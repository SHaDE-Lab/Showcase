# Surface Temperature MaRTy Core View - Radiosity Full Cube View Based - MRT Ring Based + TREE AS AIR TEMP

import numpy as np
import os
from PIL import Image
import math
from datetime import datetime
import csv
from tqdm import tqdm
import pvlib
import pandas as pd
import matplotlib.pyplot as plt
import matplotlib.patches as mpatches
import Config
import cv2
import numpy as np
import pytz
from pvlib.location import Location
from concurrent.futures import ThreadPoolExecutor, ProcessPoolExecutor
from numba import njit, prange
import threading
from queue import Queue
from functools import lru_cache
import scipy.optimize as optimize

# ══════════════════════════════════════════════════════════════════════════════
#  A-2  PET — full 3-node MEMI
#        Ported directly from Walther & Goostchel (2018) reference code.
#        All equation numbers refer to Höppe (1999) unless noted.
# ══════════════════════════════════════════════════════════════════════════════

# ── Physical constants (module-level for readability; match reference exactly) ──
_PET_po    = 1013.25          # reference pressure [hPa]
_PET_rob   = 1.06             # blood density [kg/L]
_PET_cb    = 3.64e3           # blood specific heat [J/kg/K]
_PET_cair  = 1.01e3           # air specific heat [J/kg/K]
_PET_emsk  = 0.99             # skin emissivity
_PET_emcl  = 0.95             # clothing emissivity
_PET_Lvap  = 2.42e6           # latent heat of vaporisation [J/kg]
_PET_sigm  = 5.67e-8          # Stefan-Boltzmann [W/m²K⁴]
_PET_eta   = 0.0              # body mechanical efficiency
_PET_p     = 1013.25          # local pressure [hPa]  (sea level default)
_PET_tc_set  = 36.6           # set-point core temperature [°C]
_PET_tsk_set = 34.0           # set-point skin temperature [°C]
_PET_tbody_set = 0.1 * 34.0 + 0.9 * 36.6   # weighted body temperature set-point


# ── Compute once before the time loop ─────────────────────────────────────
T_GLOBAL_MIN = 20.0   # °C  — adjust for your sites if needed
T_GLOBAL_MAX = 70.0   # °C  — Phoenix asphalt peaks ~65–68°C


class SurfaceTemperature:

    # Constants
    PI = math.pi
    TWO_PI = 2.0 * PI
    RAD = PI / 180.0
    C_STEFAN_BOLTZMANN = 5.670367e-8        # https://en.wikipedia.org/wiki/Stefan%E2%80%93Boltzmann_law
    C_ENV_EMISSION = 0.95
    C_BODY_EMISSION = 0.97
    C_BODY_ABSORPTION = 0.7
    C_LINKE_TURBIDITY = 4.2
    G_SC = 1367                             # Duffie & Beckman: The World Radiation Center (WRC) has adopted a value of 1367 W/m2, with an uncertainty of the order of 1%. 
    C_PRESSURE_AT_SEA_LEVEL = 101325
    N_RINGS = 32
    numlayers = 4
    IMAGE_SIZE = 512

    # Shadow type encoding (matches shadow_computation_v5.py output)
    SHADOW_REGULAR = 0   # black  [0,0,0]
    SHADOW_SUNLIT  = 1   # white  [255,255,255]
    SHADOW_TREE    = 2   # dark green [20,80,20]
    SHADOW_SAIL    = 3   # dark blue [0,0,100]

    TREE_SHADOW_RGB = np.array([20, 80, 20], dtype=np.uint8)
    SAIL_SHADOW_RGB = np.array([0, 0, 100], dtype=np.uint8)

    # SW albedo per segmentation class (Oke 1987; Sailor 2002)
    SURFACE_ALBEDO = {
        1: 0.00,   # Sky — radiation source, not a reflector
        2: 0.30,   # Tree / Vegetation
        3: 0.35,   # Building walls (concrete including concrete on the ground/stucco)
        4: 0.15,   # Impervious / Asphalt
        5: 0.20,   # Pervious soil
        6: 0.20,   # Moving objects (metal, cars)
        7: 0.20,   # Shade sail (HDPE fabric)
    }

    '''
    Sailor & Lu (2004) — A top-down methodology for developing diurnal and seasonal anthropogenic heating profiles for urban areas, Atmospheric Environment — cites 0.85 as standard absorptivity for urban roofing materials.
    Oke (1987) — Boundary Layer Climates, Table 1.2 — gives shortwave absorptivity ranges for common urban surfaces (concrete: 0.70–0.90, asphalt: 0.85–0.95).
    '''
    C_SW_ABSORPTION_ROOF = 0.85
    

    # Surface-specific emissivity and temperature characteristics
    SURFACE_EMISSIVITY = {
        1: 1.00,   # Sky (theoretical, will use atmospheric_radiation directly)
        2: 0.95,   # Tree/Vegetation (high emissivity, cooler)
        3: 0.90,   # Building walls (concrete/brick)
        4: 0.95,   # Impervious (asphalt/concrete)
        5: 0.93,   # Pervious soil
        6: 0.85,   # Moving objects (metal/cars)
        7: 0.90,   # Shade Sail (woven HDPE fabric, typical ε ~0.85-0.92)
    }
    
    # Expected temperature offset from air temperature when no surface temp available
    # Used for initial estimates and fallback
    SURFACE_TEMP_OFFSET = {
        1: 0,      # Sky (not used)
        2: -3,     # Trees cooler due to evapotranspiration
        3: +2,     # Building walls slightly warmer
        4: +8,     # Asphalt/concrete significantly warmer
        5: +1,     # Soil slightly warmer
        6: +4,     # Metal surfaces warmer
        7: +8,     # Sails get very hot in direct sun (thin dark fabric, low thermal mass)
    }

    # Color Table
    COLOR_TABLE = [
        [69, 117, 180],
        [116, 173, 209],
        [171, 217, 233],
        [224, 243, 248],
        [255, 255, 191],
        [254, 224, 144],
        [253, 174, 97],
        [244, 109, 67],
        [215, 48, 39]
    ]

    def __init__(self):
        """Initialize with thread pool for image creation"""
        self.image_queue = Queue()
        self.image_thread = None
        
    def __del__(self):
        """Cleanup thread pool on deletion"""
        if hasattr(self, 'image_thread') and self.image_thread and self.image_thread.is_alive():
            self.image_queue.put(None)  # Signal to stop
            self.image_thread.join()

    def get_surface_projection_factor(self, gamma):
        gamma_rad = gamma * self.RAD
        return 0.308 * math.cos(gamma_rad * (0.998 - gamma_rad * gamma_rad) / 50000)

    def get_vapor_pressure(self, relative_humidity, air_temperature):
        """Calculate actual vapor pressure from relative humidity and temperature."""
        return relative_humidity / 100 * (6.11 * 10 ** (7.5 * air_temperature / (237.3 + air_temperature)))

    def get_atmospheric_pressure(self, altitude):
        """Calculate atmospheric pressure using International Standard Atmosphere (ISA) model."""
        return self.C_PRESSURE_AT_SEA_LEVEL * (1 - 2.25577e-5 * altitude) ** 5.25588
    
    def get_relative_optical_air_mass(self, gamma, sin_gamma):
        """Calculate relative optical air mass."""
        if gamma < 0:
            return 0.0408
        return 1.0 / (sin_gamma + 0.50572 * (gamma + 6.07995) ** -1.6364)

    def get_optical_thickness(self, gamma, relative_optical_air_mass):
        """Calculate optical thickness."""
        if gamma < 0:
            return 0.0408
        thresholds = [1, 2, 3, 4, 5]
        values = [0.0435, 0.0463, 0.0491, 0.0519, 0.0548]
        for threshold, value in zip(thresholds, values):
            if gamma < threshold:
                return value
        return 1.0 / (0.9 * relative_optical_air_mass + 9.4)

    def get_extraterrestrial_radiation(self, day_of_year):
        """Calculate extraterrestrial solar radiation using orbital mechanics."""
        from math import cos, radians
        return self.G_SC * (1 + 0.03344 * cos(radians(day_of_year * 0.9856 - 2.72)))
    
    def get_incoming_radiation_cloudless(self, extraterrestrial_radiation, sin_gamma, optical_thickness,
                                         relative_optical_air_mass, atmospheric_pressure):
        """Calculate incoming radiation under cloudless conditions."""
        return extraterrestrial_radiation * sin_gamma * math.exp(
            -self.C_LINKE_TURBIDITY * optical_thickness * relative_optical_air_mass * atmospheric_pressure / self.C_PRESSURE_AT_SEA_LEVEL
        )

    def get_incoming_radiation(self, incoming_radiation_cloudless, cloud_cover):
        """Calculate incoming radiation considering cloud cover."""
        return incoming_radiation_cloudless * (1 - cloud_cover)

    def get_diffuse_radiation_cloudless(self, global_radiation_cloudless, extraterrestrial_radiation,
                                        incoming_radiation_cloudless, sin_gamma, sky_view_factor, sun_visible):
        """Calculate diffuse radiation under cloudless conditions."""
        if sin_gamma <= 0:
            return 0

        global_minus_incoming = global_radiation_cloudless - incoming_radiation_cloudless
        extraterrestrial_times_sin_gamma = extraterrestrial_radiation * sin_gamma

        diffuse_isotropic = global_minus_incoming * (
                1 - incoming_radiation_cloudless / extraterrestrial_times_sin_gamma
        ) * sky_view_factor

        diffuse_anisotropic = (
            global_minus_incoming * (incoming_radiation_cloudless / extraterrestrial_times_sin_gamma)
            if sun_visible
            else 0
        )

        return diffuse_isotropic + diffuse_anisotropic

    def get_diffuse_radiation_overcast(self, global_radiation_cloudless, sky_view_factor):
        """Calculate diffuse radiation under overcast conditions."""
        return global_radiation_cloudless * 0.28 * sky_view_factor

    def get_diffuse_radiation(self, diffuse_radiation_cloudless, diffuse_radiation_overcast, cloud_cover):
        """Calculate total diffuse radiation considering cloud cover."""
        return diffuse_radiation_cloudless * (1 - cloud_cover) + diffuse_radiation_overcast * cloud_cover

    def get_atmospheric_radiation(self, air_temperature, vapor_pressure, cloud_fraction_0to1):
        """Estimate atmospheric longwave radiation (W/m²)."""
        T_kelvin = air_temperature + 273.15
        ε_clear = 0.82 - 0.25 * 10 ** (-0.0945 * vapor_pressure)
        N_oktas = 8 * cloud_fraction_0to1
        cloud_factor = 1 + 0.21 * (N_oktas / 8) ** 2.5
        return self.C_STEFAN_BOLTZMANN * T_kelvin**4 * ε_clear * cloud_factor
    
    def get_global_radiation_cloudless(self, extraterrestrial_radiation, sin_gamma, atmospheric_pressure):
        """Calculate global radiation under cloudless conditions."""
        if sin_gamma <= 0:
            return 0

        return 0.84 * extraterrestrial_radiation * sin_gamma * math.exp(
            -0.027 * atmospheric_pressure / self.C_PRESSURE_AT_SEA_LEVEL * self.C_LINKE_TURBIDITY / sin_gamma
        )

    @staticmethod
    @njit(parallel=True, cache=True, fastmath=True)
    def _compute_lw_radiosity_jit(n_pixels, G_ambient, L_atm, prev_surface_temp_flat,
                                segmentation_flat, air_temperature,
                                surface_emissivity_flat, c_stefan_boltzmann):
        J = np.zeros(n_pixels, dtype=np.float32)
        for i in prange(n_pixels):
            seg_type = segmentation_flat[i]
            eps = surface_emissivity_flat[i]
            if seg_type == 1:               # sky pixel
                J[i] = L_atm               # atmosphere, not G_ambient
            else:
                if np.isnan(prev_surface_temp_flat[i]):
                    Ts_K = air_temperature + 273.15
                else:
                    Ts_K = prev_surface_temp_flat[i] + 273.15
                # Incropera Table 12.1: J = ε·σ·T⁴ + (1−ε)·G
                J[i] = eps * c_stefan_boltzmann * Ts_K**4 + (1.0 - eps) * G_ambient
        return J.reshape((512, 512))

    def compute_lw_radiosity(self, n_pixels, G_ambient, L_atm, prev_surface_temp,
                            segmentation_data, air_temperature):
        emissivity_map = np.zeros_like(segmentation_data, dtype=np.float32)
        for seg_type, emissivity in self.SURFACE_EMISSIVITY.items():
            emissivity_map[segmentation_data == seg_type] = emissivity

        return self._compute_lw_radiosity_jit(
            n_pixels,
            G_ambient,    # ← replaces atmospheric_radiation for surface pixels
            L_atm,        # ← sky pixels still emit this (they ARE the sky)
            prev_surface_temp.flatten(),
            segmentation_data.flatten(),
            air_temperature,
            emissivity_map.flatten(),
            self.C_STEFAN_BOLTZMANN
        )

    def compute_net_radiation(self, incoming_radiation, diffuse_radiation,
                                G_ambient, L_atm, shadow_data,
                                longwave_radiation, tau_direct=1.0,
                                gap_fraction=1.0, air_temperature=30.0,
                                tau_sail=1.0,
                                sw_absorption_map=None): 
        
        # ── Resolve per-pixel SW absorption ──────────────────────────────────────
        # sw_absorption_map = (1 − albedo) per surface pixel, physically decoupled
        # from C_BODY_ABSORPTION=0.7 which belongs only in MRFD/MRT calculation.
        # Fallback to C_BODY_ABSORPTION preserves backward compatibility.
        # Reference: Oke (1987) Table 1.2; Sailor (2002).
        if sw_absorption_map is not None:
            alpha_sw = sw_absorption_map      # shape (512, 512)
        else:
            alpha_sw = self.C_BODY_ABSORPTION # scalar fallback

        # ── Tree LW (existing, unchanged) ─────────────────────────────────────
        eps_tree = self.SURFACE_EMISSIVITY[2]
        T_tree_K = (air_temperature) + 273.15
        L_veg    = eps_tree * self.C_STEFAN_BOLTZMANN * T_tree_K**4
        L_tree   = gap_fraction * G_ambient + (1.0 - gap_fraction) * L_veg

        # ── Sail LW (NEW) ──────────────────────────────────────────────────────
        # The shade sail fabric absorbs SW and re-emits as LW at elevated temperature.
        # Surfaces below the sail see:
        #   - Transmitted sky/enclosure ambient through sail gaps:  tau_sail * G_ambient
        #   - Thermal emission from the hot sail fabric itself:     (1 - tau_sail) * L_sail_emit
        #
        # Physically consistent sail temperature for LW emission in net_radiation
        h_conv_sail  = 5.6 + 3.9 * max(1.0, 0.5)   # conservative: assume light wind
        alpha_sail   = 1.0 - self.SURFACE_ALBEDO[7]
        eps_sail     = self.SURFACE_EMISSIVITY[7]
        T_sail_phys  = air_temperature + 5.0         # initial guess
        for _ in range(20):
            Ts_K_s = T_sail_phys + 273.15
            F_s  = (alpha_sail * incoming_radiation
                    - 2 * eps_sail * self.C_STEFAN_BOLTZMANN * Ts_K_s**4
                    - 2 * h_conv_sail * (T_sail_phys - air_temperature))
            dF_s = (-8 * eps_sail * self.C_STEFAN_BOLTZMANN * Ts_K_s**3
                    - 2 * h_conv_sail)
            step_s = F_s / dF_s
            T_sail_phys -= step_s
            if abs(step_s) < 0.001:
                break
        T_sail_K    = T_sail_phys + 273.15
        L_sail_emit = eps_sail * self.C_STEFAN_BOLTZMANN * T_sail_K**4

        # Under sail shadow: surfaces receive transmitted ambient LW + sail thermal emission.
        # tau_sail already accounts for partial coverage (blended in compute_sail_transmissivity).
        L_sail = tau_sail * G_ambient + (1.0 - tau_sail) * L_sail_emit

        # ── Net radiation budgets — alpha_sw replaces C_BODY_ABSORPTION ──────────
        sunlit_budget      = alpha_sw * (incoming_radiation + diffuse_radiation) + G_ambient
        reg_shadow_budget  = alpha_sw * diffuse_radiation + G_ambient
        tree_shadow_budget = (alpha_sw
                            * (tau_direct * incoming_radiation + gap_fraction * diffuse_radiation)
                            + L_tree)
        sail_shadow_budget = (alpha_sw
                            * tau_sail * (incoming_radiation + diffuse_radiation)
                            + L_sail)

        sw_lw_in = np.where(shadow_data == self.SHADOW_REGULAR, reg_shadow_budget,  sunlit_budget)
        sw_lw_in = np.where(shadow_data == self.SHADOW_TREE,    tree_shadow_budget, sw_lw_in)
        sw_lw_in = np.where(shadow_data == self.SHADOW_SAIL,    sail_shadow_budget, sw_lw_in)

        return sw_lw_in - longwave_radiation

    def compute_conduction(self, surface_temperature, Qg, deltaT, htcap, lambda_conduction, thick, tlayer, Tdeep=300.0):
        """Compute conduction heat flux and update temperature layers (vectorized for efficiency)."""
        numlayers = len(thick)
        rows, cols = surface_temperature.shape

        tlayer = np.asarray(tlayer, dtype=np.float32).reshape(rows, cols, numlayers)

        surface_temperature_K = surface_temperature + 273.15  

        A = np.zeros((rows, cols, numlayers))
        B = np.zeros((rows, cols, numlayers))
        D = np.zeros((rows, cols, numlayers))
        R = np.zeros((rows, cols, numlayers))
        gam = np.zeros((rows, cols, numlayers))
        denom = np.zeros((rows, cols, numlayers))

        uc = 0.5

        # Surface Layer (Vectorized)
        lambd_o_thick = lambda_conduction / (thick[0] + thick[1])
        B[:, :, 0] = (thick[0] * htcap) / deltaT + 2 * uc * lambd_o_thick
        D[:, :, 0] = -2 * uc * lambd_o_thick
        R[:, :, 0] = (
            -2 * (1.0 - uc) * lambd_o_thick * (tlayer[:, :, 0] - tlayer[:, :, 1])
            + tlayer[:, :, 0] * thick[0] * htcap / deltaT
            + (surface_temperature_K - tlayer[:, :, 0]) * lambda_conduction / (thick[0] * 2)
        )

        # Interior Layers (Vectorized)
        for k in range(1, numlayers - 1):
            lambd_o_thick = lambda_conduction / (thick[k - 1] + thick[k])
            lambd_o_thick2 = lambda_conduction / (thick[k] + thick[k + 1])

            A[:, :, k] = -2 * uc * lambd_o_thick
            B[:, :, k] = thick[k] * htcap / deltaT + 2 * uc * (lambd_o_thick + lambd_o_thick2)
            D[:, :, k] = -2 * uc * lambd_o_thick2
            R[:, :, k] = (
                -2 * (1 - uc)
                * (
                    lambd_o_thick * (tlayer[:, :, k] - tlayer[:, :, k - 1])
                    + lambd_o_thick2 * (tlayer[:, :, k] - tlayer[:, :, k + 1])
                )
                + tlayer[:, :, k] * thick[k] * htcap / deltaT
            )

        # Bottom Layer (Vectorized)
        lambd_o_thick = lambda_conduction / (thick[numlayers - 2] + thick[numlayers - 1])
        A[:, :, numlayers - 1] = -2 * uc * lambd_o_thick
        B[:, :, numlayers - 1] = (
            thick[numlayers - 1] * htcap / deltaT
            + 2 * uc * (lambd_o_thick + lambda_conduction / thick[numlayers - 1])
        )
        R[:, :, numlayers - 1] = (
            -2 * (1 - uc)
            * (
                lambd_o_thick * (tlayer[:, :, numlayers - 1] - tlayer[:, :, numlayers - 2])
                + lambda_conduction * tlayer[:, :, numlayers - 1] / thick[numlayers - 1]
            )
            + 2 * lambda_conduction * Tdeep / thick[numlayers - 1]
            + tlayer[:, :, numlayers - 1] * thick[numlayers - 1] * htcap / deltaT
        )

        # Solve Tridiagonal System (Vectorized)
        gam[:, :, 0] = -D[:, :, 0] / B[:, :, 0]
        tlayer[:, :, 0] = R[:, :, 0] / B[:, :, 0]

        for k in range(1, numlayers):
            denom[:, :, k] = B[:, :, k] + A[:, :, k] * gam[:, :, k - 1]
            tlayer[:, :, k] = (R[:, :, k] - A[:, :, k] * tlayer[:, :, k - 1]) / denom[:, :, k]
            gam[:, :, k] = -D[:, :, k] / denom[:, :, k]

        for k in range(numlayers - 2, -1, -1):
            tlayer[:, :, k] += gam[:, :, k] * tlayer[:, :, k + 1]

        # Update Qg for all pixels (Vectorized)
        Qg = (surface_temperature_K - tlayer[:, :, 0]) * lambda_conduction / (thick[0] * 2)

        return Qg

    def compute_surface_conduction(self, n_pixels, segmentation_data, Qg, tlayer, thick, surface_temperature, deltaT):
        """Compute surface conduction for all pixels using vectorized operations."""
        # Define material properties based on segmentation types (Vectorized mapping)
        htcap = np.full_like(segmentation_data, 2100000, dtype=np.float32)
        lambda_conduction = np.full_like(segmentation_data, 0.8, dtype=np.float32)

        htcap[segmentation_data == 4] = 2000000
        lambda_conduction[segmentation_data == 4] = 0.75

        # Pervious / soil / grass (class 5) — Oke (1987) Table 2.1; Campbell & Norman (1998)
        # Dry sandy soil representative of Phoenix desert pervious surfaces.
        # Lower heat capacity and conductivity prevent spurious thermal mass accumulation.
        htcap[segmentation_data == 5] = 1300000    # J/m³K — dry sandy soil
        lambda_conduction[segmentation_data == 5] = 0.30  # W/mK — dry sandy soil

        Qg = np.array(Qg).reshape((512, 512))

        Qg[:] = self.compute_conduction(
            surface_temperature, Qg, deltaT, htcap, lambda_conduction, thick, tlayer
        )

        return Qg

    # def compute_surface_temperature(self, minute_delta, air_temperature, wind_velocity, new_q, segmentation_data, Qg, shadow_type=None):
    #     """Compute the updated surface temperature for each pixel."""
    #     new_q = new_q.reshape((512, 512)) if new_q.shape[0] == 262144 else new_q
    #     Qg = Qg.reshape((512, 512)) if Qg.shape[0] == 262144 else Qg

    #     C_BOWEN = {
    #         1: 0,      # Sky (not used)
    #         2: 1.5,    # Tree / vegetation (low Bowen)
    #         3: 25,     # Building walls (very low evaporation)
    #         4: 22,     # Impervious (asphalt, concrete)
    #         5: 0.8,    # Pervious soil (moisture available)
    #         6: 22      # Moving objects (cars, metal surfaces)
    #     }

    #     bowen_array = np.array([0, 0, 0.2, 4, 3, 0.4, 3, 3], dtype=np.float32)  # ← extend to index 7
    #     safe_seg    = np.clip(segmentation_data, 0, 7)                            # ← extended from 6
    #     bowen_values = bowen_array[safe_seg]

    #     if shadow_type is not None:
    #         tree_shadow_mask = (shadow_type == self.SHADOW_TREE)
    #         # Trees: reduce Bowen ~30% due to canopy evapotranspiration cooling
    #         bowen_values = np.where(tree_shadow_mask, bowen_values * 0.7, bowen_values)

    #         # Shade sails: NO Bowen reduction — fabric provides no moisture,
    #         # and the hot sail surface slightly elevates downwelling LW.
    #         # Bowen remains unchanged for SHADOW_SAIL pixels (no-op, explicit for clarity).
    #         # sail_shadow_mask = (shadow_type == self.SHADOW_SAIL)
    #         # bowen_values = np.where(sail_shadow_mask, bowen_values, bowen_values)  # identity

    #     correction_factor = (6.2 + 4.26 * wind_velocity) * (1 + 1 / np.maximum(0.1, bowen_values))
    #     correction_factor = np.maximum(correction_factor, 8.0)
        
    #     # In the C++ source code it was + Qg which is incorrect, verify with Ari
    #     return air_temperature + (new_q - Qg) / correction_factor

    def compute_surface_temperature_physical(
        self,
        q_net_radiation,      # Q* = net SW + LW absorbed by surface [W/m²]
        Qg,                   # conductive flux from Crank-Nicolson [W/m²]
        air_temperature,      # Ta [°C]
        wind_velocity,        # u [m/s]
        relative_humidity,    # RH [0-1]
        segmentation_data,    # per-pixel surface class
        z_ref=1.1,            # reference height for wind [m]
        z0_momentum=0.01,     # roughness length for momentum [m]
    ):
        """
        Solve surface energy balance implicitly for Ts:
            Q*(Ts) - QH(Ts) - QE(Ts) - QG = 0

        Q*(Ts)  = q_net_radiation - ε·σ·(Ts⁴ - Ta_K⁴)   [LW emission residual]
        QH(Ts)  = ρ·cp·(Ts - Ta) / ra                     [sensible heat]
        QE(Ts)  = ρ·cp/γ · (es(Ts) - ea) / (ra + rs)      [latent heat, Penman]
        QG      = already solved by Crank-Nicolson

        Newton-Raphson: Ts_{n+1} = Ts_n - F(Ts_n)/F'(Ts_n)
        Converges in 3-5 iterations for urban surfaces.
        """
        Ta_K = air_temperature + 273.15

        # ── Aerodynamic resistance [s/m] ──────────────────────────────────────────
        # Thom (1975): ra = [ln(z/z0)]² / (κ² · u)
        # κ = 0.41 (von Karman), z=reference height, z0=roughness length
        # Note: z0_momentum here (default 0.01, local urban surface roughness)
        # is intentionally different from the z0=0.03 (open/station exposure)
        # used in main.py's _wind() to reduce 10 m station wind to 1.1 m.
        # wind_velocity passed in is already at z_ref=1.1 m — this ra formula
        # is Thom (1975) aerodynamic resistance from 1.1 m down to the local
        # surface, not a second station-to-pedestrian height reduction.
        kappa = 0.41
        u_eff = np.maximum(wind_velocity, 0.5)   # floor at 0.5 m/s, avoids singularity
        ra = (np.log(z_ref / z0_momentum) ** 2) / (kappa**2 * u_eff)   # scalar [s/m]

        # ── Surface resistance rs [s/m] ───────────────────────────────────────────
        # Per-surface lookup:
        #   Sky(1)=0, Veg(2)=100 (C3 urban trees, Jarvis 1976),
        #   Wall(3)=∞(dry), Asphalt(4)=∞(dry), Soil(5)=200(dry Phoenix),
        #   Cars(6)=∞, Sail(7)=∞
        rs_lut = np.array([0, 0, 100, 1e6, 1e6, 200, 1e6, 1e6], dtype=np.float32)
        safe_seg = np.clip(segmentation_data, 0, 7).astype(np.int32)
        rs = rs_lut[safe_seg]   # shape (512,512)

        # ── Air thermodynamic properties ──────────────────────────────────────────
        rho_air = 1.2          # [kg/m³] at ~30°C, sea level
        cp_air  = 1005.0       # [J/kg·K]
        gamma   = 66.0         # psychrometric constant [Pa/K] at ~30°C

        # Actual vapour pressure ea [Pa]
        ea = relative_humidity * 610.78 * np.exp(17.27 * air_temperature / (air_temperature + 237.3))

        # Emissivity map
        eps_lut = np.array(
            [1.0, 1.0, 0.95, 0.90, 0.95, 0.93, 0.85, 0.90], dtype=np.float32
        )
        eps = eps_lut[safe_seg]

        # ── Newton-Raphson loop ───────────────────────────────────────────────────
        Ts = np.full_like(q_net_radiation, air_temperature, dtype=np.float64)

        for _ in range(10):   # 5 is usually enough; 10 for safety
            Ts_K = Ts + 273.15

            # Saturated vapour pressure at Ts [Pa]  (Buck 1981)
            es_Ts = 610.78 * np.exp(17.27 * Ts / (Ts + 237.3))

            # Slope of es(T) curve [Pa/K]  (for QE derivative)
            Delta = 4098.0 * es_Ts / (Ts + 237.3) ** 2

            # QH [W/m²]
            QH = rho_air * cp_air * (Ts - air_temperature) / ra

            # QE [W/m²]  — Penman-Monteith
            # rs→∞ for dry surfaces ⟹ QE→0 automatically
            QE = (rho_air * cp_air / gamma) * (es_Ts - ea) / (ra + rs)

            # Net LW residual (LW emission at Ts vs LW emission at Ta)
            # q_net_radiation already includes absorbed LW↓;
            # we only correct for the Ts-dependent emission term
            delta_LW = eps * self.C_STEFAN_BOLTZMANN * (Ts_K**4 - Ta_K**4)

            # Energy balance residual
            F  = q_net_radiation - delta_LW - QH - QE - Qg

            # Derivative dF/dTs
            dQH_dTs     = rho_air * cp_air / ra
            dQE_dTs     = (rho_air * cp_air / gamma) * Delta / (ra + rs)
            ddeltaLW_dTs = eps * 4.0 * self.C_STEFAN_BOLTZMANN * Ts_K**3

            dF = -ddeltaLW_dTs - dQH_dTs - dQE_dTs

            # Newton step  — mask avoids divide-by-zero at sky pixels
            step = np.where(np.abs(dF) > 1e-6, F / dF, 0.0)
            Ts  -= step

            if np.max(np.abs(step)) < 0.001:   # 1 mK convergence
                break

        # Sky pixels stay NaN
        sky_mask = (segmentation_data == 1)
        Ts[sky_mask] = np.nan

        return Ts.astype(np.float32)
    

    def apply_physical_bounds(self, Ts, segmentation_data, air_temperature,
                            incoming_radiation, wind_velocity):
        """
        Replace hard pins with physically-motivated bounds derived from
        the surface energy balance at each class's characteristic conditions.
        """
        # ── Trees: wet-bulb limit (Penman-Monteith with low rs) ──────────────
        # At rs=50 s/m (well-watered C3), Ts cannot exceed Ta + ~3°C in Phoenix.
        # Minimum is wet-bulb temperature (full evapotranspiration).
        T_wet_bulb = air_temperature - 4.0   # conservative for Phoenix RH~20%
        T_tree_max = air_temperature + 3.0
        tree_mask  = (segmentation_data == 2)
        Ts[tree_mask] = np.clip(Ts[tree_mask], T_wet_bulb, T_tree_max)

        # ── Grass/pervious: same logic, tighter bounds ─────────────────────────
        grass_mask = (segmentation_data == 5)
        Ts[grass_mask] = np.clip(Ts[grass_mask], T_wet_bulb, air_temperature + 2.0)

        # ── Shade sail: thin-membrane equilibrium (algebraic, no thermal mass) ─
        # Balance: α·SW = 2·ε·σ·Ts⁴ + 2·h_conv·(Ts - Ta)
        # (factor 2: both faces emit/convect)
        sail_mask  = (segmentation_data == 7)
        if np.any(sail_mask):
            alpha_sail = 1.0 - self.SURFACE_ALBEDO[7]   # ~0.80
            eps_sail   = self.SURFACE_EMISSIVITY[7]       # ~0.90
            h_conv     = 5.6 + 3.9 * max(wind_velocity, 0.5)
            Ta_K       = air_temperature + 273.15

            # Newton solve for sail pixels (scalar, then broadcast)
            Ts_sail = air_temperature + 5.0   # initial guess
            for _ in range(20):
                Ts_sail_K = Ts_sail + 273.15
                F  = (alpha_sail * incoming_radiation
                    - 2 * eps_sail * self.C_STEFAN_BOLTZMANN * Ts_sail_K**4
                    - 2 * h_conv * (Ts_sail - air_temperature))
                dF = (-8 * eps_sail * self.C_STEFAN_BOLTZMANN * Ts_sail_K**3
                    - 2 * h_conv)
                step = F / dF
                Ts_sail -= step
                if abs(step) < 0.001:
                    break
            Ts[sail_mask] = Ts_sail

        return Ts

    def spinup_surface_temperatures(self, segmentation_data, air_temperature_night,
                                    L_atm_night, tlayer, thickness,
                                    n_spinup_hours=4, minute_delta=30):
        """
        Run the SEB solver from 03:00 with zero SW, driving surfaces to
        radiative-convective equilibrium under nocturnal LW forcing.

        At convergence:
            ε·σ·Ts⁴ = ε·L_atm  +  QH_night  +  QG_night
        
        This is the unique physical initial condition — no free parameters.
        """
        n_steps = int(n_spinup_hours * 60 / minute_delta)

        Ts_init = {}
        for d in self.DIRECTIONS:
            seg = segmentation_data[d]
            Ts = np.full((512, 512), air_temperature_night, dtype=np.float32)
            Ts[seg == 1] = np.nan
            Ts_init[d] = Ts

        for step in range(n_steps):
            for d in self.DIRECTIONS:
                seg = segmentation_data[d]

                # ── Nocturnal net radiation: absorbed L_atm minus surface emission ──
                # This is what drives surfaces to their physical nocturnal equilibrium.
                # Sky pixels receive nothing (they ARE the atmosphere).
                eps_lut = np.array(
                    [1.0, 1.0, 0.95, 0.90, 0.95, 0.93, 0.85, 0.90], dtype=np.float32
                )
                safe_seg = np.clip(seg, 0, 7).astype(np.int32)
                eps = eps_lut[safe_seg]

                Ts_K = np.where(
                    np.isnan(Ts_init[d]),
                    air_temperature_night + 273.15,
                    Ts_init[d] + 273.15
                )
                # Q* = ε·L_atm↓ − ε·σ·Ts⁴  (net LW at surface, no SW at night)
                q_net_night = (
                    eps * L_atm_night
                    - eps * self.C_STEFAN_BOLTZMANN * Ts_K**4
                ).astype(np.float32)
                q_net_night[seg == 1] = 0.0   # sky pixels: no balance needed

                Qg_d = self.compute_surface_conduction(
                    self.IMAGE_SIZE**2, seg,
                    np.zeros((512, 512), dtype=np.float32),
                    tlayer[d], thickness,
                    np.where(np.isnan(Ts_init[d]), air_temperature_night, Ts_init[d]),
                    minute_delta * 60
                )
                Ts_init[d] = self.compute_surface_temperature_physical(
                    q_net_radiation=q_net_night,
                    Qg=Qg_d,
                    air_temperature=air_temperature_night,
                    wind_velocity=1.0,
                    relative_humidity=0.40,
                    segmentation_data=seg,
                )

                # ── Tree override in spinup ───────────────────────────────────────────────
                tree_mask = (seg == 2)
                if np.any(tree_mask):
                    Ts_init[d][tree_mask] = air_temperature_night

        return Ts_init   # physically consistent initial state, no offsets needed

    def compute_average_radiation_for_fisheye(
            self,
            n_pixels,
            diffuse_radiation,
            long_wave_radiation_by_direction,
            ring_indices_by_fisheye_subset,
            fractions_by_fisheye_subset,
            long_wave_indices,
            fisheye_indices,
            n_rings,
            c_body_absorption,
            c_body_emission,
    ):
        """Compute the average radiation for a fisheye image."""
        ring_diffuse_shortwave = np.zeros(n_rings, dtype=np.float64)
        ring_longwave = np.zeros(n_rings, dtype=np.float64)
        ring_total_fraction = np.zeros(n_rings, dtype=np.float64)

        diffuse_radiation_term = diffuse_radiation * c_body_absorption / c_body_emission

        # print("\nCompute the average radiation for a fisheye image...")
        
        for d in range(5):
            direction_key = self.DIRECTIONS[long_wave_indices[d]]
            long_wave = long_wave_radiation_by_direction[direction_key]
            ring_indices = ring_indices_by_fisheye_subset[direction_key]
            fraction = fractions_by_fisheye_subset[direction_key]

            if len(fraction) != n_pixels:
                if len(fraction) == 512:
                    fraction = np.resize(fraction, (n_pixels,))
                else:
                    raise ValueError(
                        f"[ERROR] Fraction array size mismatch. Expected {n_pixels}, got {len(fraction)} for direction {direction_key}"
                    )

            if len(ring_indices) != n_pixels:
                if len(ring_indices) == 512:
                    ring_indices = np.resize(ring_indices, (n_pixels,))
                else:
                    raise ValueError(
                        f"[ERROR] Ring indices size mismatch. Expected {n_pixels}, got {len(ring_indices)} for direction {direction_key}"
                    )

            if Config.debug_mode:
                print(f"[DEBUG] Max ring index: {np.max(ring_indices)}, Min ring index: {np.min(ring_indices)}")
                print(f"[DEBUG] Direction {d}: Processing {len(ring_indices)} pixels")
                print(f"[DEBUG] Direction {d}: First 10 ring indices: {ring_indices[:10]}")
                print(f"[DEBUG] Direction {d}: First 10 fraction values: {fraction[:10]}")
                print(f"[DEBUG] Direction {d}: First 10 longwave values before sum: {long_wave[:10]}")
                print(f"[DEBUG] Direction {d}: First 10 diffuse shortwave values before sum: {diffuse_radiation_term}")
                
            # ring_total_fraction = np.asarray(ring_total_fraction, dtype=np.float64)
            # ring_longwave = np.asarray(ring_longwave, dtype=np.float64)
            # ring_diffuse_shortwave = np.asarray(ring_diffuse_shortwave, dtype=np.float64)

            fraction = np.asarray(fraction, dtype=np.float64)
            ring_indices = np.asarray(ring_indices, dtype=np.int32)
            long_wave = np.asarray(long_wave).flatten()

            valid_mask = fraction >= 0
            ring_indices = np.clip(ring_indices, 0, n_rings - 1)

            np.add.at(ring_total_fraction, ring_indices[valid_mask], fraction[valid_mask])
            np.add.at(ring_longwave, ring_indices[valid_mask], long_wave[valid_mask] * fraction[valid_mask])
            np.add.at(ring_diffuse_shortwave, ring_indices[valid_mask], diffuse_radiation_term * fraction[valid_mask])

        average_diffuse_shortwave = sum(
            (ring_diffuse_shortwave[i] / ring_total_fraction[i]) if ring_total_fraction[i] > 0 else 0
            for i in range(n_rings)
        ) / n_rings

        average_longwave = sum(
            (ring_longwave[i] / ring_total_fraction[i]) if ring_total_fraction[i] > 0 else 0
            for i in range(n_rings)
        ) / n_rings

        if Config.debug_mode:
            print(f"[DEBUG] Computed average diffuse shortwave: {average_diffuse_shortwave}")
            print(f"[DEBUG] Computed average longwave: {average_longwave}")

        return average_diffuse_shortwave, average_longwave


    def precompute_cubemap_view_factors(self):
        """
        For each pixel on each cubemap face, compute its view factor
        contribution to the sensor point at the cube center.
        
        For face 'bottom' (normal pointing up +Z):
            pixel at (u,v) has direction vector d = normalize(u, v, 1)
            cos_theta = dot(d, face_normal) / |d|
            solid_angle ∝ cos_theta / |d|²
        
        Returns vf_map: dict of {direction: (512,512) array}
        Σ_all_pixels(vf_map) = 1.0  (partition of unity)
        """
        vf_map = {}
        
        # Pixel coordinates normalized to [-1, 1]
        i = np.linspace(-1, 1, 512)
        u, v = np.meshgrid(i, i)
        
        face_normals = {
            'front':  np.array([0,  0,  1]),
            'back':   np.array([0,  0, -1]),
            'left':   np.array([-1, 0,  0]),
            'right':  np.array([1,  0,  0]),
            'top':    np.array([0,  1,  0]),
            'bottom': np.array([0, -1,  0]),
        }
        
        face_tangents = {
            'front':  (np.array([1,0,0]), np.array([0,1,0])),
            'back':   (np.array([-1,0,0]), np.array([0,1,0])),
            'left':   (np.array([0,0,1]), np.array([0,1,0])),
            'right':  (np.array([0,0,-1]), np.array([0,1,0])),
            'top':    (np.array([1,0,0]), np.array([0,0,-1])),
            'bottom': (np.array([1,0,0]), np.array([0,0,1])),
        }
        
        all_weights = {}
        total_weight = 0.0
        
        for direction in self.DIRECTIONS:
            normal = face_normals[direction]
            tan1, tan2 = face_tangents[direction]
            
            # Direction vector from sensor to each pixel
            # d = u*tan1 + v*tan2 + 1*normal  (cubemap projection)
            dx = u * tan1[0] + v * tan2[0] + normal[0]
            dy = u * tan1[1] + v * tan2[1] + normal[1]
            dz = u * tan1[2] + v * tan2[2] + normal[2]
            
            r_sq = dx**2 + dy**2 + dz**2
            r    = np.sqrt(r_sq)
            
            # cos(theta) = dot(d/|d|, normal)
            cos_theta = (dx*normal[0] + dy*normal[1] + dz*normal[2]) / r
            cos_theta = np.maximum(cos_theta, 0.0)
            
            # Differential solid angle weight: cos(theta) / r²
            # (the 1/r² is what makes pixels near face center
            #  contribute more than corner pixels)
            weight = cos_theta / r_sq
            
            all_weights[direction] = weight
            total_weight += np.sum(weight)
        
        # Normalize so all weights sum to 1.0
        for direction in self.DIRECTIONS:
            vf_map[direction] = all_weights[direction] / total_weight
        
        return vf_map

    # 90-degree directions
    NORTH = 0
    EAST = 1
    SOUTH = 2
    WEST = 3
    UP = 4
    DOWN = 5

    # Fisheye subsets
    TOP = 0
    RIGHT = 1
    BOTTOM = 2
    LEFT = 3
    CENTER = 4

    # Constants for longWaveIndicies and fisheyeIndicies
    long_wave_indices = [
        [UP, EAST, DOWN, WEST, NORTH],
        [UP, SOUTH, DOWN, NORTH, EAST],
        [UP, WEST, BOTTOM, EAST, SOUTH],
        [UP, NORTH, BOTTOM, SOUTH, WEST],
        [NORTH, EAST, SOUTH, WEST, UP],
        [NORTH, EAST, SOUTH, WEST, DOWN],
    ]

    fisheye_indices = [
        [TOP, RIGHT, BOTTOM, LEFT, CENTER],
        [LEFT, RIGHT, LEFT, LEFT, CENTER],
        [BOTTOM, RIGHT, TOP, LEFT, CENTER],
        [RIGHT, RIGHT, RIGHT, RIGHT, CENTER],
        [BOTTOM, BOTTOM, BOTTOM, BOTTOM, CENTER],
        [TOP, TOP, TOP, TOP, CENTER],
    ]

    def compute_average_radiation_for_each_direction(
        self,
        n_pixels,
        diffuse_radiation,
        long_wave_radiation,
        ring_indices_by_fisheye_subset,
        fractions_by_fisheye_subset,
        average_diffuse_shortwave_by_direction,
        average_longwave_by_direction,
    ):
        """Compute average radiation for each of the six directions."""
        if Config.debug_mode:
            print(f"[DEBUG] Before accumulation - avg_dsw_by_dir: {average_diffuse_shortwave_by_direction}")
            print(f"[DEBUG] Before accumulation - avg_lw_by_dir: {average_longwave_by_direction}")

        print("Computing Average Radiation for Each Direction.")

        for i in range(6):
            diffuse_value, longwave_value = self.compute_average_radiation_for_fisheye(
                n_pixels,
                diffuse_radiation,
                long_wave_radiation,
                ring_indices_by_fisheye_subset,
                fractions_by_fisheye_subset,
                self.long_wave_indices[i],
                self.fisheye_indices[i],
                self.N_RINGS,
                self.C_BODY_ABSORPTION,
                self.C_BODY_EMISSION
            )

            average_diffuse_shortwave_by_direction[i] = diffuse_value
            average_longwave_by_direction[i] = longwave_value

        if Config.debug_mode:
            print(f"[DEBUG] After accumulation - avg_dsw_by_dir: {average_diffuse_shortwave_by_direction}")
            print(f"[DEBUG] After accumulation - avg_lw_by_dir: {average_longwave_by_direction}")

        return 1

    def compute_mean_radiant_temperature(self, mrfd, air_temperature, wind_velocity):
        """Compute the Mean Radiant Temperature (MRT)."""
        if mrfd == 0:
            print("[WARNING] No radiation detected! Approximating MRT using operative temperature.")
            sqrt_10v = np.sqrt(10 * wind_velocity) if wind_velocity > 0 else 1
            operative_temperature = (air_temperature * sqrt_10v) / (1 + sqrt_10v)
            return operative_temperature

        MRT = (mrfd / (self.C_BODY_EMISSION * self.C_STEFAN_BOLTZMANN)) ** 0.25 - 273.15

        if Config.debug_mode:
            print(f"[DEBUG] Computed MRFD: {mrfd}")
            print(f"[DEBUG] Computed MRT: {MRT}")

        return MRT

    def compute_mean_radiant_flux_density(
        self,
        average_diffuse_shortwave_by_direction,
        average_longwave_by_direction,
        c_body_absorption=0.7,
        c_body_emission=0.97
    ):
        """Simple CR3000-compatible MRFD calculation"""
        weighting_factors = [0.22, 0.22, 0.22, 0.22, 0.06, 0.06]
        
        mrfd = sum(
            weighting_factors[i] * (
                c_body_absorption * average_diffuse_shortwave_by_direction[i] + 
                c_body_emission * average_longwave_by_direction[i]
            )
            for i in range(6)
        )
        
        return mrfd
        
    def compute_multiple_mrts(self, sensor_sw, sensor_lw, calc_sw, calc_lw, air_temperature, wind_velocity):
        """
        Compute 4 different MRT values using different combinations of sensor and calculated radiation.
        
        Args:
            sensor_sw: list of 6 sensor shortwave values [Left, Right, Front, Back, Up, Down]
            sensor_lw: list of 6 sensor longwave values [Left, Right, Front, Back, Up, Down]
            calc_sw: list of 6 calculated shortwave values [Left, Right, Front, Back, Up, Down]
            calc_lw: list of 6 calculated longwave values [Left, Right, Front, Back, Up, Down]
            air_temperature: air temperature in Celsius
            wind_velocity: wind velocity in m/s
            
        Returns:
            dict with keys: 'sensors_data', 'calc_sw_sensor_lw', 'sensor_sw_calc_lw', 'calc_sw_calc_lw'
        """
        
        # MRT 1: Sensors Data (both SW and LW from sensors)
        mrfd_sensors = self.compute_mean_radiant_flux_density(
            average_diffuse_shortwave_by_direction=sensor_sw,
            average_longwave_by_direction=sensor_lw,
            c_body_absorption=0.7,
            c_body_emission=0.97
        )
        mrt_sensors = self.compute_mean_radiant_temperature(
            mrfd_sensors, air_temperature, wind_velocity
        )
        
        # MRT 2: Calc SW + Sensor LW
        mrfd_calc_sw_sensor_lw = self.compute_mean_radiant_flux_density(
            average_diffuse_shortwave_by_direction=calc_sw,
            average_longwave_by_direction=sensor_lw,
            c_body_absorption=0.7,
            c_body_emission=0.97
        )
        mrt_calc_sw_sensor_lw = self.compute_mean_radiant_temperature(
            mrfd_calc_sw_sensor_lw, air_temperature, wind_velocity
        )
        
        # MRT 3: Sensor SW + Calc LW
        mrfd_sensor_sw_calc_lw = self.compute_mean_radiant_flux_density(
            average_diffuse_shortwave_by_direction=sensor_sw,
            average_longwave_by_direction=calc_lw,
            c_body_absorption=0.7,
            c_body_emission=0.97
        )
        mrt_sensor_sw_calc_lw = self.compute_mean_radiant_temperature(
            mrfd_sensor_sw_calc_lw, air_temperature, wind_velocity
        )
        
        # MRT 4: Calc SW + Calc LW (both calculated) - NEW
        mrfd_calc_sw_calc_lw = self.compute_mean_radiant_flux_density(
            average_diffuse_shortwave_by_direction=calc_sw,
            average_longwave_by_direction=calc_lw,
            c_body_absorption=0.7,
            c_body_emission=0.97
        )
        mrt_calc_sw_calc_lw = self.compute_mean_radiant_temperature(
            mrfd_calc_sw_calc_lw, air_temperature, wind_velocity
        )
        
        if Config.debug_mode:
            print(f"[MRT_CALC] Sensors Data: {mrt_sensors:.2f} °C")
            print(f"[MRT_CALC] Calc SW + Sensor LW: {mrt_calc_sw_sensor_lw:.2f} °C")
            print(f"[MRT_CALC] Sensor SW + Calc LW: {mrt_sensor_sw_calc_lw:.2f} °C")
            print(f"[MRT_CALC] Calc SW + Calc LW: {mrt_calc_sw_calc_lw:.2f} °C")
        
        return {
            'sensors_data': mrt_sensors,
            'calc_sw_sensor_lw': mrt_calc_sw_sensor_lw,
            'sensor_sw_calc_lw': mrt_sensor_sw_calc_lw,
            'calc_sw_calc_lw': mrt_calc_sw_calc_lw  # NEW
        }

    # def compute_canopy_transmissivity(self, segmentation_data, solar_elevation_deg, site_no):
    #     top_seg = segmentation_data.get("top")
        
    #     if top_seg is None:
    #         return 1.0, {"tree_fraction": 0.0, "gap_fraction": 1.0, "LAI": 0.0}
        
    #     total_pixels      = top_seg.size
    #     tree_pixels       = np.sum(top_seg == 2)
    #     sky_pixels        = np.sum(top_seg == 1)
    #     building_pixels   = np.sum(top_seg == 3)
    #     impervious_pixels = np.sum(top_seg == 4)

    #     tree_fraction   = tree_pixels    / total_pixels
    #     gap_fraction    = sky_pixels     / total_pixels
    #     opaque_fraction = (building_pixels + impervious_pixels) / total_pixels

    #     # --- Opaque overhead (building/roof/indoor) ---
    #     if opaque_fraction > 0.5:
    #         canopy_info = {
    #             "tree_fraction":   tree_fraction,
    #             "gap_fraction":    gap_fraction,
    #             "LAI":             99.0,
    #             "tau_direct":      0.0,
    #             "solar_elevation": solar_elevation_deg,
    #             "overhead_type":   "opaque_structure"
    #         }
    #         if Config.debug_mode:
    #             print(f"[CANOPY] Opaque overhead detected ({opaque_fraction:.1%}) → tau_direct=0.0")
    #         return 0.0, canopy_info

    #     # --- No significant canopy ---
    #     if tree_fraction < 0.10:
    #         return 1.0, {"tree_fraction": tree_fraction, "gap_fraction": gap_fraction, "LAI": 0.0}
        
    #     # --- Tree canopy (Beer-Lambert) ---
    #     k = 0.5
    #     gap_fraction_clamped = np.clip(gap_fraction, 0.01, 0.99)
    #     effective_LAI = -np.log(gap_fraction_clamped) / k

    #     sin_elev   = np.sin(np.radians(max(5.0, solar_elevation_deg)))
    #     tau_direct = np.exp(-k * effective_LAI / sin_elev)
    #     tau_direct = np.clip(tau_direct, 0.0, 1.0)

    #     # --- Segmentation bias correction ---
    #     # Segmentation models tend to over-detect tree coverage (narrow/sparse trees
    #     # mapped as dense canopy), leading to artificially high LAI and underestimated SW.
    #     # We apply a minimum tau floor that scales with tree fraction:
    #     #   - Moderate tree cover (10-50%): higher floor (more likely sparse/narrow trees)
    #     #   - Heavy tree cover (50-80%):    medium floor
    #     #   - Near-full cover (>80%):       low floor (likely genuinely dense)
    #     if tree_fraction < 0.50:
    #         tau_min = 0.25   # sparse/narrow trees — segmentation likely over-detecting
    #         print(site_no, " CASE 1 Happend")
    #     elif tree_fraction < 0.80:
    #         tau_min = 0.15   # moderate canopy
    #         print(site_no, " CASE 2 Happend")
    #     else:
    #         tau_min = 0.15   # genuinely dense canopy — trust Beer-Lambert more
    #         print(site_no, " CASE 3 Happend")

    #     tau_corrected = max(tau_direct, tau_min)

    #     if Config.debug_mode:
    #         print(f"[CANOPY] tree={tree_fraction:.1%}, gap={gap_fraction:.2f}, "
    #             f"LAI={effective_LAI:.2f}, tau_BeerLambert={tau_direct:.3f}, "
    #             f"tau_min={tau_min:.3f}, tau_final={tau_corrected:.3f}")

    #     canopy_info = {
    #         "tree_fraction":   tree_fraction,
    #         "gap_fraction":    gap_fraction,
    #         "LAI":             effective_LAI,
    #         "tau_direct":      tau_corrected,
    #         "tau_beer_lambert": tau_direct,    # keep raw for diagnostics
    #         "tau_min_applied": tau_corrected > tau_direct,  # flag when floor kicked in
    #         "solar_elevation": solar_elevation_deg,
    #         "overhead_type":   "tree_canopy"
    #     }

    #     return tau_corrected, canopy_info

    def compute_canopy_transmissivity(self, segmentation_data, solar_elevation_deg, folder_id):
        tree_case = 0
        top_seg = segmentation_data.get("top")
        
        if top_seg is None:
            canopy_info = {
                "tree_fraction": 0.0,
                "gap_fraction":  1.0,
                "LAI":           0.0,
                "tau_direct":    1.0,
                "solar_elevation": solar_elevation_deg,
                "overhead_type": "unknown"
            }
            return 0, 0.0, 1.0, canopy_info
        
        total_pixels      = top_seg.size
        tree_pixels       = np.sum(top_seg == 2)
        sky_pixels        = np.sum(top_seg == 1)
        building_pixels   = np.sum(top_seg == 3)
        impervious_pixels = np.sum(top_seg == 4)

        tree_fraction   = tree_pixels    / total_pixels
        opaque_fraction = (building_pixels + impervious_pixels) / total_pixels

        # --- Fix 2: gap fraction within canopy only (Miller 1967, Norman & Campbell 1989) ---
        # Using sky / (sky + tree) instead of sky / total isolates true canopy gap fraction,
        # preventing building occlusion from inflating LAI as if it were leaf area.
        canopy_pixels = sky_pixels + tree_pixels
        gap_fraction  = sky_pixels / canopy_pixels if canopy_pixels > 0 else 1.0

        # --- Fix 1: Opaque overhead (building/roof/bridge) → tau = 0.0, not 1.0 ---
        # The enclosure classifier handles fully enclosed indoor sites; this branch
        # catches partial opaque overhead (e.g., a bridge, overhang, or parking structure)
        # where the top segmentation is dominated by building/impervious pixels.
        # Transmissivity must be 0 — no direct beam penetrates concrete.
        if opaque_fraction > 0.5:
            if Config.debug_mode:
                print(f"[CANOPY] Opaque overhead detected ({opaque_fraction:.1%}) → tau_direct=0.0")
            canopy_info = {
                "tree_fraction": tree_fraction,
                "gap_fraction":  gap_fraction,
                "LAI":           99.0,
                "tau_direct":    0.0,
                "solar_elevation": solar_elevation_deg,
                "overhead_type": "opaque_structure"
            }
            return -1, tree_fraction, 0.0, canopy_info

        # --- No significant canopy ---
        if tree_fraction < 0.10:
            canopy_info = {
                "tree_fraction": tree_fraction,
                "gap_fraction":  gap_fraction,
                "LAI":           0.0,
                "tau_direct":    1.0,
                "solar_elevation": solar_elevation_deg,
                "overhead_type": "open"
            }
            return 0, tree_fraction, 1.0, canopy_info

        # --- Tree canopy (Beer-Lambert with segmentation bias correction) ---
        #
        # Segmentation over-detects tree pixels → gap_fraction underestimated →
        # raw LAI inflates unboundedly → tau_direct collapses to ~0 unrealistically.
        #
        # Correction strategy: fix the biased INPUT (cap LAI) rather than patching
        # the OUTPUT (step-wise tau floors). LAI_max scales with tree_fraction:
        #   tree_fraction=0.10 → LAI_max=1.8  (sparse street trees)
        #   tree_fraction=0.50 → LAI_max=3.0  (moderate urban canopy)
        #   tree_fraction=0.90 → LAI_max=4.2  (dense canopy)
        #
        # Reference: Nowak et al. (2001) urban tree LAI typically 1–5;
        # Phoenix open desert canopy rarely exceeds 3.5 (McPherson et al., 2005).

        k = 0.5
        gap_fraction_clamped = np.clip(gap_fraction, 0.01, 0.99)
        raw_LAI       = -np.log(gap_fraction_clamped) / k
        LAI_max       = 1.5 + 3.0 * tree_fraction
        effective_LAI = min(raw_LAI, LAI_max)

        sin_elev   = np.sin(np.radians(max(5.0, solar_elevation_deg)))
        tau_direct = np.exp(-k * effective_LAI / sin_elev)
        tau_direct = np.clip(tau_direct, 0.0, 1.0)

        # --- Smooth continuous tau floor ---
        # Replaces step-wise if/elif thresholds with a continuous exponential decay.
        # tau_min(0.10) ≈ 0.32 | tau_min(0.50) ≈ 0.18 | tau_min(0.90) ≈ 0.07
        tau_min       = 0.05 + 0.32 * np.exp(-3.0 * tree_fraction)
        tau_corrected = max(tau_direct, tau_min)

        # tree_case: diagnostic label for CSV, no physics attached
        if tree_fraction < 0.50:
            tree_case = 1
        elif tree_fraction < 0.75:
            tree_case = 2
        elif tree_fraction < 0.90:
            tree_case = 3
        elif tree_fraction < 0.97:
            tree_case = 4
        else:
            tree_case = 5

        if Config.debug_mode:
            print(f"[CANOPY] tree={tree_fraction:.1%}, gap={gap_fraction:.2f} (canopy-only), "
                f"raw_LAI={raw_LAI:.2f}, capped_LAI={effective_LAI:.2f} (max={LAI_max:.2f}), "
                f"tau_BeerLambert={tau_direct:.3f}, tau_min={tau_min:.3f}, "
                f"tau_final={tau_corrected:.3f}, floor_active={tau_corrected > tau_direct}")

        canopy_info = {
            "tree_fraction":    tree_fraction,
            "gap_fraction":     gap_fraction,
            "raw_LAI":          raw_LAI,
            "LAI":              effective_LAI,
            "LAI_max":          LAI_max,
            "tau_direct":       tau_corrected,
            "tau_beer_lambert": tau_direct,
            "tau_min":          tau_min,
            "tau_min_applied":  tau_corrected > tau_direct,
            "solar_elevation":  solar_elevation_deg,
            "overhead_type":    "tree_canopy"
        }

        return tree_case, tree_fraction, tau_corrected, canopy_info

    def compute_sail_transmissivity(self, segmentation_data, folder_id):
        """
        Compute shade sail transmissivity from segmentation.

        Unlike tree canopy (Beer-Lambert with LAI), shade sail tau is a fixed
        material property of woven HDPE fabric. Commercial shade sails typically
        transmit 20-35% of direct and diffuse solar radiation uniformly
        (Lawrence et al., 2012; ARPA-E Shade Sail spec sheets).

        Physics:
            - tau_sail_direct : fraction of direct beam passing through fabric
            - tau_sail_diffuse: same fabric blocks diffuse equally (isotropic fabric)
            - sail_fraction   : fraction of top segmentation covered by sail (class 7)
            - The sail itself heats up and emits LW — handled in compute_net_radiation

        Returns:
            sail_fraction : float   fraction of overhead pixels that are sail
            tau_sail      : float   solar transmissivity of sail material [0,1]
            sail_info     : dict    diagnostic metadata
        """
        top_seg = segmentation_data.get("top")

        if top_seg is None:
            return 0.0, 1.0, {
                "sail_fraction": 0.0, "tau_sail": 1.0, "overhead_type": "unknown"
            }

        total_pixels = top_seg.size
        sail_pixels  = np.sum(top_seg == 7)
        sail_fraction = sail_pixels / total_pixels

        if sail_fraction < 0.05:
            # No meaningful sail overhead — full transmissivity
            return sail_fraction, 1.0, {
                "sail_fraction": sail_fraction,
                "tau_sail":      1.0,
                "overhead_type": "open"
            }

        # Fixed tau for woven HDPE shade sail fabric (~30% transmissivity)
        # This is a material constant — NOT derived from gap fraction.
        # In contrast to trees, shade sails are uniform semi-opaque surfaces.
        # Effective tau scales with sail coverage: partial sail = partial attenuation.
        TAU_SAIL_MATERIAL = 0.10   # 30% transmissivity — adjust per site if known

        # Effective tau: blend of open sky (tau=1) and sail fabric (tau=TAU_MATERIAL)
        # weighted by sail_fraction. This handles partial overhead coverage gracefully.
        tau_sail = (1.0 - sail_fraction) * 1.0 + sail_fraction * TAU_SAIL_MATERIAL
        tau_sail = float(np.clip(tau_sail, 0.0, 1.0))

        sail_info = {
            "sail_fraction":    sail_fraction,
            "tau_sail":         tau_sail,
            "tau_material":     TAU_SAIL_MATERIAL,
            "overhead_type":    "shade_sail",
        }

        if Config.debug_mode:
            print(f"[SAIL] sail_frac={sail_fraction:.1%}  "
                f"tau_material={TAU_SAIL_MATERIAL:.2f}  "
                f"tau_eff={tau_sail:.3f}")

        return sail_fraction, tau_sail, sail_info
    
    def _compute_face_albedos(self, segmentation_data):
        """Mean SW albedo per cubemap face from segmentation. Sky pixels excluded."""
        if segmentation_data is None or not isinstance(segmentation_data, dict):
            return {d: 0.20 for d in ['front', 'right', 'back', 'left', 'top', 'bottom']}

        albedo_lut = np.array(
            [self.SURFACE_ALBEDO.get(i, 0.20) for i in range(8)], dtype=np.float32
        )

        face_albedos = {}
        for direction in ['front', 'right', 'back', 'left', 'top', 'bottom']:
            seg = segmentation_data.get(direction)
            if seg is None or not isinstance(seg, np.ndarray):
                face_albedos[direction] = 0.20
                continue
            safe_seg  = np.clip(seg, 0, 7).astype(np.int32)
            non_sky   = (seg != 1)
            if np.any(non_sky):
                face_albedos[direction] = float(np.mean(albedo_lut[safe_seg][non_sky]))
            else:
                face_albedos[direction] = 0.0

        return face_albedos

    

    def compute_directional_shortwave_radiation(
        self,
        direct_horizontal_radiation,
        diffuse_radiation,
        solar_elevation,
        solar_azimuth,
        sun_visible,
        sky_view_factor,
        segmentation_data=None,
        sensor_heading=270.0,
        tau_direct=1.0,
        n_reflections=3,
        face_sunlit_fractions=None,
    ):
        """
        Directional SW radiation with multi-bounce radiosity.

        Replaces empirical factors 0.5 and 1.5 with analytically derived
        view factors from Oke (1987) urban canyon geometry:
            F_ground→wall  = (1−SVF) / 4   (4 cardinal walls, symmetric canyon)
            F_wall→ground  = (1−SVF) / 2   (Oke 1987, Ch. 8)
            F_wall→3walls  = (1−SVF) / 6   each (remainder of wall hemisphere)
            F_wall→top     = (1−SVF) / 2   ← replaces empirical 0.5
        Multi-bounce loop replaces empirical 1.5 lateral boost.

        sun_visible gates only what the SENSOR POINT itself receives directly.
        Surrounding surfaces (walls, ground) are independently illuminated
        according to face_sunlit_fractions derived from the shadow map — so
        reflected SW from sunlit surroundings correctly reaches a shaded sensor.

        References: Oke (1987); Grimmond & Oke (1999); Incropera et al. (2007).
        """
        indicator = 1.0 if sun_visible else 0.0

        eta_rad  = np.radians(solar_elevation)
        sin_eta  = np.sin(eta_rad)
        cos_eta  = np.cos(eta_rad)

        # ── What the SENSOR POINT itself receives directly ────────────────────────
        # Gated by sun_visible: is the sensor point itself in shade?
        direct_calibrated       = direct_horizontal_radiation * indicator
        sunfleck_direct         = (
            direct_horizontal_radiation * tau_direct * (1.0 - indicator)
            if tau_direct < 1.0 else 0.0
        )
        effective_direct_sensor = direct_calibrated + sunfleck_direct

        # ── What the SURROUNDING ENVIRONMENT receives ─────────────────────────────
        # NOT gated by sun_visible — surrounding surfaces (walls, ground) are
        # independently illuminated. Their actual sunlit fraction is read from
        # face_sunlit_fractions (derived from the shadow map in execute()).
        # This ensures reflected SW from sunlit surroundings reaches a shaded sensor.
        # Fallback to indicator when no shadow map is provided (backward compatible).
        if sun_visible:
            # OLD behavior (symmetric model)
            effective_direct_env = direct_horizontal_radiation * indicator
        else:
            # NEW behavior (physically correct)
            effective_direct_env = direct_horizontal_radiation

        I_prime_env = effective_direct_env / sin_eta if sin_eta > 0.01 else 0.0

        def get_geo_direction(sensor_offset):
            geo_azimuth = (sensor_heading + sensor_offset) % 360
            if 315 <= geo_azimuth or geo_azimuth < 45:  return 'N'
            elif 45 <= geo_azimuth < 135:               return 'E'
            elif 135 <= geo_azimuth < 225:              return 'S'
            else:                                        return 'W'

        # ── Per-face albedos from segmentation ───────────────────────────────────
        face_albedos = self._compute_face_albedos(segmentation_data)
        rho_ground   = face_albedos.get('bottom', 0.15)

        geo_to_face = {
            get_geo_direction(0):   'front',
            get_geo_direction(90):  'right',
            get_geo_direction(180): 'back',
            get_geo_direction(270): 'left',
        }
        rho_geo = {
            geo_dir: face_albedos.get(face_name, 0.30)
            for geo_dir, face_name in geo_to_face.items()
        }

        # ── Helper: per-face sunlit fraction ─────────────────────────────────────
        # Falls back to indicator (old behaviour) when no shadow map provided.
        def get_face_sunlit(face_name):
            if sun_visible:
                # OLD behavior → everything sunlit
                return 1.0
            else:
                # NEW behavior → use shadow map
                if face_sunlit_fractions is not None:
                    return face_sunlit_fractions.get(face_name, 1.0)
                return 1.0

        # ── Diffuse lateral: same for all faces, unaffected by sun_visible ───────
        K_diffuse_lateral = diffuse_radiation * sky_view_factor

        # ── Sensor upward face ────────────────────────────────────────────────────
        # Uses sensor-point visibility (sun_visible), not environment visibility.
        K_up = effective_direct_sensor + diffuse_radiation * sky_view_factor

        # ── Primary (bounce 0): direct + diffuse on each cardinal wall face ───────
        # Each wall's sunlit fraction comes from the shadow map, NOT from sun_visible.
        cardinal_azimuths = {'N': 0, 'E': 90, 'S': 180, 'W': 270}
        K_geo = {'N': 0.0, 'E': 0.0, 'S': 0.0, 'W': 0.0}

        if I_prime_env > 0:
            for direction, phi in cardinal_azimuths.items():
                face_name = geo_to_face.get(direction)
                f_wall    = get_face_sunlit(face_name)

                delta_angle = solar_azimuth - phi
                while delta_angle >  180: delta_angle -= 360
                while delta_angle < -180: delta_angle += 360

                if abs(delta_angle) < 90:
                    cos_factor       = np.cos(np.radians(delta_angle))
                    K_geo[direction] = (f_wall * I_prime_env * cos_eta * cos_factor
                                        + K_diffuse_lateral)
                else:
                    # Back-facing wall — receives diffuse only
                    K_geo[direction] = K_diffuse_lateral
        else:
            for d in K_geo:
                K_geo[d] = K_diffuse_lateral

        # ── Seed for multi-bounce radiosity ───────────────────────────────────────
        # G_ground_b: what the ground absorbs before any inter-reflection.
        # Uses shadow-map sunlit fraction for ground face ('bottom'), not sun_visible.
        f_ground   = get_face_sunlit('bottom')
        G_ground_b = f_ground * effective_direct_env + diffuse_radiation

        # G_wall_b: per-wall absorbed irradiance before inter-reflection.
        # Consistent with K_geo primary above.
        G_wall_b = {}
        for d in ['N', 'E', 'S', 'W']:
            face_name = geo_to_face.get(d)
            f_wall    = get_face_sunlit(face_name)

            if I_prime_env > 0:
                delta_angle = solar_azimuth - cardinal_azimuths[d]
                while delta_angle >  180: delta_angle -= 360
                while delta_angle < -180: delta_angle += 360

                if abs(delta_angle) < 90:
                    cos_factor  = np.cos(np.radians(delta_angle))
                    G_wall_b[d] = (f_wall * I_prime_env * cos_eta * cos_factor
                                + K_diffuse_lateral)
                else:
                    G_wall_b[d] = K_diffuse_lateral
            else:
                G_wall_b[d] = K_diffuse_lateral

        # ── Multi-bounce SW radiosity (Oke 1987 view factors) ────────────────────
        K_down     = 0.0
        K_geo_refl = {d: 0.0 for d in ['N', 'E', 'S', 'W']}
        K_up_refl  = 0.0

        for _b in range(n_reflections):
            J_ground    = rho_ground * G_ground_b
            J_wall      = {d: rho_geo[d] * G_wall_b[d] for d in ['N', 'E', 'S', 'W']}
            J_wall_mean = float(np.mean(list(J_wall.values())))

            # Accumulate at sensor position using Oke (1987) view factors
            K_down += J_ground
            for d in ['N', 'E', 'S', 'W']:
                K_geo_refl[d] += J_wall[d]
            # F_{wall→top sensor} = (1−SVF)/2  ← analytically derived
            K_up_refl += J_wall_mean * (1.0 - sky_view_factor) / 2.0

            # Next-bounce incident irradiance
            # F_{walls→ground} = (1−SVF)/2 per wall × 4 walls
            G_ground_next = sum(J_wall.values()) * (1.0 - sky_view_factor) / 2.0

            G_wall_next = {}
            for d in ['N', 'E', 'S', 'W']:
                from_ground = J_ground * (1.0 - sky_view_factor) / 4.0
                from_walls  = (
                    sum(J_wall[d2] for d2 in ['N', 'E', 'S', 'W'] if d2 != d)
                    * (1.0 - sky_view_factor) / 6.0
                )
                G_wall_next[d] = from_ground + from_walls

            G_ground_b = G_ground_next
            G_wall_b   = G_wall_next

        # ── Assemble final directional values ─────────────────────────────────────
        K_up += K_up_refl
        for d in ['N', 'E', 'S', 'W']:
            K_geo[d] += K_geo_refl[d]

        K_front = K_geo[get_geo_direction(0)]
        K_right = K_geo[get_geo_direction(90)]
        K_back  = K_geo[get_geo_direction(180)]
        K_left  = K_geo[get_geo_direction(270)]

        directional_shortwave = {
            'north': K_geo['N'], 'east':  K_geo['E'],
            'south': K_geo['S'], 'west':  K_geo['W'],
            'up':    K_up,       'down':  K_down,
            'front': K_front,    'right': K_right,
            'back':  K_back,     'left':  K_left,
        }
        directional_sw_CR3 = [K_left, K_right, K_front, K_back, K_up, K_down]

        if Config.debug_mode:
            print(f"[SW_DEBUG] Sensor heading: {sensor_heading}° (Front→{get_geo_direction(0)})")
            print(f"[SW_DEBUG] sun_visible={sun_visible}  "
                f"f_ground={f_ground:.2f}  "
                f"face_sunlit_fractions={face_sunlit_fractions}")
            print(f"[SW_DEBUG] rho_ground={rho_ground:.3f}  n_reflections={n_reflections}")
            print(f"[SW_DEBUG] effective_direct_sensor={effective_direct_sensor:.1f}  "
                f"effective_direct_env={effective_direct_env:.1f}")
            print(f"[SW_DEBUG] K_up={K_up:.1f}  K_down={K_down:.1f}")
            print(f"[SW_DEBUG] Geo SW: N={K_geo['N']:.1f} E={K_geo['E']:.1f} "
                f"S={K_geo['S']:.1f} W={K_geo['W']:.1f}")

        return directional_shortwave, directional_sw_CR3


    def compute_enclosed_longwave_maps(
        self,
        segmentation_data:        dict,
        surface_temperature_data: dict,
        L_atm:                    float,
        air_temperature:          float,
        enclosure_info:           dict,
        t:                        int,
        lw_temp_adjustment:       float = 0.0,
    ) -> tuple[dict, float]:
        """
        Compute per-pixel enclosure-aware LW radiosity maps for each direction.

        For fully enclosed sites:
            J_j = ε_j · σ · T_j⁴  +  (1 − ε_j) · G_ambient
            G_ambient = (1 − α) · L_atm  +  α · J_mean

        surface_temperature_data=None forces J_mean to use fixed air-temp offsets,
        breaking the feedback loop that causes collapse in fully enclosed sites.
        """
        enc_fraction = enclosure_info["enclosure_fraction"]

        # In compute_enclosed_longwave_maps():
        J_mean, surface_radiosity = self.compute_enclosure_mean_radiosity(
            segmentation_data, air_temperature, t,
            lw_temp_adjustment=lw_temp_adjustment,
            surface_temperature_data=surface_temperature_data,
            L_atm=L_atm,
            enclosure_fraction=enc_fraction
        )

        G_ambient = (1.0 - enc_fraction) * L_atm + enc_fraction * J_mean

        if Config.debug_mode:
            print(f"[ENC_LW_MAPS] α={enc_fraction:.2f}  L_atm={L_atm:.1f}  "
                f"J_mean={J_mean:.1f}  G_ambient={G_ambient:.1f}  W/m²")

        lw_maps = {}

        for direction, (emission_map, emissivity_map) in surface_radiosity.items():
            seg = segmentation_data[direction]
            lw  = np.zeros((512, 512), dtype=np.float32)

            # Sky pixels → true atmospheric LW (they ARE the sky)
            sky_mask = (seg == 1)
            lw[sky_mask] = L_atm

            # Surface pixels → enclosure-aware radiosity
            surf_mask = ~sky_mask
            if np.any(surf_mask):
                # J = ε·σ·T⁴ + (1−ε)·G_ambient   (Incropera Eq. 12.1)
                lw[surf_mask] = (
                    emission_map[surf_mask]
                    + (1.0 - emissivity_map[surf_mask]) * G_ambient
                )

            lw_maps[direction] = lw

            if Config.debug_mode:
                surf_lw = lw[surf_mask]
                if surf_lw.size > 0:
                    print(f"[ENC_LW_MAPS] {direction:6s}  "
                        f"mean={surf_lw.mean():.1f}  "
                        f"min={surf_lw.min():.1f}  "
                        f"max={surf_lw.max():.1f}  W/m²")

        return lw_maps, J_mean

    # Standard Direction Order
    DIRECTIONS = ["front", "right", "back", "left", "top", "bottom"]

    def process_direction(self, d, t, Q0, Q1, surface_temperature_data,
                        segmentation_data, shadow_data, E, Qg, tlayer,
                        thickness, air_temperature, wind_velocity,
                        relative_humidity, 
                        incoming_radiation, diffuse_radiation,
                        L_atm, G_ambient,
                        minute_delta, n_pixels, site_no, location,
                        tau_direct=1.0, gap_fraction=1.0,
                        tau_sail=1.0):

        new_q = Q1[d] if t % 2 == 0 else Q0[d]

        # ── Fix 1: use initialized surface temps at t=0, not just T_air ──────────
        # surface_temperature_data[d][0] was initialized with surface-type offsets
        # (e.g. asphalt = T_air+8). Using plain T_air here gave a first-timestep
        # q_net spike that stored an unrealistically hot T_s[0].
        if t == 0:
            prev_surface_temp = surface_temperature_data[d][0].copy()
        else:
            prev_surface_temp = surface_temperature_data[d][t - 1].copy()
        prev_surface_temp[segmentation_data[d] == 1] = np.nan

        E_d = self.compute_lw_radiosity(
            n_pixels, G_ambient, L_atm,
            prev_surface_temp, segmentation_data[d], air_temperature
        )

        # ── Per-surface SW absorption map (1 − albedo) ────────────────────────────
        # Decouples surface SW absorption from human body absorptivity (C_BODY_ABSORPTION).
        # Values match SURFACE_ALBEDO: sky=0 (not a surface), tree=0.70, wall=0.65,
        # asphalt=0.85, soil=0.70, cars=0.80, sail=0.80.
        # Reference: Oke (1987) Table 1.2; Sailor (2002).
        sw_abs_lut = np.array(
            [0.00, 0.00, 0.70, 0.65, 0.85, 0.70, 0.80, 0.80],
            dtype=np.float32
        )
        safe_seg   = np.clip(segmentation_data[d], 0, 7).astype(np.int32)
        sw_abs_map = sw_abs_lut[safe_seg]                                  # shape (512,512)

        new_q[:] = self.compute_net_radiation(
            incoming_radiation, diffuse_radiation,
            G_ambient, L_atm,
            shadow_data[d][t], E_d,
            tau_direct=tau_direct, gap_fraction=gap_fraction,
            air_temperature=air_temperature,
            tau_sail=tau_sail,
            sw_absorption_map=sw_abs_map,                                  # ← PASS IT
        ).flatten()

        # print("\n------------> Minute Delta: ", minute_delta)

        Qg_d = self.compute_surface_conduction(
            n_pixels, segmentation_data[d], Qg[d], tlayer[d],
            thickness, prev_surface_temp, minute_delta * 60
        )
        
        surface_temp = self.compute_surface_temperature_physical(
            q_net_radiation=new_q.reshape((512, 512)),
            Qg=Qg_d,
            air_temperature=air_temperature,
            wind_velocity=wind_velocity,
            relative_humidity=relative_humidity / 100.0,
            segmentation_data=segmentation_data[d],
        )
        surface_temp = self.apply_physical_bounds(
            surface_temp, segmentation_data[d],
            air_temperature, incoming_radiation, wind_velocity
        )

        # # ── Fix 2: asymmetric smoothing applied at ALL t (not just t>0) ──────────
        # sky_mask  = (segmentation_data[d] == 1)
        # prev_safe = np.where(np.isnan(prev_surface_temp), surface_temp, prev_surface_temp)

        # if t < 3:
        #     # Warm-up window: heat quickly, cool slowly to prevent initial spike
        #     # and let surfaces reach a physically plausible starting temperature.
        #     alpha = np.where(surface_temp > prev_safe, 0.40, 0.15)
        # else:
        #     # Normal operation: symmetric smoothing, same α for heating and cooling.
        #     # Damps LW oscillation without biasing the thermal trajectory.
        #     alpha = 0.40

        # surface_temp = alpha * surface_temp + (1.0 - alpha) * prev_safe
        # surface_temp[sky_mask] = np.nan

        # # ── Tree override: no thermal mass, no conduction, always T_air ──────────
        # # Trees exchange heat with the air rapidly via transpiration and convection.
        # # We do not model leaf-level energy balance; instead we fix T_tree = T_air.
        # # Their LW emission (ε·σ·T⁴) and MRT contribution remain physically correct
        # # because compute_lw_radiosity and compute_enclosure_mean_radiosity read
        # # surface_temperature_data, which now holds T_air for tree pixels.
        # tree_mask = (segmentation_data[d] == 2)
        # surface_temp[tree_mask] = air_temperature
        # Qg_d[tree_mask] = 0.0

        # # ── Sail override: fix at elevated temperature (NEW) ──────────────────
        # # Shade sails are thin fabric with negligible thermal mass — no meaningful
        # # conduction storage. We skip the energy balance solver for sail pixels and
        # # assign a fixed temperature based on solar loading.
        # # When sun is up: T_sail = T_air + T_sail_offset (hot fabric in direct sun)
        # # The LW emission from sails is read from surface_temperature_data in
        # # compute_enclosure_mean_radiosity, so getting T_sail right here matters.
        # sail_mask = (segmentation_data[d] == 7)
        # if np.any(sail_mask):
        #     # If this direction is "top" (looking up at the sail), it's in full sun.
        #     # For lateral directions, the sail is seen edge-on — use a moderate temp.
        #     sail_delta = self.SURFACE_TEMP_OFFSET[7] if d == "top" else 2.0
        #     surface_temp[sail_mask] = air_temperature + sail_delta

        # # ── Grass/pervious override: bypass conduction solver ─────────────────────
        # # Irrigated turf and pervious soil cannot accumulate thermal mass the way
        # # asphalt does — evapotranspiration removes energy as latent heat continuously.
        # # Running the Crank-Nicholson solver on class 5 produces spurious heat buildup
        # # in tlayer that inflates T_s and LW emission.
        # #
        # # Fix: pin T_s to a small fixed offset from T_air, analogous to the tree override.
        # # T_grass = T_air - 1.0°C  (irrigated turf, evaporative cooling)
        # # This is conservative — measured irrigated turf in Phoenix is often T_air−2 to T_air+1.
        # #
        # # Reference: Oke (1987) Ch.2; Qin et al. (2001) urban grass surface energy balance.
        # # Grimmond & Oke (1999): latent heat flux dominates energy balance for irrigated surfaces.
        # grass_mask = (segmentation_data[d] == 5)
        # if np.any(grass_mask):
        #     surface_temp[grass_mask] = air_temperature - 1.0
        
        # Qg_d[grass_mask] = 0.0   # no conductive storage for evaporating surfaces

        # ── Physics-based temporal relaxation ─────────────────────────────────
        # τ = ρ·c·z / h_eff where z is the diurnal thermal penetration depth
        # References: Oke (1987) Table 2.1; Campbell & Norman (1998)
        #
        # Class:  sky  sky  tree  wall   asph  soil  cars  sail
        # τ [s]:   0    0   800  5400  4800  2400  3000   300
        #
        # At Δt=30min (1800s):
        #   asphalt: α = 1-exp(-1800/4800) ≈ 0.31  (69% memory)
        #   wall:    α = 1-exp(-1800/5400) ≈ 0.28  (72% memory)
        #   sail:    α = 1-exp(-1800/300)  ≈ 0.998 (nearly instant)
        
        # # if tree has heat storage:
        # tau_lut  = np.array([0, 0, 800, 5400, 4800, 2400, 3000, 300], dtype=np.float32)

        # for trees non heat storage:
        # Change tau_lut[2] from 800 → 1 so α≈1 instantly (belt-and-suspenders)
        tau_lut = np.array([0, 0, 1, 5400, 4800, 2400, 3000, 300], dtype=np.float32)

        safe_seg = np.clip(segmentation_data[d], 0, 7).astype(np.int32)
        tau      = tau_lut[safe_seg]
        delta_t  = minute_delta * 60.0
        alpha    = 1.0 - np.exp(-delta_t / np.maximum(tau, 1.0))
        prev_safe    = np.where(np.isnan(prev_surface_temp), surface_temp, prev_surface_temp)
        surface_temp = alpha * surface_temp + (1.0 - alpha) * prev_safe

        surface_temp[segmentation_data[d] == 1] = np.nan   # sky always NaN

        # ── Tree override: no thermal mass, Ts = T_air always ────────────────────
        tree_mask = (segmentation_data[d] == 2)
        if np.any(tree_mask):
            surface_temp[tree_mask] = air_temperature
            Qg_d[tree_mask] = 0.0
            tree_flat = tree_mask.flatten()
            tlayer[d][tree_flat, :] = air_temperature + 273.15

        # Validation Thermal Images
        image_params = (
            surface_temp.copy(),
            segmentation_data[d].copy(),
            location, d, t, site_no, air_temperature,
            T_GLOBAL_MIN, T_GLOBAL_MAX,   # ← add these two
            True,                          # save_npy=True
        )
        return d, E_d, Qg_d, surface_temp, image_params

    
    # OPTIMIZED: Batch image processing
    def _image_worker(self):
        """Worker thread for processing images"""
        while True:
            item = self.image_queue.get()
            if item is None:  # Stop signal
                break
            try:
                self.create_temperature_validation_image(*item)
            except Exception as e:
                print(f"[ERROR] Image creation failed: {e}")
            self.image_queue.task_done()

    def detect_overhead_coverage(self, segmentation_data, sky_view_factor):
        """
        Detect if site has significant overhead coverage (canopy, shade structure).
        
        Returns:
            coverage_factor: 0.0 (open) to 1.0 (fully covered)
        """
        top_seg = segmentation_data.get("top")
        
        if top_seg is None:
            return 0.0
        
        # Calculate what percentage is NOT sky looking up
        non_sky_pixels = np.sum(top_seg != 1)
        total_pixels = top_seg.size
        overhead_coverage = non_sky_pixels / total_pixels
        
        # Validate against SVF
        # Low SVF + high overhead non-sky = covered structure
        if sky_view_factor < 0.15 and overhead_coverage > 0.7:
            if Config.debug_mode:
                print(f"[COVERAGE] Detected overhead structure: SVF={sky_view_factor:.3f}, "
                    f"Overhead coverage={overhead_coverage:.1%}")
            return overhead_coverage
        
        return 0.0

    def classify_site_enclosure(self, segmentation_data: dict, sky_view_factor: float) -> dict:
        """
        Classify the radiative enclosure level of a site from segmentation data.

        Rules:
        - Fully enclosed → top building fraction > 0.9
        - Semi-enclosed → 0.15 < SVF ≤ 0.60
        - Open → SVF > 0.60
        """

        sky_fracs      = {}
        building_fracs = {}
        ground_fracs   = {}
        tree_fracs = {}

        for direction, seg in segmentation_data.items():
            if not isinstance(seg, np.ndarray):
                continue
            n = seg.size
            sky_fracs[direction]      = np.sum(seg == 1) / n
            building_fracs[direction] = np.sum(seg == 3) / n
            ground_fracs[direction]   = np.sum(seg == 4) / n
            tree_fracs[direction]     = np.sum(seg == 2) / n

        # --- Use hemisphere only (exclude bottom) ---
        hemisphere_dirs = ["top", "front", "right", "back", "left"]
        mean_sky_frac = np.mean([sky_fracs.get(d, 0.5) for d in hemisphere_dirs])
        mean_tree_frac = np.mean([tree_fracs.get(d, 0.0) for d in hemisphere_dirs])
        enclosure_frac = 1.0 - mean_sky_frac

        top_sky_frac        = sky_fracs.get("top", 0.5)
        top_building_frac   = building_fracs.get("top", 0.0)
        lateral_sky_frac    = np.mean([sky_fracs.get(d, 0.5)
                                    for d in ["front", "right", "back", "left"]])
        lateral_tree_frac = np.mean([
            tree_fracs.get(d, 0.0)
            for d in ["front", "right", "back", "left"]
        ])
        tree_enclosure_score = 0.7 * tree_fracs.get("top", 0.0) + 0.3 * lateral_tree_frac
        print("-------------> tree_enclosure_score: ", tree_enclosure_score)

        # Sail fraction on top face only — sails are semi-transparent and should
        # not drive the enclosure classifier into semi_enclosed, because their LW
        # physics are handled separately via compute_sail_transmissivity.
        top_sail_frac = (
            np.sum(segmentation_data["top"] == 7) / segmentation_data["top"].size
            if isinstance(segmentation_data.get("top"), np.ndarray)
            else 0.0
        )

        # --- Classification ---
        if tree_enclosure_score > 0.75 and sky_view_factor < 0.20 and top_building_frac < 0.3:
            enc_type = "fully_enclosed_tree"
            print("************ FULLY ENCLOSED TREE (Top + lateral canopy)")
            
        elif top_building_frac > 0.90 and sky_view_factor < 0.09:
            enc_type = "fully_enclosed"
            print("************ FULLY ENCLOSED (Top building > 90%)")

        elif sky_view_factor <= 0.35 and sky_view_factor >= 0.09 and top_sail_frac <= 0.30:
            enc_type = "semi_enclosed"
            print("************ SEMI-ENCLOSED")

        else:
            enc_type = "open"
            print("************ OPEN SITE")

        if Config.debug_mode:
            print(
                f"[ENCLOSURE] Type={enc_type}, "
                f"SVF={sky_view_factor:.3f}, "
                f"enc_frac={enclosure_frac:.2f}, "
                f"top_sky={top_sky_frac:.2f}, "
                f"top_building={top_building_frac:.2f}, "
                f"lateral_sky={lateral_sky_frac:.2f}"
            )

        return {
            "type":                      enc_type,
            "enclosure_fraction":        enclosure_frac,
            "sky_fraction_by_direction": sky_fracs,
            "building_fraction_by_dir":  building_fracs,
            "top_sky_fraction":          top_sky_frac,
            "top_building_fraction":     top_building_frac,
            "lateral_sky_fraction":      lateral_sky_frac,
        }


    # def compute_enclosure_mean_radiosity(
    #     self,
    #     segmentation_data: dict,
    #     air_temperature:   float,
    #     t:                 int,
    #     lw_temp_adjustment:    float = 0.0,
    #     surface_temperature_data: dict = None,   # ← NEW
    # ) -> tuple[float, dict]:
    #     """
    #     Compute the mean enclosure radiosity J_mean for a diffuse gray enclosure.

    #     ── Physics ─────────────────────────────────────────────────────────────────
    #     For a diffuse gray enclosure with N surfaces, the mean radiosity seen by
    #     any interior point is the view-factor-weighted sum of each surface's actual
    #     longwave emission (Modest, 2013; Incropera et al., 2007):

    #         J_mean = Σ_j ( F_j · ε_j · σ · T_j⁴ )          [W/m²]

    #     where F_j is the view factor from the point of interest to surface j,
    #     approximated here as the geometric area fraction:

    #         F_j = N_j / N_total_nonsky

    #     N_j            — number of pixels of surface type j in direction d
    #     N_total_nonsky — total non-sky pixels across all directions

    #     Under the Lambertian (diffuse) assumption with a roughly symmetric
    #     enclosure geometry, this uniform view factor approximation is standard
    #     (Walton, 1983; Scott Krayenhoff, pers. comm. 2026).

    #     Note: emissivity is NOT used as an additional weighting factor in the
    #     denominator. It is already embedded inside the emission term ε·σ·T⁴,
    #     which gives the actual (non-blackbody) longwave emitted by the surface.
    #     Weighting again by ε in the denominator would incorrectly double-penalize
    #     low-emissivity surfaces (Scott Krayenhoff, pers. comm. 2026).

    #     Per-surface radiosity (emission + reflection of enclosure ambient) is
    #     computed in compute_enclosed_longwave_maps using:

    #         J_j = ε_j · σ · T_j⁴  +  (1 − ε_j) · G_ambient

    #     where G_ambient blends J_mean with open-sky atmospheric radiation:

    #         G_ambient = (1 − α) · L_atm  +  α · J_mean
    #         α = enclosure_fraction ∈ [0, 1]

    #     ── Temperature Strategy ────────────────────────────────────────────────────
    #     Surface temperatures are derived as  T = T_air + Δ_enclosed,  where Δ is a
    #     small enclosure-specific offset (see offset_array below).

    #     We intentionally do NOT use surface_temperature_data from process_direction
    #     here. That solver computes surface temps using open-sky atmospheric_radiation
    #     (~390 W/m²) as downwelling LW, but this enclosed site has ~470+ W/m² actual
    #     LW from surrounding walls. The resulting ~80 W/m² energy deficit causes
    #     process_direction surfaces to compute as unrealistically cold (e.g. 14°C in
    #     a 30°C tunnel), which then drives J_mean to collapse or overshoot through
    #     the feedback loop. Using air_temperature + small offset gives stable,
    #     physically meaningful J_mean values every timestep.

    #     ── Offset Values ───────────────────────────────────────────────────────────
    #     Offsets are calibrated for ENCLOSED, NO-SOLAR-INPUT environments:
    #       Sky       (1): not used — handled as atmospheric_radiation
    #       Tree      (2): −2°C  (slight evapotranspiration cooling)
    #       Building  (3): −2°C  (shaded wall, near air temp)
    #       Asphalt   (4): −2°C  (thermal mass, no solar → near air temp)
    #       Soil      (5): −1°C  (moist soil, slight cooling)
    #       Moving    (6): −1°C  (metal surfaces, slight cooling)

    #     Compare to outdoor offsets [0, -3, +2, +8, +1, +4] which assume direct
    #     solar heating. Asphalt drops from +8 → −2 because there is no solar input
    #     in a fully enclosed site.

    #     ── Sanity Check ────────────────────────────────────────────────────────────
    #     Because F_j = N_j / N_total_nonsky, the sum Σ F_j = 1.0 exactly for a
    #     closed enclosure. The debug output prints F_total so this can be verified.

    #     ── Physical Bounds ─────────────────────────────────────────────────────────
    #     J_mean is clamped to the blackbody emission range:
    #       Lower bound: σ · (T_air − 15)⁴   (cool night / overnight tunnel floor)
    #       Upper bound: σ · (T_air + 15)⁴   (hottest shaded enclosed surface)

    #     Parameters
    #     ----------
    #     segmentation_data  : dict  { direction: np.ndarray(512,512) }
    #     air_temperature    : float  [°C]
    #     t                  : int    current timestep index (unused, kept for API consistency)
    #     lw_temp_adjustment : float  [°C] time-varying thermal mass correction

    #     Returns
    #     -------
    #     J_mean            : float   mean enclosure radiosity [W/m²]
    #     surface_radiosity : dict    { direction: (emission_map, emissivity_map) }
    #                         emission_map  — per-pixel ε·σ·T⁴  [W/m²]
    #                         emissivity_map — per-pixel ε        [dimensionless]

    #     References
    #     ----------
    #     Modest, M. F. (2013). Radiative Heat Transfer (3rd ed.). Academic Press.
    #     Incropera et al. (2007). Fundamentals of Heat and Mass Transfer (6th ed.).
    #     Walton, G. N. (1983). Thermal Analysis Research Program Reference Manual. NBSIR.
    #     Krayenhoff, S. (2026). Personal communication, March 13.
    #     """
    #     # Enclosure-specific temperature offsets from air temperature (°C)
    #     # Index corresponds to segmentation class 0–7
    #     offset_array = np.array([0, 0, 0, -2, -2, -1, -1, -1], dtype=np.float32)

    #     # ── Step 1: count total non-sky pixels across ALL directions ────────────
    #     # This is the denominator for view factor normalization.
    #     # F_j = (pixels of surface type j in direction d) / (total non-sky pixels)
    #     # Σ F_j = 1.0 exactly for a closed enclosure — use as sanity check.
    #     total_nonsky_pixels = sum(
    #         np.sum(seg != 1)
    #         for seg in segmentation_data.values()
    #         if isinstance(seg, np.ndarray)
    #     ) or 1  # safety fallback if somehow all pixels are sky

    #     # ── Step 2: accumulate view-factor-weighted emission ─────────────────────
    #     total_weighted_emission = 0.0
    #     total_view_factor       = 0.0   # should converge to ~1.0 for closed enclosure
    #     surface_radiosity       = {}

    #     for direction, seg in segmentation_data.items():
    #         if not isinstance(seg, np.ndarray):
    #             continue

    #         emission_map   = np.zeros((512, 512), dtype=np.float32)
    #         emissivity_map = np.zeros((512, 512), dtype=np.float32)

    #         # Get actual surface temperatures if available (t > 0 only)
    #         # At t=0 there are no previous temps — fall back to fixed offsets
    #         use_actual_temps = (
    #             surface_temperature_data is not None
    #             and t > 0
    #             and direction in surface_temperature_data
    #             and surface_temperature_data[direction][t - 1] is not None
    #         )
    #         prev_temp_map = surface_temperature_data[direction][t - 1] if use_actual_temps else None

    #         for seg_type, emissivity in self.SURFACE_EMISSIVITY.items():
    #             if seg_type == 1:
    #                 continue
    #             mask = (seg == seg_type)
    #             if not np.any(mask):
    #                 continue

    #             emissivity_map[mask] = emissivity

    #             if use_actual_temps and prev_temp_map is not None:
    #                 # Use actual per-pixel surface temperatures from previous timestep.
    #                 # These include solar heating, thermal mass, and tree shadow effects
    #                 # accumulated through process_direction's energy balance solver.
    #                 pixel_temps_C = prev_temp_map[mask]
    #                 fallback_T_C  = air_temperature + float(offset_array[seg_type]) + lw_temp_adjustment
    #                 pixel_temps_K = np.where(
    #                     np.isnan(pixel_temps_C),
    #                     fallback_T_C + 273.15,
    #                     pixel_temps_C + 273.15
    #                 )
    #             else:
    #                 # t=0 fallback: use fixed enclosure offsets
    #                 T_C = air_temperature + float(offset_array[seg_type]) + lw_temp_adjustment
    #                 pixel_temps_K = np.full(int(np.sum(mask)), T_C + 273.15, dtype=np.float32)

    #             pixel_emissions   = emissivity * self.C_STEFAN_BOLTZMANN * pixel_temps_K ** 4
    #             emission_map[mask] = pixel_emissions

    #             F_j = np.sum(mask) / total_nonsky_pixels
    #             total_weighted_emission += F_j * float(np.mean(pixel_emissions))
    #             total_view_factor       += F_j

    #         surface_radiosity[direction] = (emission_map, emissivity_map)

    #     # ── Step 3: J_mean = view-factor-weighted mean emission ──────────────────
    #     if total_view_factor > 0:
    #         J_mean = total_weighted_emission / total_view_factor
    #     else:
    #         # Fallback: blackbody emission at air temperature
    #         J_mean = self.C_STEFAN_BOLTZMANN * (air_temperature + 273.15) ** 4

    #     # ── Physical bounds clamp ────────────────────────────────────────────────
    #     J_max = self.C_STEFAN_BOLTZMANN * (air_temperature + 15.0 + 273.15) ** 4
    #     J_min = self.C_STEFAN_BOLTZMANN * (air_temperature - 15.0 + 273.15) ** 4
    #     J_mean = float(np.clip(J_mean, J_min, J_max))

    #     if Config.debug_mode:
    #         T_equiv = (J_mean / self.C_STEFAN_BOLTZMANN) ** 0.25 - 273.15
    #         print(f"[ENCLOSURE_LW] J_mean={J_mean:.1f} W/m²  "
    #               f"(equiv blackbody T={T_equiv:.1f}°C)  "
    #               f"F_total={total_view_factor:.4f} (expect ~1.0)")

    #     return J_mean, surface_radiosity

    def compute_enclosure_mean_radiosity(self, segmentation_data, air_temperature,
                                        t, lw_temp_adjustment=0.0,
                                        surface_temperature_data=None,
                                        L_atm=390.0,
                                        enclosure_fraction=0.0,
                                        under_relaxation=0.6, tolerance=1.0,
                                        max_iter=30):
        """
        Gauss-Seidel radiosity solver for diffuse gray enclosure.
        
        Full radiosity: J_j = ε_j·σ·T_j⁴ + (1−ε_j)·G_ambient
        G_ambient = (1−α)·L_atm + α·J_mean
        J_mean = Σ_j F_j · J_j  (F_j = area fraction)
        
        Iterate until |J_mean_new − J_mean_old| < tolerance [W/m²]
        Under-relaxation (ω=0.6) prevents oscillation.
        
        References: Modest (2013) Ch. 5; Incropera et al. (2007) Ch. 13.
        """
        offset_array = np.array([0, 0, 0, -2, -2, -1, -1, -1], dtype=np.float32)

        # # NOT USED FOR CUBE VIEW-BASED APPROACH
        # total_nonsky_pixels = sum(
        #     np.sum(seg != 1)
        #     for seg in segmentation_data.values()
        #     if isinstance(seg, np.ndarray)
        # ) or 1

        # Build emission and emissivity maps once (they don't change during iteration)
        emission_maps = {}
        emissivity_maps = {}
        surface_radiosity = {}

        for direction, seg in segmentation_data.items():
            if not isinstance(seg, np.ndarray):
                continue
            em_map  = np.zeros((512, 512), dtype=np.float32)
            eps_map = np.zeros((512, 512), dtype=np.float32)

            use_actual = (
                surface_temperature_data is not None and t > 0
                and direction in surface_temperature_data
                and surface_temperature_data[direction][t - 1] is not None
            )
            prev_T = surface_temperature_data[direction][t - 1] if use_actual else None

            for seg_type, emissivity in self.SURFACE_EMISSIVITY.items():
                if seg_type == 1:
                    continue
                mask = (seg == seg_type)
                if not np.any(mask):
                    continue
                eps_map[mask] = emissivity

                if use_actual and prev_T is not None:
                    T_K = np.where(
                        np.isnan(prev_T[mask]),
                        air_temperature + float(offset_array[seg_type]) + lw_temp_adjustment + 273.15,
                        prev_T[mask] + 273.15
                    )
                else:
                    T_K = air_temperature + float(offset_array[seg_type]) + lw_temp_adjustment + 273.15

                em_map[mask] = emissivity * self.C_STEFAN_BOLTZMANN * T_K ** 4

            emission_maps[direction]  = em_map
            emissivity_maps[direction] = eps_map

        # ── Gauss-Seidel iteration ────────────────────────────────────────────
        # Seed: blackbody at air temperature
        J_mean = self.C_STEFAN_BOLTZMANN * (air_temperature + 273.15) ** 4
        alpha  = enclosure_fraction  # passed in or computed outside

        for iteration in range(max_iter):
            G_ambient = (1.0 - alpha) * L_atm + alpha * J_mean

            # J_mean_new = Σ_j F_j · [ε_j·σ·T_j⁴ + (1−ε_j)·G_ambient]
            total_J = 0.0
            total_F = 0.0
            for direction, em_map in emission_maps.items():
                seg     = segmentation_data[direction]
                eps_map = emissivity_maps[direction]
                # Full radiosity per pixel (Incropera Eq. 12.1)
                J_map   = em_map + (1.0 - eps_map) * G_ambient
                non_sky = (seg != 1)
                if not np.any(non_sky):
                    continue
                # NEW — pixel-to-sensor view factors
                vf      = self.vf_map[direction]          # precomputed (512,512)
                weights = vf * non_sky                    # zero out sky pixels
                w_sum   = float(np.sum(weights))
                
                # $ Dead Code but good to know there's a mult and divide
                # if w_sum > 0:
                #     total_J += float(np.sum(J_map * weights)) / w_sum * w_sum
                #     total_F += w_sum

                # Better here:
                if w_sum > 0:
                    total_J += float(np.sum(J_map * weights))    # weighted radiosity sum for this face
                    total_F += w_sum                             # total view factor weight for normalization

            J_mean_new = total_J / total_F if total_F > 0 else J_mean

            # Under-relaxation: J_mean ← ω·J_new + (1−ω)·J_old
            J_mean_relaxed = under_relaxation * J_mean_new + (1.0 - under_relaxation) * J_mean

            delta = abs(J_mean_relaxed - J_mean)
            J_mean = J_mean_relaxed

            if delta < tolerance:
                break

        # Build final per-pixel radiosity maps
        G_ambient_final = (1.0 - alpha) * L_atm + alpha * J_mean
        for direction in emission_maps:
            em_map  = emission_maps[direction]
            eps_map = emissivity_maps[direction]
            surface_radiosity[direction] = (em_map, eps_map)

        J_max = self.C_STEFAN_BOLTZMANN * (air_temperature + 15.0 + 273.15) ** 4
        J_min = self.C_STEFAN_BOLTZMANN * (air_temperature - 15.0 + 273.15) ** 4
        J_mean = float(np.clip(J_mean, J_min, J_max))

        return J_mean, surface_radiosity
    

    # def _save_colorbar_image(self, folder_id: str, t_min: float, t_max: float,
    #                         bar_height: int = 1000, bar_width: int = 130):
    #     import matplotlib.cm as _cm
    #     from PIL import ImageDraw, ImageFont

    #     _lut_f = _cm.inferno(np.linspace(0, 1, 256))[:, :3]
    #     lut = (_lut_f * 255).astype(np.uint8)

    #     bar = np.zeros((bar_height, bar_width, 3), dtype=np.uint8)
    #     for row in range(bar_height):
    #         idx = int((1.0 - row / (bar_height - 1)) * 255)
    #         bar[row] = lut[idx]

    #     img  = Image.fromarray(bar)
    #     draw = ImageDraw.Draw(img)

    #     # ── Fonts: big number ───────────────────────────────────
    #     FONT_SIZE = 85
    #     font_num  = None
    #     for font_path in [
    #         "/usr/share/fonts/truetype/dejavu/DejaVuSans-Bold.ttf",  # Linux bold (thicker)
    #         "/usr/share/fonts/truetype/dejavu/DejaVuSans.ttf",
    #         "/System/Library/Fonts/Helvetica.ttc",
    #         "C:/Windows/Fonts/arialbd.ttf",                           # Windows bold
    #         "C:/Windows/Fonts/arial.ttf",
    #     ]:
    #         if os.path.exists(font_path):
    #             font_num = ImageFont.truetype(font_path, FONT_SIZE)
    #             break
    #     if font_num is None:
    #         font_num = ImageFont.load_default()

    #     # ── Labels ────────────────────────────────────────────────────────────
    #     WHITE     = (255, 255, 255)
    #     DARK_RED  = (180, 40, 40)
    #     n_labels  = 3

    #     for i in range(n_labels):
    #         frac   = i / (n_labels - 1)
    #         temp_c = t_max - frac * (t_max - t_min)
    #         y_px   = int(frac * (bar_height - 1))

    #         number = f"{temp_c:.0f}"
    #         bbox   = draw.textbbox((0, 0), number, font=font_num)
    #         num_w  = bbox[2] - bbox[0]
    #         num_h  = bbox[3] - bbox[1]

    #         # Center horizontally in the bar
    #         text_x = (bar_width - num_w) // 2

    #         if i == 0:
    #             label_y = y_px + 5
    #         elif i == n_labels - 1:
    #             label_y = bar_height - num_h - 40
    #         else:
    #             label_y = y_px - num_h // 2

    #         # Last label (coldest) → dark red, all others → white
    #         color = DARK_RED if i == 0 else WHITE
    #         draw.text((text_x, label_y), number, fill=color, font=font_num)
    #         num_h  = bbox[3] - bbox[1]


    #     out_dir  = f"./output/{folder_id}/validation_thermal_images"
    #     os.makedirs(out_dir, exist_ok=True)
    #     out_path = f"{out_dir}/thermal_colorbar_legend.png"
    #     img.save(out_path)
    #     print(f"[COLORBAR] Saved legend → {out_path}")
    
    def _save_colorbar_image(
        self,
        folder_id: str,
        t_min: float,
        t_max: float,
        bar_height: int = 1000,
        bar_width: int = 70,
    ):
        import matplotlib.cm as _cm
        from PIL import Image
        import numpy as np
        import os

        _lut_f = _cm.inferno(np.linspace(0, 1, 256))[:, :3]
        lut = (_lut_f * 255).astype(np.uint8)

        bar = np.zeros((bar_height, bar_width, 3), dtype=np.uint8)

        for row in range(bar_height):
            idx = int((1.0 - row / (bar_height - 1)) * 255)
            bar[row] = lut[idx]

        img = Image.fromarray(bar)

        out_dir = f"./output/{folder_id}/validation_thermal_images"
        os.makedirs(out_dir, exist_ok=True)

        out_path = f"{out_dir}/thermal_colorbar_legend.png"
        img.save(out_path)

        print(f"[COLORBAR] Saved legend → {out_path}")

    # ══════════════════════════════════════════════════════════════════════════════
    #  A-1  UTCI
    # ══════════════════════════════════════════════════════════════════════════════
    
    def compute_utci(self, ta: float, tmrt: float, va: float, rh: float, va_10m: float = None) -> tuple:
        """
        Universal Thermal Climate Index via Bröde et al. (2012) polynomial.
    
        Uses pythermalcomfort as the primary implementation (peer-reviewed
        reference code), falls back to the exact inline polynomial when the
        package is absent.
    
        Parameters
        ----------
        ta   : float  Dry-bulb air temperature [°C]
        tmrt : float  Mean radiant temperature [°C]
        va   : float  Wind speed at 2 m sensor height [m/s]
        va_10m : float, optional  Raw wind speed already measured at 10 m —
                 pass this (main.py supplies it from the un-reduced Open-Meteo
                 value) to avoid round-tripping the 1.1 m value back up
                 through a second log-law conversion.
        rh   : float  Relative humidity [%]
    
        Returns
        -------
        utci_val : float   UTCI [°C]
        category : str     Thermal stress category
    
        References
        ----------
        Bröde P et al. (2012) Int J Biometeorol 56:481–494
        Fiala D et al.  (2012) Int J Biometeorol 56:395–408
        Tartarini & Schiavon (2020) SoftwareX 12:100578
        """
        if va_10m is None:
            raise ValueError(
                "compute_utci() requires va_10m (raw 10 m wind speed). "
                "UTCI's Fiala-model polynomial expects 10 m wind, not the "
                "1.1 m pedestrian-height value used for PET — passing va "
                "here instead of a real va_10m would silently corrupt UTCI."
            )
        va_10m = float(np.clip(va_10m, 0.5, 17.0))
    
        # ── Primary: pythermalcomfort reference implementation ────────────────────
        try:
            from pythermalcomfort.models import utci as _utci_fn
            result   = _utci_fn(tdb=ta, tr=tmrt, v=va_10m, rh=rh,
                                units="SI", limit_inputs=False)
            utci_val = result.utci if hasattr(result, "utci") else result["utci"]
            if utci_val is None or (isinstance(utci_val, float) and math.isnan(utci_val)):
                raise ValueError("out of range")
            utci_val = float(utci_val)
    
        except ImportError:
            print("[UTCI] pythermalcomfort not found — using built-in polynomial.  "
                "pip install pythermalcomfort>=2.10.0")
            utci_val = self._utci_polynomial(ta, va_10m, tmrt, rh)
        except Exception as exc:
            print(f"[UTCI] pythermalcomfort failed ({exc}) — using built-in polynomial.")
            utci_val = self._utci_polynomial(ta, va_10m, tmrt, rh)
    
        return utci_val, self._utci_stress_category(utci_val)
    
    
    @staticmethod
    def _utci_polynomial(Ta: float, va: float, Tmrt: float, RH: float) -> float:
        """
        Exact 210-term UTCI polynomial approximation.
    
        Variable order matches the reference implementation exactly:
            Ta, va, D_Tmrt (= Tmrt − Ta), Pa (vapor pressure in kPa).
    
        Source: Walther & Goostchel (2018); Bröde et al. (2012) Appendix.
        Verified coefficient-by-coefficient against the reference code.
        """
        # Saturation vapor pressure [hPa] — Magnus formula (same as reference Syst())
        es_hPa = 6.105 * math.exp(17.27 * Ta / (237.7 + Ta))
        ehPa   = es_hPa * (RH / 100.0)   # actual vapor pressure [hPa]
        Pa     = ehPa / 10.0              # [hPa] → [kPa]
        D_Tmrt = Tmrt - Ta
    
        UTCI_approx = (
            Ta
            + 0.607562052
            + (-0.0227712343)   * Ta
            + (8.06470249e-4)   * Ta * Ta
            + (-1.54271372e-4)  * Ta * Ta * Ta
            + (-3.24651735e-6)  * Ta * Ta * Ta * Ta
            + (7.32602852e-8)   * Ta * Ta * Ta * Ta * Ta
            + (1.35959073e-9)   * Ta * Ta * Ta * Ta * Ta * Ta
            # ── va terms ──────────────────────────────────────────────────────────
            + (-2.25836520)     * va
            + 0.0880326035      * Ta * va
            + 0.00216844454     * Ta * Ta * va
            + (-1.53347087e-5)  * Ta * Ta * Ta * va
            + (-5.72983704e-7)  * Ta * Ta * Ta * Ta * va
            + (-2.55090145e-9)  * Ta * Ta * Ta * Ta * Ta * va
            + (-0.751269505)    * va * va
            + (-0.00408350271)  * Ta * va * va
            + (-5.21670675e-5)  * Ta * Ta * va * va
            + (1.94544667e-6)   * Ta * Ta * Ta * va * va
            + (1.14099531e-8)   * Ta * Ta * Ta * Ta * va * va
            + 0.158137256       * va * va * va
            + (-6.57263143e-5)  * Ta * va * va * va
            + (2.22697524e-7)   * Ta * Ta * va * va * va
            + (-4.16117031e-8)  * Ta * Ta * Ta * va * va * va
            + (-0.0127762753)   * va * va * va * va
            + (9.66891875e-6)   * Ta * va * va * va * va
            + (2.52785852e-9)   * Ta * Ta * va * va * va * va
            + (4.56306672e-4)   * va * va * va * va * va
            + (-1.74202546e-7)  * Ta * va * va * va * va * va
            + (-5.91491269e-6)  * va * va * va * va * va * va
            # ── D_Tmrt terms ──────────────────────────────────────────────────────
            + 0.398374029       * D_Tmrt
            + (1.83945314e-4)   * Ta * D_Tmrt
            + (-1.73754510e-4)  * Ta * Ta * D_Tmrt
            + (-7.60781159e-7)  * Ta * Ta * Ta * D_Tmrt
            + (3.77830287e-8)   * Ta * Ta * Ta * Ta * D_Tmrt
            + (5.43079673e-10)  * Ta * Ta * Ta * Ta * Ta * D_Tmrt
            + (-0.0200518269)   * va * D_Tmrt
            + (8.92859837e-4)   * Ta * va * D_Tmrt
            + (3.45433048e-6)   * Ta * Ta * va * D_Tmrt
            + (-3.77925774e-7)  * Ta * Ta * Ta * va * D_Tmrt
            + (-1.69699377e-9)  * Ta * Ta * Ta * Ta * va * D_Tmrt
            + (1.69992415e-4)   * va * va * D_Tmrt
            + (-4.99204314e-5)  * Ta * va * va * D_Tmrt
            + (2.47417178e-7)   * Ta * Ta * va * va * D_Tmrt
            + (1.07596466e-8)   * Ta * Ta * Ta * va * va * D_Tmrt
            + (8.49242932e-5)   * va * va * va * D_Tmrt
            + (1.35191328e-6)   * Ta * va * va * va * D_Tmrt
            + (-6.21531254e-9)  * Ta * Ta * va * va * va * D_Tmrt
            + (-4.99410301e-6)  * va * va * va * va * D_Tmrt
            + (-1.89489258e-8)  * Ta * va * va * va * va * D_Tmrt
            + (8.15300114e-8)   * va * va * va * va * va * D_Tmrt
            + (7.55043090e-4)   * D_Tmrt * D_Tmrt
            + (-5.65095215e-5)  * Ta * D_Tmrt * D_Tmrt
            + (-4.52166564e-7)  * Ta * Ta * D_Tmrt * D_Tmrt
            + (2.46688878e-8)   * Ta * Ta * Ta * D_Tmrt * D_Tmrt
            + (2.42674348e-10)  * Ta * Ta * Ta * Ta * D_Tmrt * D_Tmrt
            + (1.54547250e-4)   * va * D_Tmrt * D_Tmrt
            + (5.24110970e-6)   * Ta * va * D_Tmrt * D_Tmrt
            + (-8.75874982e-8)  * Ta * Ta * va * D_Tmrt * D_Tmrt
            + (-1.50743064e-9)  * Ta * Ta * Ta * va * D_Tmrt * D_Tmrt
            + (-1.56236307e-5)  * va * va * D_Tmrt * D_Tmrt
            + (-1.33895614e-7)  * Ta * va * va * D_Tmrt * D_Tmrt
            + (2.49709824e-9)   * Ta * Ta * va * va * D_Tmrt * D_Tmrt
            + (6.51711721e-7)   * va * va * va * D_Tmrt * D_Tmrt
            + (1.94960053e-9)   * Ta * va * va * va * D_Tmrt * D_Tmrt
            + (-1.00361113e-8)  * va * va * va * va * D_Tmrt * D_Tmrt
            + (-1.21206673e-5)  * D_Tmrt * D_Tmrt * D_Tmrt
            + (-2.18203660e-7)  * Ta * D_Tmrt * D_Tmrt * D_Tmrt
            + (7.51269482e-9)   * Ta * Ta * D_Tmrt * D_Tmrt * D_Tmrt
            + (9.79063848e-11)  * Ta * Ta * Ta * D_Tmrt * D_Tmrt * D_Tmrt
            + (1.25006734e-6)   * va * D_Tmrt * D_Tmrt * D_Tmrt
            + (-1.81584736e-9)  * Ta * va * D_Tmrt * D_Tmrt * D_Tmrt
            + (-3.52197671e-10) * Ta * Ta * va * D_Tmrt * D_Tmrt * D_Tmrt
            + (-3.36514630e-8)  * va * va * D_Tmrt * D_Tmrt * D_Tmrt
            + (1.35908359e-10)  * Ta * va * va * D_Tmrt * D_Tmrt * D_Tmrt
            + (4.17032620e-10)  * va * va * va * D_Tmrt * D_Tmrt * D_Tmrt
            + (-1.30369025e-9)  * D_Tmrt * D_Tmrt * D_Tmrt * D_Tmrt
            + (4.13908461e-10)  * Ta * D_Tmrt * D_Tmrt * D_Tmrt * D_Tmrt
            + (9.22652254e-12)  * Ta * Ta * D_Tmrt * D_Tmrt * D_Tmrt * D_Tmrt
            + (-5.08220384e-9)  * va * D_Tmrt * D_Tmrt * D_Tmrt * D_Tmrt
            + (-2.24730961e-11) * Ta * va * D_Tmrt * D_Tmrt * D_Tmrt * D_Tmrt
            + (1.17139133e-10)  * va * va * D_Tmrt * D_Tmrt * D_Tmrt * D_Tmrt
            + (6.62154879e-10)  * D_Tmrt * D_Tmrt * D_Tmrt * D_Tmrt * D_Tmrt
            + (4.03863260e-13)  * Ta * D_Tmrt * D_Tmrt * D_Tmrt * D_Tmrt * D_Tmrt
            + (1.95087203e-12)  * va * D_Tmrt * D_Tmrt * D_Tmrt * D_Tmrt * D_Tmrt
            + (-4.73602469e-12) * D_Tmrt * D_Tmrt * D_Tmrt * D_Tmrt * D_Tmrt * D_Tmrt
            # ── Pa terms ──────────────────────────────────────────────────────────
            + 5.12733497        * Pa
            + (-0.312788561)    * Ta * Pa
            + (-0.0196701861)   * Ta * Ta * Pa
            + (9.99690870e-4)   * Ta * Ta * Ta * Pa
            + (9.51738512e-6)   * Ta * Ta * Ta * Ta * Pa
            + (-4.66426341e-7)  * Ta * Ta * Ta * Ta * Ta * Pa
            + 0.548050612       * va * Pa
            + (-0.00330552823)  * Ta * va * Pa
            + (-0.00164119440)  * Ta * Ta * va * Pa
            + (-5.16670694e-6)  * Ta * Ta * Ta * va * Pa
            + (9.52692432e-7)   * Ta * Ta * Ta * Ta * va * Pa
            + (-0.0429223622)   * va * va * Pa
            + 0.00500845667     * Ta * va * va * Pa
            + (1.00601257e-6)   * Ta * Ta * va * va * Pa
            + (-1.81748644e-6)  * Ta * Ta * Ta * va * va * Pa
            + (-1.25813502e-3)  * va * va * va * Pa
            + (-1.79330391e-4)  * Ta * va * va * va * Pa
            + (2.34994441e-6)   * Ta * Ta * va * va * va * Pa
            + (1.29735808e-4)   * va * va * va * va * Pa
            + (1.29064870e-6)   * Ta * va * va * va * va * Pa
            + (-2.28558686e-6)  * va * va * va * va * va * Pa
            + (-0.0369476348)   * D_Tmrt * Pa
            + 0.00162325322     * Ta * D_Tmrt * Pa
            + (-3.14279680e-5)  * Ta * Ta * D_Tmrt * Pa
            + (2.59835559e-6)   * Ta * Ta * Ta * D_Tmrt * Pa
            + (-4.77136523e-8)  * Ta * Ta * Ta * Ta * D_Tmrt * Pa
            + (8.64203390e-3)   * va * D_Tmrt * Pa
            + (-6.87405181e-4)  * Ta * va * D_Tmrt * Pa
            + (-9.13863872e-6)  * Ta * Ta * va * D_Tmrt * Pa
            + (5.15916806e-7)   * Ta * Ta * Ta * va * D_Tmrt * Pa
            + (-3.59217476e-5)  * va * va * D_Tmrt * Pa
            + (3.28696511e-5)   * Ta * va * va * D_Tmrt * Pa
            + (-7.10542454e-7)  * Ta * Ta * va * va * D_Tmrt * Pa
            + (-1.24382300e-5)  * va * va * va * D_Tmrt * Pa
            + (-7.38584400e-9)  * Ta * va * va * va * D_Tmrt * Pa
            + (2.20609296e-7)   * va * va * va * va * D_Tmrt * Pa
            + (-7.32469180e-4)  * D_Tmrt * D_Tmrt * Pa
            + (-1.87381964e-5)  * Ta * D_Tmrt * D_Tmrt * Pa
            + (4.80925239e-6)   * Ta * Ta * D_Tmrt * D_Tmrt * Pa
            + (-8.75492040e-8)  * Ta * Ta * Ta * D_Tmrt * D_Tmrt * Pa
            + (2.77862930e-5)   * va * D_Tmrt * D_Tmrt * Pa
            + (-5.06004592e-6)  * Ta * va * D_Tmrt * D_Tmrt * Pa
            + (1.14325367e-7)   * Ta * Ta * va * D_Tmrt * D_Tmrt * Pa
            + (2.53016723e-6)   * va * va * D_Tmrt * D_Tmrt * Pa
            + (-1.72857035e-8)  * Ta * va * va * D_Tmrt * D_Tmrt * Pa
            + (-3.95079398e-8)  * va * va * va * D_Tmrt * D_Tmrt * Pa
            + (-3.59413173e-7)  * D_Tmrt * D_Tmrt * D_Tmrt * Pa
            + (7.04388046e-7)   * Ta * D_Tmrt * D_Tmrt * D_Tmrt * Pa
            + (-1.89309167e-8)  * Ta * Ta * D_Tmrt * D_Tmrt * D_Tmrt * Pa
            + (-4.79768731e-7)  * va * D_Tmrt * D_Tmrt * D_Tmrt * Pa
            + (7.96079978e-9)   * Ta * va * D_Tmrt * D_Tmrt * D_Tmrt * Pa
            + (1.62897058e-9)   * va * va * D_Tmrt * D_Tmrt * D_Tmrt * Pa
            + (3.94367674e-8)   * D_Tmrt * D_Tmrt * D_Tmrt * D_Tmrt * Pa
            + (-1.18566247e-9)  * Ta * D_Tmrt * D_Tmrt * D_Tmrt * D_Tmrt * Pa
            + (3.34678041e-10)  * va * D_Tmrt * D_Tmrt * D_Tmrt * D_Tmrt * Pa
            + (-1.15606447e-10) * D_Tmrt * D_Tmrt * D_Tmrt * D_Tmrt * D_Tmrt * Pa
            + (-2.80626406)     * Pa * Pa
            + 0.548712484       * Ta * Pa * Pa
            + (-0.00399428410)  * Ta * Ta * Pa * Pa
            + (-9.54009191e-4)  * Ta * Ta * Ta * Pa * Pa
            + (1.93090978e-5)   * Ta * Ta * Ta * Ta * Pa * Pa
            + (-0.308806365)    * va * Pa * Pa
            + 0.0116952364      * Ta * va * Pa * Pa
            + (4.95271903e-4)   * Ta * Ta * va * Pa * Pa
            + (-1.90710882e-5)  * Ta * Ta * Ta * va * Pa * Pa
            + 0.00210787756     * va * va * Pa * Pa
            + (-6.98445738e-4)  * Ta * va * va * Pa * Pa
            + (2.30109073e-5)   * Ta * Ta * va * va * Pa * Pa
            + (4.17856590e-4)   * va * va * va * Pa * Pa
            + (-1.27043871e-5)  * Ta * va * va * va * Pa * Pa
            + (-3.04620472e-6)  * va * va * va * va * Pa * Pa
            + 0.0514507424      * D_Tmrt * Pa * Pa
            + (-0.00432510997)  * Ta * D_Tmrt * Pa * Pa
            + (8.99281156e-5)   * Ta * Ta * D_Tmrt * Pa * Pa
            + (-7.14663943e-7)  * Ta * Ta * Ta * D_Tmrt * Pa * Pa
            + (-2.66016305e-4)  * va * D_Tmrt * Pa * Pa
            + (2.63789586e-4)   * Ta * va * D_Tmrt * Pa * Pa
            + (-7.01199003e-6)  * Ta * Ta * va * D_Tmrt * Pa * Pa
            + (-1.06823306e-4)  * va * va * D_Tmrt * Pa * Pa
            + (3.61341136e-6)   * Ta * va * va * D_Tmrt * Pa * Pa
            + (2.29748967e-7)   * va * va * va * D_Tmrt * Pa * Pa
            + (3.04788893e-4)   * D_Tmrt * D_Tmrt * Pa * Pa
            + (-6.42070836e-5)  * Ta * D_Tmrt * D_Tmrt * Pa * Pa
            + (1.16257971e-6)   * Ta * Ta * D_Tmrt * D_Tmrt * Pa * Pa
            + (7.68023384e-6)   * va * D_Tmrt * D_Tmrt * Pa * Pa
            + (-5.47446896e-7)  * Ta * va * D_Tmrt * D_Tmrt * Pa * Pa
            + (-3.59937910e-8)  * va * va * D_Tmrt * D_Tmrt * Pa * Pa
            + (-4.36497725e-6)  * D_Tmrt * D_Tmrt * D_Tmrt * Pa * Pa
            + (1.68737969e-7)   * Ta * D_Tmrt * D_Tmrt * D_Tmrt * Pa * Pa
            + (2.67489271e-8)   * va * D_Tmrt * D_Tmrt * D_Tmrt * Pa * Pa
            + (3.23926897e-9)   * D_Tmrt * D_Tmrt * D_Tmrt * D_Tmrt * Pa * Pa
            + (-0.0353874123)   * Pa * Pa * Pa
            + (-0.221201190)    * Ta * Pa * Pa * Pa
            + 0.0155126038      * Ta * Ta * Pa * Pa * Pa
            + (-2.63917279e-4)  * Ta * Ta * Ta * Pa * Pa * Pa
            + 0.0453433455      * va * Pa * Pa * Pa
            + (-0.00432943862)  * Ta * va * Pa * Pa * Pa
            + (1.45389826e-4)   * Ta * Ta * va * Pa * Pa * Pa
            + (2.17508610e-4)   * va * va * Pa * Pa * Pa
            + (-6.66724702e-5)  * Ta * va * va * Pa * Pa * Pa
            + (3.33217140e-5)   * va * va * va * Pa * Pa * Pa
            + (-0.00226921615)  * D_Tmrt * Pa * Pa * Pa
            + (3.80261982e-4)   * Ta * D_Tmrt * Pa * Pa * Pa
            + (-5.45314314e-9)  * Ta * Ta * D_Tmrt * Pa * Pa * Pa
            + (-7.96355448e-4)  * va * D_Tmrt * Pa * Pa * Pa
            + (2.53458034e-5)   * Ta * va * D_Tmrt * Pa * Pa * Pa
            + (-6.31223658e-6)  * va * va * D_Tmrt * Pa * Pa * Pa
            + (3.02122035e-4)   * D_Tmrt * D_Tmrt * Pa * Pa * Pa
            + (-4.77403547e-6)  * Ta * D_Tmrt * D_Tmrt * Pa * Pa * Pa
            + (1.73825715e-6)   * va * D_Tmrt * D_Tmrt * Pa * Pa * Pa
            + (-4.09087898e-7)  * D_Tmrt * D_Tmrt * D_Tmrt * Pa * Pa * Pa
            + 0.614155345       * Pa * Pa * Pa * Pa
            + (-0.0616755931)   * Ta * Pa * Pa * Pa * Pa
            + 0.00133374846     * Ta * Ta * Pa * Pa * Pa * Pa
            + 0.00355375387     * va * Pa * Pa * Pa * Pa
            + (-5.13027851e-4)  * Ta * va * Pa * Pa * Pa * Pa
            + (1.02449757e-4)   * va * va * Pa * Pa * Pa * Pa
            + (-0.00148526421)  * D_Tmrt * Pa * Pa * Pa * Pa
            + (-4.11469183e-5)  * Ta * D_Tmrt * Pa * Pa * Pa * Pa
            + (-6.80434415e-6)  * va * D_Tmrt * Pa * Pa * Pa * Pa
            + (-9.77675906e-6)  * D_Tmrt * D_Tmrt * Pa * Pa * Pa * Pa
            + 0.0882773108      * Pa * Pa * Pa * Pa * Pa
            + (-0.00301859306)  * Ta * Pa * Pa * Pa * Pa * Pa
            + 0.00104452989     * va * Pa * Pa * Pa * Pa * Pa
            + (2.47090539e-4)   * D_Tmrt * Pa * Pa * Pa * Pa * Pa
            + 0.00148348065     * Pa * Pa * Pa * Pa * Pa * Pa
        )
    
        return UTCI_approx
    
    
    @staticmethod
    def _utci_stress_category(utci: float) -> str:
        """Thermal stress category per Bröde et al. (2012) Table 1."""
        if utci < -40:  return "extreme cold stress"
        if utci < -27:  return "very strong cold stress"
        if utci < -13:  return "strong cold stress"
        if utci <   0:  return "moderate cold stress"
        if utci <   9:  return "slight cold stress"
        if utci <  26:  return "no thermal stress"
        if utci <  32:  return "moderate heat stress"
        if utci <  38:  return "strong heat stress"
        if utci <  46:  return "very strong heat stress"
        return "extreme heat stress"
    
    
    
    
    @staticmethod
    def _pet_vaso(tcore: float, tsk: float) -> tuple:
        """
        Skin blood flow [L/m²/h] and alpha weighting (Höppe 1999).
        Controls heat exchange between core and shell via blood convection.
        """
        sig_skin = _PET_tsk_set - tsk
        sig_core = tcore - _PET_tc_set
        if sig_core < 0:
            sig_core = 0.0
        if sig_skin < 0:
            sig_skin = 0.0
        qmblood = (6.3 + 75.0 * sig_core) / (1.0 + 0.5 * sig_skin)
        if qmblood > 90.0:
            qmblood = 90.0
        alpha = 0.1   # fixed weighting as in reference (not transient model)
        return qmblood, alpha
    
    
    @staticmethod
    def _pet_sweat(tbody: float, tsk: float) -> float:
        """
        Sweat rate [g/m²/h] (Höppe 1999 / reference eq. for MEMI).
        Activated when body temperature exceeds set-point.
        """
        sig_body = tbody - _PET_tbody_set
        sig_skin = tsk   - _PET_tsk_set
        if sig_body < 0:
            sig_body = 0.0
        if sig_skin < 0:
            sig_skin = 0.0
        qmsw = 304.94e-3 * sig_body   # [g/m²/h]
        if qmsw > 500.0:
            qmsw = 500.0
        return qmsw
    
    
    @staticmethod
    def _pet_system(T, Ta, Tmrt, HR, v, age, sex, ht, mbody, pos, M, icl, mode):
        """
        3-node MEMI heat balance residuals (core | skin | clothing).
    
        T    : [Tcore, Tskin, Tclo]  [°C]
        mode : True  → return residual vector for fsolve (actual environment)
            False → return scalar balance for PET bisection (reference env)
    
        Ported from Walther & Goostchel (2018) Syst() without modification.
        Reference: Höppe (1999); VDI 3787 Part 2 (2008).
        """
        # Convert list to column array for vectorised balance
        arr = np.array([[T[0]], [T[1]], [T[2]]], dtype=float)
        Tc, Tsk, Tcl = arr[0, 0], arr[1, 0], arr[2, 0]
    
        enbal = np.zeros((3, 1))
    
        # ── Body geometry ─────────────────────────────────────────────────────────
        Adu  = 0.203 * mbody ** 0.425 * ht ** 0.725     # DuBois area [m²]
        feff = 0.725 if pos in (1, 3) else 0.696         # effective radiation area factor
        fcl  = 1.0 + 0.31 * icl                          # clothing area factor
        facl = (173.51 * icl - 2.36 - 100.76 * icl**2 + 19.28 * icl**3) / 100.0
        Aclo = Adu * facl + Adu * (fcl - 1.0)           # clothing surface area [m²]
        Aeffr = Adu * feff                               # effective radiative area [m²]
    
        # ── Vapour pressure ────────────────────────────────────────────────────────
        if mode:   # actual environment
            vpa = HR / 100.0 * 6.105 * math.exp(17.27 * Ta / (237.7 + Ta))  # [hPa]
        else:      # PET reference environment: fixed 12 hPa (≈ 50% RH at 20°C)
            vpa = 12.0
    
        # ── Convection coefficient [W/m²K] ────────────────────────────────────────
        hc = 0.0
        if pos == 1:  hc = 2.67 + 6.5  * v ** 0.67
        if pos == 2:  hc = 2.26 + 7.42 * v ** 0.67
        if pos == 3:
            hc = 8.6 * v ** 0.513
            hc *= (_PET_p / _PET_po) ** 0.55
    
        # ── Basal metabolism [W] ──────────────────────────────────────────────────
        bmi_term = ht * 100.0 / mbody ** (1.0 / 3.0)
        metab_m = 3.45 * mbody**0.75 * (1.0 + 0.004*(30.0-age) + 0.010*(bmi_term - 43.4))
        metab_f = 3.19 * mbody**0.75 * (1.0 + 0.004*(30.0-age) + 0.018*(bmi_term - 42.1))
    
        if mode:
            he_m = (M + metab_m) / Adu
            he_f = (M + metab_f) / Adu
        else:   # reference environment always uses 80 W activity
            he_m = (80.0 + metab_m) / Adu
            he_f = (80.0 + metab_f) / Adu
    
        h = (he_m if sex == 1 else he_f) * (1.0 - _PET_eta)   # [W/m²]
    
        # ── Respiration ────────────────────────────────────────────────────────────
        texp    = 0.47 * Ta + 21.0                                      # expired air [°C]
        dvent   = h * 1.44e-6                                           # pulmonary flow [m³/s per m²]
        eres    = _PET_cair * (Ta - texp) * dvent                       # sensible [W/m²]
        vpexp   = 6.11 * 10.0 ** (7.45 * texp / (235.0 + texp))        # [hPa]
        erel    = 0.623 * _PET_Lvap / _PET_p * (vpa - vpexp) * dvent   # latent [W/m²]
        ere     = eres + erel
    
        # ── Clothing thermal resistance ────────────────────────────────────────────
        rcl  = icl / 6.45   # [m²K/W]
        facl = min(facl, 1.0)
        y = 0.0
        if icl >= 2.0:                     y = 1.0
        elif 0.6 < icl < 2.0:             y = (ht - 0.2) / ht
        elif 0.3 < icl <= 0.6:            y = 0.5
        elif 0.0 < icl <= 0.3:            y = 0.1
    
        if y > 0:
            r2   = Adu * (fcl - 1.0 + facl) / (6.28 * ht * y)
            r1   = facl * Adu / (6.28 * ht * y)
            di   = r2 - r1
            if di > 0 and r1 > 0:
                htcl = (6.28 * ht * y * di) / (rcl * math.log(r2 / r1) * Aclo)
            else:
                htcl = 100.0   # negligible resistance when no clothing geometry
        else:
            htcl = 100.0
    
        # ── Vasoconstriction / vasodilation and body temperature ──────────────────
        qmblood, alpha = SurfaceTemperature._pet_vaso(Tc, Tsk)
        tbody = alpha * Tsk + (1.0 - alpha) * Tc
    
        # ── Sweating ──────────────────────────────────────────────────────────────
        qmsw = SurfaceTemperature._pet_sweat(tbody, Tsk)
        esw  = _PET_Lvap / 1000.0 * qmsw / 3600.0   # [W/m²]  (g/m²/h → W/m²)
    
        # ── Skin saturation vapour pressure and evaporation ──────────────────────
        Pvsk    = 6.105 * math.exp((17.27 * (Tsk + 273.15) - 4717.03) / (237.7 + Tsk))
        Lw      = 16.7e-1        # [K/hPa] Lewis factor
        he_diff = hc * Lw        # diffusion coefficient of air layer
        fecl    = 1.0 / (1.0 + 0.92 * hc * rcl)
        emax    = he_diff * fecl * (Pvsk - vpa)
        w       = esw / emax if emax > 0 else 1.0
        if w > 1.0:
            w   = 1.0
            esw = max(esw, emax) if emax > 0 else esw
        if esw < 0.0:
            esw = 0.0
        i_m  = 0.38
        Recl = (1.0 / (fcl * hc) + rcl) / (Lw * i_m)
        ediff = (1.0 - w) * (Pvsk - vpa) / Recl
        evap  = -(ediff + esw)
    
        # ── Radiation ─────────────────────────────────────────────────────────────
        Tmrt_K = (Tmrt + 273.15) ** 4
        Tsk_K  = (Tsk  + 273.15) ** 4
        Tcl_K  = (Tcl  + 273.15) ** 4
    
        rbare = Aeffr * (1.0 - facl) * _PET_emsk * _PET_sigm * (Tmrt_K - Tsk_K) / Adu
        rclo  = feff  * Aclo         * _PET_emcl * _PET_sigm * (Tmrt_K - Tcl_K) / Adu
        rsum  = rclo + rbare
    
        # ── Convection ────────────────────────────────────────────────────────────
        cbare = hc * (Ta  - Tsk) * Adu * (1.0 - facl) / Adu
        cclo  = hc * (Ta  - Tcl) * Aclo / Adu
        csum  = cclo + cbare
    
        # ── 3-node balance equations ──────────────────────────────────────────────
        blood_term = (qmblood / 3600.0 * _PET_cb + 5.28) * (Tc - Tsk)
        enbal[0, 0] = h + ere - blood_term                          # core
        enbal[1, 0] = rbare + cbare + evap + blood_term - htcl * (Tsk - Tcl)  # skin
        enbal[2, 0] = cclo  + rclo  + htcl * (Tsk - Tcl)           # clothing
    
        enbal_scal = h + ere + rsum + csum + evap                   # scalar balance
    
        if mode:
            return [enbal[0, 0], enbal[1, 0], enbal[2, 0]]
        else:
            return enbal_scal
    
    
    @staticmethod
    def _pet_solve_actual(Ta, Tmrt, HR, v, age, sex, ht, mbody, pos, M, icl):
        """
        Solve 3-node system for actual conditions via scipy.optimize.fsolve.
        Returns [Tcore, Tskin, Tclo].
        """
        T0 = [38.0, 35.0, 34.0]   # physiologically reasonable initial guess
        Tstable = optimize.fsolve(
            SurfaceTemperature._pet_system,
            T0,
            args=(Ta, Tmrt, HR, v, age, sex, ht, mbody, pos, M, icl, True),
            full_output=False,
        )
        return Tstable
    
    
    @staticmethod
    def _pet_find_pet(age, sex, ht, mbody, pos, M, icl, Tstable):
        """
        Find PET by bisection on the scalar energy balance of the reference
        environment (Ta=Tmrt, va=0.1 m/s, HR=50 → ea=12 hPa).
    
        Bisects on Syst(Tstable, Tx, Tx, 50, 0.1, ..., mode=False) = 0.
        """
        eps = 1e-6
        Tmin, Tmax = -40.0, 90.0
    
        def f(Tx):
            return SurfaceTemperature._pet_system(
                Tstable, Tx, Tx, 50.0, 0.1,
                age, sex, ht, mbody, pos, M, 0.9, False
            )
    
        Ti, Tf = Tmin, Tmax
        pet = 0.0
        while Tf - Ti > eps:
            if f(Ti) * f(pet) < 0:
                Tf = pet
            else:
                Ti = pet
            pet = (Ti + Tf) / 2.0
    
        return pet
    
    
    def compute_pet(
        self,
        ta:       float,
        tmrt:     float,
        va:       float,
        rh:       float,
        pressure: float = 101325.0,
        met:      float = 80.0,
        icl:      float = 0.9,
        age:      int   = 35,
        sex:      int   = 1,
        height:   float = 1.80,
        mass:     float = 75.0,
        pos:      int   = 1,
    ) -> tuple:
        """
        Physiologically Equivalent Temperature (PET) via 3-node MEMI.
    
        Parameters
        ----------
        ta, tmrt : float  Air and mean radiant temperature [°C]
        va       : float  Wind speed [m/s]
        rh       : float  Relative humidity [%]
        pressure : float  Atmospheric pressure [Pa]
        met      : float  Activity metabolic rate [W]  (80 = slow walk)
        icl      : float  Clothing insulation [clo]    (0.9 = light summer)
        age      : int    Subject age [years]          (35 = ISO standard)
        sex      : int    1 = male, 2 = female
        height   : float  Subject height [m]           (1.80 = ISO standard)
        mass     : float  Subject mass [kg]            (75 = ISO standard)
        pos      : int    Position: 1=standing, 2=sitting, 3=crouching
    
        Returns
        -------
        pet_val  : float  PET [°C]
        category : str    Thermal perception category
    
        References
        ----------
        Höppe P (1999) Int J Biometeorol 43:10–18
        VDI 3787 Part 2 (2008)
        Walther E, Goostchel Q (2018) Build Environ 128:285–295
        """
        # ── Primary: pythermalcomfort ─────────────────────────────────────────────
        try:
            from pythermalcomfort.models import pet_stat as _pet_fn
            AD_std  = 0.203 * (mass ** 0.425) * (height ** 0.725)
            met_unit = met / (58.2 * AD_std)   # W → met
            result   = _pet_fn(tdb=ta, tr=tmrt, v=max(va, 0.1), rh=rh,
                            met=met_unit, clo=icl)
            pet_val  = result.pet if hasattr(result, "pet") else result["pet"]
            if pet_val is None or (isinstance(pet_val, float) and math.isnan(pet_val)):
                raise ValueError("out of range")
            pet_val  = float(pet_val)
    
        except (ImportError, Exception):
            # ── Fallback: full 3-node MEMI ────────────────────────────────────────
            va_eff  = max(va, 0.1)
            Tstable = self._pet_solve_actual(ta, tmrt, rh, va_eff, age, sex,
                                            height, mass, pos, met, icl)
            pet_val = self._pet_find_pet(age, sex, height, mass, pos, met, icl, Tstable)
    
        return pet_val, self._pet_thermal_category(pet_val)
    
    
    @staticmethod
    def _pet_thermal_category(pet: float) -> str:
        """Thermal perception per Matzarakis & Mayer (1996) Table 1."""
        if pet <  4:  return "extreme cold stress"
        if pet <  8:  return "very strong cold stress"
        if pet < 13:  return "strong cold stress"
        if pet < 18:  return "moderate cold stress"
        if pet < 23:  return "slight cold stress"
        if pet < 29:  return "comfortable"
        if pet < 35:  return "slight heat stress"
        if pet < 41:  return "moderate heat stress"
        if pet < 45:  return "strong heat stress"
        return "very strong heat stress"
    
    
    # ── A-3: Combined wrapper (unchanged from before) ────────────────────────────
    
    def compute_thermal_indices(
        self,
        ta:       float,
        tmrt:     float,
        va:       float,
        rh:       float,
        pressure: float = 101325.0,
        met:      float = 80.0,
        icl:      float = 0.9,
        va_10m:   float = None,
    ) -> dict:
        """Compute UTCI and PET. Returns dict with utci, utci_category, pet, pet_category."""
        try:
            utci_val, utci_cat = self.compute_utci(ta, tmrt, va, rh, va_10m=va_10m)
        except Exception as exc:
            print(f"[THERMAL] UTCI failed: {exc}")
            utci_val, utci_cat = float("nan"), "N/A"
    
        try:
            pet_val, pet_cat = self.compute_pet(ta, tmrt, va, rh, pressure, met, icl)
        except Exception as exc:
            print(f"[THERMAL] PET failed: {exc}")
            pet_val, pet_cat = float("nan"), "N/A"
    
        return {
            "utci":          utci_val,
            "utci_category": utci_cat,
            "pet":           pet_val,
            "pet_category":  pet_cat,
        }
    


    def execute(
            self,
            segmentation_data,
            local_times,
            shadow_data,
            location,
            measurements,
            minute_delta,
            radii_by_fisheye_subset,
            fractions_by_fisheye_subset,
            csv_path,
            surface_temperature_data,
            folder_id,
            timezone: str = "America/Phoenix",
    ):
        """Python implementation of the C++ SurfaceTemperature::execute function (OPTIMIZED)."""

        # ── Start image processing thread ─────────────────────────────────────────
        self.image_thread = threading.Thread(target=self._image_worker)
        self.image_thread.daemon = True
        self.image_thread.start()

        DIRECTIONS = ["front", "right", "back", "left", "top", "bottom"]

        # ── Timezone ──────────────────────────────────────────────────────────────
        # Resolved from the site's actual lat/lon by main.py's _resolve_timezone()
        # and passed in here — local_times arrives as naive strings whose
        # wall-clock digits are already correct for that timezone, so we must
        # re-attach the SAME timezone here, not assume Phoenix, or every solar
        # position / sunrise-sunset calculation below silently uses the wrong
        # absolute instant for non-Phoenix sites.
        mst = pytz.timezone(timezone)
        local_times_strings = local_times[:]
        local_times = []
        for tstr in local_times_strings:
            naïve = datetime.strptime(tstr, "%Y-%m-%d %H:%M:%S")
            localized = mst.localize(naïve)
            local_times.append(localized)

        # ── Open CSV ──────────────────────────────────────────────────────────────
        os.makedirs(os.path.dirname(csv_path), exist_ok=True)
        write_headers = not os.path.exists(csv_path) or os.stat(csv_path).st_size == 0

        try:
            csv_file = open(csv_path, "a", newline="")
            csv_writer = csv.writer(csv_file)
            if write_headers:
                headers = [
                    "DateTime", "FolderID", "AirTemperature", "RelativeHumidity",
                    "WindVelocity", "CloudCover", "SVF", "SVF_gt", "SunVisible",
                    "SurfaceProjectionFactor", "ExtraterrestrialRadiation",
                    "AtmosphericPressure", "RelativeOpticalAirMass", "OpticalThickness",
                    "VaporPressure", "IncomingRadiation", "GlobalRadiationCloudless",
                    "DiffuseRadiation",
                    "Sensor_LW_Left", "Sensor_LW_Right", "Sensor_LW_Front",
                    "Sensor_LW_Back", "Sensor_LW_Up", "Sensor_LW_Down",
                    "Sensor_SW_Left", "Sensor_SW_Right", "Sensor_SW_Front",
                    "Sensor_SW_Back", "Sensor_SW_Up", "Sensor_SW_Down",
                    "Calc_LW_Left", "Calc_LW_Right", "Calc_LW_Front",
                    "Calc_LW_Back", "Calc_LW_Up", "Calc_LW_Down",
                    "Calc_SW_Left", "Calc_SW_Right", "Calc_SW_Front",
                    "Calc_SW_Back", "Calc_SW_Up", "Calc_SW_Down",
                    "MRT_GroundTruth", "MRT_SensorsData", "MRT_CalcSW_SensorLW",
                    "MRT_SensorSW_CalcLW", "MRT_CalcSW_CalcLW",
                    "UTCI", "UTCI_Category", "PET", "PET_Category",
                ]
                csv_writer.writerow(headers)
        except Exception as e:
            print(f"ERROR: Unable to open '{csv_path}'. Exception: {e}")
            return 0

        n_time_steps = len(local_times)
        n_pixels = self.IMAGE_SIZE * self.IMAGE_SIZE

        # ── Ring indices ──────────────────────────────────────────────────────────
        ring_indices_by_fisheye_subset = {}
        for direction in DIRECTIONS:
            radii = radii_by_fisheye_subset[direction]
            ring_indices_by_fisheye_subset[direction] = (
                np.array(radii) * (self.N_RINGS - 1)
            ).astype(int)

        # ── Segmentation images ───────────────────────────────────────────────────
        for direction, data in segmentation_data.items():
            if not isinstance(data, np.ndarray):
                print(f"[ERROR] Segmentation data for {direction} is not a NumPy array!")
                continue
            self.create_seg_image(data, location, direction, n_pixels, folder_id)

        # ── Sky View Factor ───────────────────────────────────────────────────────
        # The same number the viewer shows: the cosine-weighted sky solid angle from the six segmentation faces (svf.py).
        sky_view_factor = None
        if Config.svf_mode != 'default':
            try:
                import svf as _svf
                _info = _svf.ensure_site_svf(os.path.join("output", folder_id), source="compute")
                if _info and _info.get("svf") is not None and not _info.get("partial"):
                    sky_view_factor = float(_info["svf"])
                    print(f"[SVF] using the site's SVF from the segmentation: {sky_view_factor:.4f}")
            except Exception as e:
                print(f"[SVF] shared SVF not available ({e}); using the fisheye method")
        try:
            if sky_view_factor is not None:
                pass
            elif Config.svf_mode == 'default':
                sky_view_factor = self.compute_sky_view_factor_default(
                    self.N_RINGS,
                    segmented_images=[
                        segmentation_data[d] for d in ["front", "right", "back", "left", "top"]
                    ],
                    fraction_bottom_data=fractions_by_fisheye_subset["bottom"],
                    fraction_center_data=fractions_by_fisheye_subset["top"],
                    ring_indices_bottom=ring_indices_by_fisheye_subset["bottom"],
                    ring_indices_center=ring_indices_by_fisheye_subset["top"],
                    projection_type='cosine'
                )
            elif Config.svf_mode == 'fisheye':
                sky_view_factor = self.process_segmentation_fisheye(
                    {"top": f"output/{folder_id}/fisheye/seg/fisheye_photo_up_0_90.png"},
                    projection_type="angular"
                ).get("top")
            print("Computed SVF:", sky_view_factor)
        except Exception as e:
            print(f"[ERROR] Sky View Factor computation failed: {e}")
            sky_view_factor = 0.5

        svf_gt = measurements["sky_view_factor"][0]

        # ── Enclosure classification (done once, outside the time loop) ───────────
        enclosure_info = self.classify_site_enclosure(segmentation_data, sky_view_factor)

        # ── Precompute cubemap view factors (once, before time loop) ──────────────
        self.vf_map = self.precompute_cubemap_view_factors()
        print("[VF] Cubemap view factors precomputed.")

        # ── Generate colorbar legend image once ───────────────────────────────────
        self._save_colorbar_image(folder_id, T_GLOBAL_MIN, T_GLOBAL_MAX)

        # ── Initialize radiation and conduction arrays ─────────────────────────────
        Q0  = {d: np.zeros(n_pixels)                           for d in DIRECTIONS}
        Q1  = {d: np.zeros(n_pixels)                           for d in DIRECTIONS}
        E   = {d: np.zeros(n_pixels)                           for d in DIRECTIONS}
        Qg  = {d: np.zeros((512, 512), dtype=np.float32)       for d in DIRECTIONS}
        thickness = np.linspace(0.2, 0.2 * self.numlayers, self.numlayers)

        init_temp_K = measurements["air_temperature"][0] + 273.15
        tlayer = {
            d: np.full((n_pixels, self.numlayers), init_temp_K, dtype=np.float32)
            for d in self.DIRECTIONS
        }

        # ── Pre-compute solar positions in one batch call ─────────────────────────
        all_timestamps = pd.DatetimeIndex(local_times)
        pressure      = pvlib.atmosphere.alt2pres(location["altitude"])

        # print(f"[DEBUG] altitude={location['altitude']}, pressure={pressure}")

        all_solpos    = pvlib.solarposition.get_solarposition(
            all_timestamps,
            latitude=location["latitude"],
            longitude=location["longitude"],
            altitude=location["altitude"],
            pressure=pressure,
        )
        # print(f"[DEBUG] all_solpos sample:\n{all_solpos.head()}") 

        # ── Pre-compute sunrise/sunset per unique date ────────────────────────────
        unique_dates = list(set(ts.date() for ts in local_times))
        sunrise_sunset_cache = {}
        for d in unique_dates:
            day_start = pd.Timestamp(d, tz=timezone)
            day_end   = day_start + pd.Timedelta(days=1)
            ss = pvlib.solarposition.sun_rise_set_transit_spa(
                pd.date_range(day_start, day_end, freq='1H'),
                latitude=location["latitude"],
                longitude=location["longitude"]
            )
            sunrise_sunset_cache[d] = (ss['sunrise'].iloc[0], ss['sunset'].iloc[0])

        # # ── Initial surface temperatures ──────────────────────────────────────────
        # air_temperature  = measurements["air_temperature"][0]

        # # # Trees conduction included:
        # # offset_array     = np.array([0, 0, -3, +2, +8, +1, +4], dtype=np.float32)

        # # # Trees conduction excluded: (trees get 0 offset → T_air exactly):
        # offset_array = np.array([0, 0, 0, +2, +8, +1, +4, +8], dtype=np.float32)

        # enclosure_offset = np.array([0, 0, 0, 0, 0, 0, 0, +3], dtype=np.float32)

        # preheat_extra = np.zeros(8, dtype=np.float32)
        # if enclosure_info["type"] in ("semi_enclosed", "fully_enclosed"):
        #     t0_timestamp   = local_times[0]
        #     sunrise_t0, _  = sunrise_sunset_cache[t0_timestamp.date()]
        #     hours_since_sunrise = max(
        #         0.0, (t0_timestamp - sunrise_t0).total_seconds() / 3600.0
        #     )
        #     heating_rate = np.array([0, 0, 0.5, 1.0, 1.2, 0.8, 0.8, 1.0], dtype=np.float32)
        #     max_preheat  = np.array([0, 0, 3.0, 6.0, 8.0, 4.0, 4.0, 5.0], dtype=np.float32)
        #     preheat_extra = np.minimum(heating_rate * hours_since_sunrise, max_preheat)
        #     if Config.debug_mode:
        #         print(f"[PREHEAT] {hours_since_sunrise:.1f}h since sunrise, "
        #               f"wall={preheat_extra[3]:.1f}°C, floor={preheat_extra[4]:.1f}°C")

        # for d in DIRECTIONS:
        #     Ts       = surface_temperature_data[d][0]
        #     seg      = segmentation_data[d]
        #     safe_seg = np.clip(seg, 0, 7)
        #     if enclosure_info["type"] in ("semi_enclosed", "fully_enclosed"):
        #         Ts[:] = air_temperature + (enclosure_offset + preheat_extra)[safe_seg]
        #     else:
        #         Ts[:] = air_temperature + offset_array[safe_seg]
        #     Ts[seg == 1] = np.nan   # sky pixels always NaN

        #     # Trees always start at T_air regardless of enclosure type
        #     Ts[seg == 2] = air_temperature
        #     Ts[seg == 7] = air_temperature

        # ── Initial surface temperatures via pre-dawn spin-up ─────────────────────
        air_temperature  = measurements["air_temperature"][0]
        vapor_pressure_night = self.get_vapor_pressure(
            measurements["relative_humidity"][0], air_temperature
        )
        L_atm_night = self.get_atmospheric_radiation(air_temperature, vapor_pressure_night, 0.0)

        spinup_result = self.spinup_surface_temperatures(
            segmentation_data=segmentation_data,
            air_temperature_night=air_temperature,
            L_atm_night=L_atm_night,
            tlayer=tlayer,
            thickness=thickness,
            n_spinup_hours=4,
            minute_delta=minute_delta,
        )
        for d in DIRECTIONS:
            surface_temperature_data[d][0] = spinup_result[d]

        # ═════════════════════════════════════════════════════════════════════════
        #  MAIN TIME LOOP
        # ═════════════════════════════════════════════════════════════════════════
        for t in range(n_time_steps):
            if Config.early_stop and t == 24:
                break

            print(f"\n===== [t={t}/{n_time_steps-1}] =====")

            date  = local_times[t]
            hour  = date.hour
            if hour >= 21 or hour <= 5:
                print(f"[SKIP] Nighttime (hour={hour})")
                if t > 0:
                    for d in DIRECTIONS:
                        prev = surface_temperature_data[d][t - 1]
                        if prev is not None and not np.all(np.isnan(prev)):
                            surface_temperature_data[d][t] = prev.copy()
                continue

            timestamp = pd.Timestamp(date)
            solpos    = all_solpos.iloc[t]
            sunrise_time, sunset_time = sunrise_sunset_cache[date.date()]
            zenith_angle  = solpos["zenith"]
            azimuth_angle = solpos["azimuth"]

            # ── Adaptive timestep: actual elapsed time between measurements ───────────
            if t == 0:
                # At t=0 no previous timestep — use fixed minute_delta as fallback
                delta_t_minutes = minute_delta
            else:
                elapsed_seconds = (local_times[t] - local_times[t - 1]).total_seconds()
                delta_t_minutes = elapsed_seconds / 60.0

            # Safety clamp: prevent absurdly large gaps (e.g. overnight skip) from
            # blowing up the conduction solver. Cap at 120 min.
            delta_t_minutes = float(np.clip(delta_t_minutes, 1.0, 120.0))

            print(f"[TIMESTEP] t={t}  actual_delta={delta_t_minutes:.1f} min")

            minute_delta = delta_t_minutes

            # ── Get measurements ──────────────────────────────────────────────────
            if measurements["single_mode"]:
                air_temperature   = measurements["air_temperature"][0]
                relative_humidity = measurements["relative_humidity"][0]
                wind_velocity     = measurements["wind_velocity"][0]
                if "wind_velocity_10m" not in measurements:
                    raise ValueError(
                        "measurements['wind_velocity_10m'] is required — "
                        "falling back to wind_velocity (1.1 m) here would feed "
                        "pedestrian-height wind into UTCI's 10 m polynomial term."
                    )
                wind_velocity_10m = measurements["wind_velocity_10m"][0]
                cloud_cover       = measurements["cloud_cover"][0]
                sw_left   = measurements["shortwave_radiation"]["left"][0]
                sw_right  = measurements["shortwave_radiation"]["right"][0]
                sw_front  = measurements["shortwave_radiation"]["front"][0]
                sw_back   = measurements["shortwave_radiation"]["back"][0]
                sw_top    = measurements["shortwave_radiation"]["top"][0]
                sw_bottom = measurements["shortwave_radiation"]["bottom"][0]
                lw_left   = measurements["longwave_radiation"]["left"][0]
                lw_right  = measurements["longwave_radiation"]["right"][0]
                lw_front  = measurements["longwave_radiation"]["front"][0]
                lw_back   = measurements["longwave_radiation"]["back"][0]
                lw_top    = measurements["longwave_radiation"]["top"][0]
                lw_bottom = measurements["longwave_radiation"]["bottom"][0]
                shade_value = measurements["shaded_at_measurement"][0]
            else:
                idx = min(t, len(measurements["air_temperature"]) - 1)
                air_temperature   = measurements["air_temperature"][idx]
                relative_humidity = measurements["relative_humidity"][idx]
                wind_velocity     = measurements["wind_velocity"][idx]
                if "wind_velocity_10m" not in measurements:
                    raise ValueError(
                        "measurements['wind_velocity_10m'] is required — "
                        "falling back to wind_velocity (1.1 m) here would feed "
                        "pedestrian-height wind into UTCI's 10 m polynomial term."
                    )
                wind_velocity_10m = measurements["wind_velocity_10m"][idx]
                cloud_cover       = measurements["cloud_cover"][idx]
                sw_left   = measurements["shortwave_radiation"]["left"][idx]
                sw_right  = measurements["shortwave_radiation"]["right"][idx]
                sw_front  = measurements["shortwave_radiation"]["front"][idx]
                sw_back   = measurements["shortwave_radiation"]["back"][idx]
                sw_top    = measurements["shortwave_radiation"]["top"][idx]
                sw_bottom = measurements["shortwave_radiation"]["bottom"][idx]
                lw_left   = measurements["longwave_radiation"]["left"][idx]
                lw_right  = measurements["longwave_radiation"]["right"][idx]
                lw_front  = measurements["longwave_radiation"]["front"][idx]
                lw_back   = measurements["longwave_radiation"]["back"][idx]
                lw_top    = measurements["longwave_radiation"]["top"][idx]
                lw_bottom = measurements["longwave_radiation"]["bottom"][idx]
                shade_value = measurements["shaded_at_measurement"][idx]

            if t >= len(shadow_data["bottom"]):
                print(f"[WARNING] Missing shadow data at t={t}, skipping.")
                continue

            # ── Thermal mass adjustment (enclosed sites only) ──────────────────────
            # Models two competing effects:
            #   1. overnight_heat — stored warmth decaying from sunrise (τ=3h)
            #   2. thermal_lag   — surfaces lagging behind rising air temp (τ=10h)
            # Net adjustment feeds into J_mean temperature offsets via lw_temp_adjustment.
            lw_temp_adjustment = 0.0
            # if enclosure_info["type"] in ("semi_enclosed", "fully_enclosed"):
            #     sunrise_t, _ = sunrise_sunset_cache[date.date()]
            #     hours_sr = max(0.0, (timestamp - sunrise_t).total_seconds() / 3600.0)
            #     # overnight_heat  = 7.0 * math.exp(-hours_sr / 3.0)
            #     # thermal_lag     = 2.0 * (1.0 - math.exp(-hours_sr / 10.0))
            #     sunset_recovery = (
            #         2.0 * max(0.0, hours_sr - 12.0) * math.exp(-(hours_sr - 12.0) / 3.0)
            #         if hours_sr > 12.0 else 0.0
            #     )
            #     lw_temp_adjustment = overnight_heat - thermal_lag + sunset_recovery
            #     print(f"[ENCLOSURE_TM] hours_sr={hours_sr:.2f}h  "
            #           f"overnight={overnight_heat:.2f}°C  lag={thermal_lag:.2f}°C  "
            #           f"net_adj={lw_temp_adjustment:.2f}°C")

            # ── Force shadow pixels if outside solar window ───────────────────────
            if timestamp < sunrise_time or timestamp > sunset_time:
                for d in DIRECTIONS:
                    shadow_data[d][t][:] = 0
                sun_visible = False
            else:
                # ── Sun visibility ────────────────────────────────────────────────
                sun_visible, visibility_reason = self.determine_sun_visibility_sophisticated(
                    shadow_data, sky_view_factor, zenith_angle, azimuth_angle,
                    cloud_cover, segmentation_data, t, location, date
                )
                if not sun_visible and visibility_reason in ["below_horizon", "very_low_sun"]:
                    for d in DIRECTIONS:
                        shadow_data[d][t][:] = 0

                if sky_view_factor < 0.03:
                    sun_visible = False
                    top_seg = segmentation_data.get("top")
                    if top_seg is not None:
                        tree_pct = np.sum(top_seg == 2) / top_seg.size * 100
                        if tree_pct <= 50:
                            for d in DIRECTIONS:
                                shadow_data[d][t][:] = 0
                    else:
                        for d in DIRECTIONS:
                            shadow_data[d][t][:] = 0

                # # Override with measured shade flag
                # sun_visible = (shade_value == 0)

            # ── Solar geometry ────────────────────────────────────────────────────
            gamma     = 90.0 - zenith_angle
            sin_gamma = max(0.0, np.sin(np.radians(gamma)))

            # ── Radiation scalars ─────────────────────────────────────────────────
            surface_projection_factor  = self.get_surface_projection_factor(gamma)
            print("surface_projection_factor: ", surface_projection_factor)
            # return -99
            relative_optical_air_mass  = self.get_relative_optical_air_mass(gamma, sin_gamma)
            optical_thickness          = self.get_optical_thickness(gamma, relative_optical_air_mass)
            vapor_pressure             = self.get_vapor_pressure(relative_humidity, air_temperature)
            atmospheric_pressure       = self.get_atmospheric_pressure(location["altitude"])
            extraterrestrial_radiation = self.get_extraterrestrial_radiation(date.timetuple().tm_yday)

            incoming_radiation_cloudless = self.get_incoming_radiation_cloudless(
                extraterrestrial_radiation, sin_gamma,
                optical_thickness, relative_optical_air_mass, atmospheric_pressure,
            )
            incoming_radiation       = self.get_incoming_radiation(incoming_radiation_cloudless, cloud_cover)
            global_radiation_cloudless = self.get_global_radiation_cloudless(
                extraterrestrial_radiation, sin_gamma, atmospheric_pressure
            )
            diffuse_radiation_cloudless = self.get_diffuse_radiation_cloudless(
                global_radiation_cloudless, extraterrestrial_radiation,
                incoming_radiation_cloudless, sin_gamma, sky_view_factor, sun_visible,
            )
            diffuse_radiation = self.get_diffuse_radiation(
                diffuse_radiation_cloudless,
                self.get_diffuse_radiation_overcast(global_radiation_cloudless, sky_view_factor),
                cloud_cover,
            )

            # ── Canopy transmissivity ─────────────────────────────────────────────
            # Called once here. Results (tau_direct, canopy_info) flow into
            # process_direction and compute_directional_shortwave_radiation below.
            tree_case, tree_fraction, tau_direct, canopy_info = self.compute_canopy_transmissivity(
                segmentation_data, solar_elevation_deg=gamma, folder_id=folder_id
            )
            if canopy_info["tree_fraction"] > 0.1:
                print(f"[CANOPY] tree={canopy_info['tree_fraction']:.1%}, "
                      f"gap={canopy_info['gap_fraction']:.2f}, "
                      f"LAI={canopy_info['LAI']:.2f}, τ={canopy_info['tau_direct']:.3f}")
                

            # ── Sail transmissivity (NEW) ──────────────────────────────────────────────
            sail_fraction, tau_sail, sail_info = self.compute_sail_transmissivity(
                segmentation_data, folder_id=folder_id
            )
            if sail_info.get("sail_fraction", 0) > 0.05:
                print(f"[SAIL] sail={sail_info['sail_fraction']:.1%}  "
                    f"tau_material={sail_info['tau_material']:.2f}  "
                    f"tau_eff={sail_info['tau_sail']:.3f}")
                
            # ── Combined effective tau for the MRT sensor point ────────────────────────
            # If both canopy AND sail are overhead, their attenuations multiply.
            # (rare but possible: a palm tree AND a sail both visible in "top" segmentation)
            tau_effective_for_sensor = tau_direct * tau_sail

            # ── Per-face sunlit fractions from shadow map ──────────────────────────────
            # shadow_data[d][t] tells us what fraction of each face is actually receiving
            # direct sun — independent of whether the SENSOR POINT is shaded.
            # Tree and sail pixels contribute partial direct irradiance via their tau values.
            face_sunlit_fractions = {}
            for d in DIRECTIONS:
                shadow = shadow_data[d][t]
                total  = shadow.size
                f_full = np.sum(shadow == self.SHADOW_SUNLIT) / total
                f_tree = np.sum(shadow == self.SHADOW_TREE)   / total
                f_sail = np.sum(shadow == self.SHADOW_SAIL)   / total
                # Effective sunlit fraction: full + attenuated partial contributions
                face_sunlit_fractions[d] = float(f_full
                                                + f_tree * tau_direct
                                                + f_sail * tau_sail)

            # ── Directional shortwave radiation ───────────────────────────────────────
            directional_sw, directional_sw_CR3 = self.compute_directional_shortwave_radiation(
                direct_horizontal_radiation=incoming_radiation,
                diffuse_radiation=diffuse_radiation,
                solar_elevation=gamma,
                solar_azimuth=azimuth_angle,
                sun_visible=sun_visible,
                sky_view_factor=sky_view_factor,
                segmentation_data=segmentation_data,
                sensor_heading=270.0,
                tau_direct=tau_effective_for_sensor,
                n_reflections=3,
                face_sunlit_fractions=face_sunlit_fractions,   # ← NEW
            )

            # ── Step 1: L_atm — single true-sky LW value ──────────────────────────
            # This is the only place get_atmospheric_radiation is called.
            # For open sites with a shade structure (awning/parasol) that the
            # enclosure classifier missed, we blend in structure emission here.
            # Semi/fully enclosed sites do NOT receive this correction — their
            # inter-surface radiation is handled entirely by G_ambient below.
            L_atm = self.get_atmospheric_radiation(air_temperature, vapor_pressure, cloud_cover)

            # overhead_coverage = self.detect_overhead_coverage(segmentation_data, sky_view_factor)
            # if overhead_coverage > 0.5 and enclosure_info["type"] == "open":
            #     structure_T_K  = air_temperature + 273.15 - 2
            #     structure_LW   = 0.9 * self.C_STEFAN_BOLTZMANN * structure_T_K**4
            #     L_atm = L_atm * (1.0 - overhead_coverage) + structure_LW * overhead_coverage
            #     if Config.debug_mode:
            #         print(f"[COVERAGE] Open-site overhead correction: L_atm={L_atm:.1f} W/m²")

            # ── Step 2: J_mean — mean enclosure radiosity ─────────────────────────
            # For open sites (alpha ≈ 0) J_mean is irrelevant — G_ambient collapses
            # to L_atm. We skip the expensive call to keep open-site cost low.
            J_mean = L_atm
            if enclosure_info["enclosure_fraction"] > 0.05:
                J_mean, _ = self.compute_enclosure_mean_radiosity(
                    segmentation_data, air_temperature, t,
                    lw_temp_adjustment=lw_temp_adjustment,
                    surface_temperature_data=surface_temperature_data,
                    L_atm=L_atm,                                            # ← add this
                    enclosure_fraction=enclosure_info["enclosure_fraction"]
                )

            # ── Step 3: G_ambient — unified irradiation seen by every surface pixel
            # Incropera Table 12.1: J = ε·σ·T⁴ + (1−ε)·G
            # G_ambient IS that G — the only quantity that differs between site types.
            #
            # Boundary conditions (Scott's validation requirement):
            #   alpha = 0 (open)     → G_ambient = L_atm   ✓
            #   alpha = 1 (enclosed) → G_ambient = J_mean  ✓
            alpha     = enclosure_info["enclosure_fraction"]
            G_ambient = (1.0 - alpha) * L_atm + alpha * J_mean

            if Config.debug_mode:
                if alpha < 0.05:
                    diff = abs(G_ambient - L_atm)
                    print(f"[BC_CHECK] Open site: G_ambient={G_ambient:.1f} L_atm={L_atm:.1f} "
                          f"diff={diff:.2f} W/m² {'PASS' if diff < 1.0 else 'FAIL'}")
                if alpha > 0.90:
                    diff = abs(G_ambient - J_mean)
                    print(f"[BC_CHECK] Enclosed: G_ambient={G_ambient:.1f} J_mean={J_mean:.1f} "
                          f"diff={diff:.2f} W/m² {'PASS' if diff < 5.0 else 'FAIL'}")

            print(f"[LW] L_atm={L_atm:.1f}  J_mean={J_mean:.1f}  "
                  f"G_ambient={G_ambient:.1f}  alpha={alpha:.2f}  W/m²")

            # ── Step 4: process all six directions in parallel ────────────────────
            # Every direction receives the same L_atm and G_ambient.
            # Inside process_direction:
            #   E_d[sky]     = L_atm                           (sky pixels ARE the atmosphere)
            #   E_d[surface] = ε·σ·T⁴ + (1−ε)·G_ambient       (Incropera Eq. 12.1)
            #   q_net        = α_body·SW + G_ambient − E_d      (net energy balance)
            #   T_s[t]       = T_air + (q_net + Qg) / h_eff    (surface temperature)
            with ThreadPoolExecutor(max_workers=min(6, len(DIRECTIONS))) as executor:
                futures = [
                    executor.submit(
                        self.process_direction,
                        d, t, Q0, Q1, surface_temperature_data, segmentation_data,
                        shadow_data, E, Qg, tlayer, thickness,
                        air_temperature, wind_velocity,
                        relative_humidity,
                        incoming_radiation, diffuse_radiation,
                        L_atm, G_ambient,
                        minute_delta, n_pixels, folder_id, location,
                        tau_direct=tau_direct,
                        gap_fraction=canopy_info['gap_fraction'],
                        tau_sail=tau_sail,
                    )
                    for d in DIRECTIONS
                ]
                for future in futures:
                    d, E_d, Qg_d, surface_temp, image_params = future.result()
                    E[d]   = E_d
                    Qg[d]  = Qg_d
                    surface_temperature_data[d][t] = surface_temp
                    self.image_queue.put(image_params)

            #     # ── Step 4b: fully-enclosed E[d] overwrite ────────────────────────────
            #     # For fully enclosed sites, E[d] from process_direction is computed
            #     # using G_ambient (which was derived from J_mean, which used prev surface
            #     # temps that themselves were computed with G_ambient). This tight feedback
            #     # loop causes J_mean to collapse or diverge.
            #     #
            #     # Fix: recompute E[d] here using fixed air-temp offsets (surface_temperature_data=None)
            #     # to break the loop. The energy balance in process_direction is still used
            #     # for surface temperature evolution (Qg, tlayer, thermal mass) — we only
            #     # replace the LW maps that feed into MRT computation.
            #     if enclosure_info["type"] == "fully_enclosed" or enclosure_info["type"] == "fully_enclosed_tree":
            #         enc_lw_maps, J_mean_enc = self.compute_enclosed_longwave_maps(
            #             segmentation_data=segmentation_data,
            #             surface_temperature_data=None,   # ← fixed offsets: breaks feedback loop
            #             L_atm=L_atm,
            #             air_temperature=air_temperature,
            #             enclosure_info=enclosure_info,
            #             t=t,
            #             lw_temp_adjustment=lw_temp_adjustment,
            #         )
            #         for d in DIRECTIONS:
            #             if d in enc_lw_maps:
            #                 E[d] = enc_lw_maps[d]

            #         print(f"[FULLY_ENC] E[d] overwritten with stable enclosure LW  "
            #             f"J_mean={J_mean_enc:.1f} W/m²")

            # # ── Step 5: semi-enclosed roof correction ─────────────────────────────
            # # The shadow map marks overhead building pixels as shaded (correct from
            # # the interior perspective), so the conduction model never sees exterior
            # # solar forcing on the roof. We correct the interior face temperature
            # # using a steady-state outside surface heat balance:
            # #   α_SW·G_dir = (h_conv + h_rad)·ΔT  (EnergyPlus Engineering Ref., 2024)
            # # The resulting additional LW is an additive delta on E["top"] only.
            # # This is the ONLY place the roof correction is applied.
            # if enclosure_info["type"] == "semi_enclosed":
            #     top_seg = segmentation_data.get("top")
            #     if top_seg is not None:
            #         building_fraction = np.sum(top_seg == 3) / top_seg.size
            #         if building_fraction > 0.05:
            #             emissivity_roof = self.SURFACE_EMISSIVITY.get(3, 0.90)
            #             T_mean_K = air_temperature + 273.15
            #             h_rad    = 4.0 * emissivity_roof * self.C_STEFAN_BOLTZMANN * T_mean_K**3
            #             h_conv   = 5.6 + 3.9 * wind_velocity   # Ito/ASHRAE Ch.26
            #             h_total  = h_conv + h_rad
            #             roof_T_C = air_temperature + (self.C_SW_ABSORPTION_ROOF / h_total) * incoming_radiation
            #             LW_roof  = emissivity_roof * self.C_STEFAN_BOLTZMANN * (roof_T_C + 273.15)**4
            #             delta_LW = LW_roof - L_atm
            #             added_LW = building_fraction * delta_LW
            #             E["top"] = E["top"] + added_LW
            #             print(f"[SEMI_ENC_ROOF] frac={building_fraction:.2f}  "
            #                   f"T_roof={roof_T_C:.1f}°C  "
            #                   f"LW_roof={LW_roof:.1f}  added={added_LW:.1f} W/m²")

            # ── Step 6: MRT ───────────────────────────────────────────────────────
            avg_dsw_by_dir = np.zeros(6)
            avg_lw_by_dir  = np.zeros(6)
            self.compute_average_radiation_for_each_direction(
                n_pixels, diffuse_radiation, E,
                ring_indices_by_fisheye_subset, fractions_by_fisheye_subset,
                avg_dsw_by_dir, avg_lw_by_dir
            )

            # Reorder from internal [front,right,back,left,top,bottom]
            # to CR3000 convention   [left, right, front, back, up, down]
            avg_dsw_CR3 = [
                avg_dsw_by_dir[3], avg_dsw_by_dir[1],
                avg_dsw_by_dir[0], avg_dsw_by_dir[2],
                avg_dsw_by_dir[4], avg_dsw_by_dir[5]
            ]
            avg_lw_CR3 = [
                avg_lw_by_dir[3], avg_lw_by_dir[1],
                avg_lw_by_dir[0], avg_lw_by_dir[2],
                avg_lw_by_dir[4], avg_lw_by_dir[5]
            ]

            measured_sw_CR3 = [sw_left, sw_right, sw_front, sw_back, sw_top, sw_bottom]
            measured_lw_CR3 = [lw_left, lw_right, lw_front, lw_back, lw_top, lw_bottom]

            mrt_values = self.compute_multiple_mrts(
                sensor_sw=measured_sw_CR3,
                sensor_lw=measured_lw_CR3,
                calc_sw=directional_sw_CR3,
                calc_lw=avg_lw_CR3,
                air_temperature=air_temperature,
                wind_velocity=wind_velocity
            )

            mrt_gt = measurements["mrt_gt"][t] if t < len(measurements["mrt_gt"]) else "N/A"

            print(f"[MRT] GT={mrt_gt}  "
                  f"Sensors={mrt_values['sensors_data']:.2f}  "
                  f"CalcSW+SensorLW={mrt_values['calc_sw_sensor_lw']:.2f}  "
                  f"SensorSW+CalcLW={mrt_values['sensor_sw_calc_lw']:.2f}  "
                  f"CalcSW+CalcLW={mrt_values['calc_sw_calc_lw']:.2f}  °C")
            print(f"[LW] Calc:    {[f'{x:.1f}' for x in avg_lw_CR3]}")
            print(f"[LW] Sensor:  {[f'{x:.1f}' for x in measured_lw_CR3]}")


            thermal_indices = self.compute_thermal_indices(
                ta=air_temperature, tmrt=mrt_values["calc_sw_calc_lw"],
                va=wind_velocity, va_10m=wind_velocity_10m, rh=relative_humidity,
                pressure=atmospheric_pressure, met=80.0, icl=0.9,
            )
            print(f"[UTCI] {thermal_indices['utci']:.2f} °C  ({thermal_indices['utci_category']})")
            print(f"[PET]  {thermal_indices['pet']:.2f} °C  ({thermal_indices['pet_category']})")

            # ── Step 7: write CSV row ─────────────────────────────────────────────
            csv_file.write(
                f"{local_times[t]},{folder_id},{air_temperature},{relative_humidity},"
                f"{wind_velocity},{cloud_cover},"
                f"{sky_view_factor},{svf_gt},{sun_visible},{surface_projection_factor},"
                f"{extraterrestrial_radiation},{atmospheric_pressure},"
                f"{relative_optical_air_mass},{optical_thickness},{vapor_pressure},"
                f"{incoming_radiation},{global_radiation_cloudless},{diffuse_radiation},"
                f"{measured_lw_CR3[0]:.2f},{measured_lw_CR3[1]:.2f},{measured_lw_CR3[2]:.2f},"
                f"{measured_lw_CR3[3]:.2f},{measured_lw_CR3[4]:.2f},{measured_lw_CR3[5]:.2f},"
                f"{measured_sw_CR3[0]:.2f},{measured_sw_CR3[1]:.2f},{measured_sw_CR3[2]:.2f},"
                f"{measured_sw_CR3[3]:.2f},{measured_sw_CR3[4]:.2f},{measured_sw_CR3[5]:.2f},"
                f"{avg_lw_CR3[0]:.2f},{avg_lw_CR3[1]:.2f},{avg_lw_CR3[2]:.2f},"
                f"{avg_lw_CR3[3]:.2f},{avg_lw_CR3[4]:.2f},{avg_lw_CR3[5]:.2f},"
                f"{directional_sw_CR3[0]:.2f},{directional_sw_CR3[1]:.2f},"
                f"{directional_sw_CR3[2]:.2f},{directional_sw_CR3[3]:.2f},"
                f"{directional_sw_CR3[4]:.2f},{directional_sw_CR3[5]:.2f},"
                f"{mrt_gt},{mrt_values['sensors_data']:.2f},"
                f"{mrt_values['calc_sw_sensor_lw']:.2f},"
                f"{mrt_values['sensor_sw_calc_lw']:.2f},"
                f"{mrt_values['calc_sw_calc_lw']:.2f},"
                f"{thermal_indices['utci']:.2f},{thermal_indices['utci_category']},"
                f"{thermal_indices['pet']:.2f},{thermal_indices['pet_category']}\n"
            )
            csv_file.flush()

        # ── Cleanup ───────────────────────────────────────────────────────────────
        self.image_queue.join()
        self.image_queue.put(None)
        if self.image_thread:
            self.image_thread.join()

        csv_file.close()
        return 1
    


    # All other methods remain the same (determine_sun_visibility_sophisticated, helper functions, etc.)
    # I'm including them here for completeness but without changes

    def determine_sun_visibility_sophisticated(
        self, 
        shadow_data, 
        sky_view_factor, 
        zenith_angle, 
        azimuth_angle, 
        cloud_cover,
        segmentation_data,
        t,
        location,
        date
    ):
        """Sophisticated sun visibility determination using multiple criteria"""
        elevation_angle = 90.0 - zenith_angle
        
        if elevation_angle <= 0:
            print(f"[SUN_VIS] Sun below horizon (elevation: {elevation_angle:.1f}°)")
            return False, "below_horizon"
        
        if elevation_angle < 5:
            print(f"[SUN_VIS] Very low sun (elevation: {elevation_angle:.1f}°)")
            return False, "very_low_sun"
        
        if cloud_cover > 0.8:
            if elevation_angle > 45:
                cloud_factor = 0.3
            elif elevation_angle > 25:
                cloud_factor = 0.1
            else:
                cloud_factor = 0.0
                
            if np.random.random() > cloud_factor:
                print(f"[SUN_VIS] Blocked by heavy clouds (cover: {cloud_cover:.2f})")
                return False, "heavy_clouds"
        
        min_svf_for_sun = max(0.1, 0.3 - (elevation_angle / 90.0) * 0.2)
        
        if sky_view_factor < min_svf_for_sun:
            print(f"[SUN_VIS] Insufficient sky view (SVF: {sky_view_factor:.3f} < {min_svf_for_sun:.3f})")
            return False, "low_sky_view"
        
        sun_direction_sky_available = self._check_sky_in_sun_direction(
            segmentation_data, zenith_angle, azimuth_angle
        )
        
        if not sun_direction_sky_available:
            print(f"[SUN_VIS] Sky blocked in sun direction (zenith: {zenith_angle:.1f}°, azimuth: {azimuth_angle:.1f}°)")
            return False, "sky_blocked_in_sun_direction"
        
        sun_visible, shadow_reason = self._analyze_shadows_adaptive(
            shadow_data, zenith_angle, azimuth_angle, sky_view_factor, elevation_angle, t
        )
        
        if not sun_visible:
            print(f"[SUN_VIS] Shadow analysis failed: {shadow_reason}")
            return False, f"shadow_analysis_{shadow_reason}"
        
        expected_irradiance = self._calculate_expected_clear_sky_irradiance(elevation_angle, location)
        irradiance_threshold = expected_irradiance * 0.3
        
        temporal_consistency = self._check_temporal_consistency(t, elevation_angle)
        
        if not temporal_consistency:
            print(f"[SUN_VIS] Failed temporal consistency check")
            return False, "temporal_inconsistency"
        
        print(f"[SUN_VIS] Sun visible (elevation: {elevation_angle:.1f}°, clouds: {cloud_cover:.2f}, SVF: {sky_view_factor:.3f})")
        return True, "visible"

    def _check_sky_in_sun_direction(self, segmentation_data, zenith_angle, azimuth_angle):
        """Check if sky is available in the direction of the sun using segmentation data."""
        try:
            top_seg = segmentation_data.get("top")
            if top_seg is not None:
                center_x, center_y = 256, 256
                
                max_radius = min(center_x, center_y) * 0.8
                radius = (zenith_angle / 90.0) * max_radius
                
                azimuth_rad = np.radians(azimuth_angle - 90)
                
                sun_x = int(center_x + radius * np.cos(azimuth_rad))
                sun_y = int(center_y + radius * np.sin(azimuth_rad))
                
                if 0 <= sun_x < 512 and 0 <= sun_y < 512:
                    region_size = 20
                    x_start = max(0, sun_x - region_size//2)
                    x_end = min(512, sun_x + region_size//2)
                    y_start = max(0, sun_y - region_size//2)
                    y_end = min(512, sun_y + region_size//2)
                    
                    sun_region = top_seg[y_start:y_end, x_start:x_end]
                    sky_pixels = np.sum(sun_region == 1)
                    total_pixels = sun_region.size
                    
                    sky_fraction = sky_pixels / total_pixels if total_pixels > 0 else 0
                    
                    print(f"[SKY_CHECK] Sun region sky fraction: {sky_fraction:.3f}")
                    return sky_fraction > 0.5
            
            return True
            
        except Exception as e:
            print(f"[SKY_CHECK] Error checking sky in sun direction: {e}")
            return True

    def _analyze_shadows_adaptive(self, shadow_data, zenith_angle, azimuth_angle, sky_view_factor, elevation_angle, t):
        """Adaptive shadow analysis that considers sun position and site characteristics."""
        try:
            bottom_shadow = shadow_data["bottom"][t]
            
            if elevation_angle > 60:
                region_size = 80
            elif elevation_angle > 30:
                region_size = 100
            else:
                region_size = 120
            
            center = 256
            start = center - region_size // 2
            end = center + region_size // 2
            
            regions = {
                "center": (start, end, start, end),
                "north": (start, end, start-50, start),
                "south": (start, end, end, end+50),
                "east": (end, end+50, start, end),
                "west": (start-50, start, start, end)
            }
            
            region_results = {}
            
            for region_name, (x1, x2, y1, y2) in regions.items():
                x1, x2 = max(0, x1), min(512, x2)
                y1, y2 = max(0, y1), min(512, y2)
                
                if x2 > x1 and y2 > y1:
                    region_shadow = bottom_shadow[y1:y2, x1:x2]
                    shaded_pixels = np.sum(region_shadow == 0)
                    total_pixels = region_shadow.size
                    shade_fraction = shaded_pixels / total_pixels if total_pixels > 0 else 0
                    
                    region_results[region_name] = {
                        "shaded_pixels": shaded_pixels,
                        "total_pixels": total_pixels,
                        "shade_fraction": shade_fraction
                    }
            
            base_threshold = 0.7
            svf_adjustment = (sky_view_factor - 0.1) * 0.3
            elevation_adjustment = (elevation_angle / 90.0) * 0.2
            
            final_threshold = max(0.3, min(0.9, base_threshold - svf_adjustment - elevation_adjustment))
            
            print(f"[SHADOW] Adaptive threshold: {final_threshold:.3f} (base: {base_threshold}, SVF adj: {svf_adjustment:.3f}, elev adj: {elevation_adjustment:.3f})")
            
            center_shade = region_results.get("center", {}).get("shade_fraction", 0)
            
            if center_shade > final_threshold:
                adjacent_regions = ["north", "south", "east", "west"]
                min_adjacent_shade = min([region_results.get(r, {}).get("shade_fraction", 1) for r in adjacent_regions])
                
                if min_adjacent_shade < final_threshold * 0.8:
                    print(f"[SHADOW] Center shaded ({center_shade:.3f}) but adjacent clear ({min_adjacent_shade:.3f})")
                    return True, "partial_shade_but_adjacent_clear"
                else:
                    print(f"[SHADOW] All regions heavily shaded (center: {center_shade:.3f})")
                    return False, "all_regions_shaded"
            else:
                print(f"[SHADOW] Center region adequately clear ({center_shade:.3f} < {final_threshold:.3f})")
                return True, "center_clear"
                
        except Exception as e:
            print(f"[SHADOW] Error in adaptive shadow analysis: {e}")
            return False, "analysis_error"

    def _calculate_expected_clear_sky_irradiance(self, elevation_angle, location):
        """Calculate expected clear sky irradiance for validation."""
        try:
            air_mass = 1.0 / max(0.01, np.sin(np.radians(elevation_angle)))
            dni_clear = 900 * np.exp(-0.7 * air_mass)
            ghi_expected = dni_clear * np.sin(np.radians(elevation_angle)) + 100
            return max(0, ghi_expected)
        except Exception as e:
            print(f"[IRRADIANCE] Error calculating expected irradiance: {e}")
            return 0

    def _check_temporal_consistency(self, t, elevation_angle):
        """Check temporal consistency to avoid rapid sun visibility changes."""
        try:
            if not hasattr(self, '_sun_visibility_history'):
                self._sun_visibility_history = []
            
            if len(self._sun_visibility_history) < 3:
                return True
            
            recent_states = self._sun_visibility_history[-3:]
            recent_visible_count = sum(recent_states)
            
            if elevation_angle < 10 and recent_visible_count == 0:
                return True
            
            if elevation_angle > 30 and recent_visible_count >= 2:
                return True
            
            return True
            
        except Exception as e:
            print(f"[TEMPORAL] Error in temporal consistency check: {e}")
            return True

    def create_seg_image(self, segmentation_data, location, direction, n_pixels, folder_id):
        dir_name = f"./output/{folder_id}/validation_seg_images/"
        os.makedirs(dir_name, exist_ok=True)
        image_file_name = f"{dir_name}/seg_{direction}.png"

        # Vectorized color lookup — no loops at all
        color_map_array = np.array([
            [255, 255, 255],  # 0: background
            [0,   0,   255],  # 1: sky
            [0,   255, 0  ],  # 2: tree
            [192, 192, 192],  # 3: building
            [128, 128, 128],  # 4: impervious
            [255, 255, 0  ],  # 5: pervious
            [255, 0,   255],  # 6: moving objects
            [0,   255, 255],  # 7: shade sail
        ], dtype=np.uint8)

        safe_seg = np.clip(segmentation_data, 0, 7)
        rgb = color_map_array[safe_seg]
        Image.fromarray(rgb).save(image_file_name)
        print(f"Segmentation image saved as {image_file_name}")

    def sky_mask_default(self, segmentation_image):
        """Generate a binary sky mask from a segmentation image where 1 represents sky."""
        if segmentation_image is None or not isinstance(segmentation_image, np.ndarray):
            print("[ERROR] sky_mask: Received None or invalid image format")
            return np.zeros((512, 512), dtype=np.uint8)

        if segmentation_image.size == 0:
            print("[ERROR] sky_mask: Received an empty image")
            return np.zeros((512, 512), dtype=np.uint8)

        if segmentation_image.shape[:2] != (512, 512):
            print(f"[INFO] Resizing from {segmentation_image.shape[:2]} to (512,512)")
            segmentation_resized = cv2.resize(segmentation_image, (512, 512), interpolation=cv2.INTER_NEAREST)
        else:
            segmentation_resized = segmentation_image.copy()

        sky_mask = (segmentation_resized == 1).astype(np.uint8)

        return sky_mask

    def compute_sky_view_factor_default(
        self,
        n_rings,
        segmented_images,
        fraction_bottom_data,
        fraction_center_data,
        ring_indices_bottom,
        ring_indices_center,
        projection_type
    ):
        """Compute the Sky View Factor (SVF) using preprocessed segmented images."""
        fraction_bottom_data = np.clip(fraction_bottom_data, 0, 1).flatten()
        fraction_center_data = np.clip(fraction_center_data, 0, 1).flatten()
        
        ring_indices_bottom = np.clip(ring_indices_bottom, 0, n_rings - 1).astype(np.int32).flatten()
        ring_indices_center = np.clip(ring_indices_center, 0, n_rings - 1).astype(np.int32).flatten()

        n_pixels = len(ring_indices_bottom)  
        
        if len(fraction_bottom_data) != n_pixels or len(fraction_center_data) != n_pixels:
            print(f"[ERROR] Fraction data size mismatch")
            return 0.5
        
        if len(segmented_images) != 5:
            print(f"[ERROR] Expected 5 segmented images, but got {len(segmented_images)}")
            return 0.5
        
        ring_total = np.zeros(n_rings, dtype=float)
        ring_sky = np.zeros(n_rings, dtype=float)

        directions = ["front", "right", "back", "left", "top"]
        sky_masks = [self.sky_mask_default(img) for img in segmented_images]

        # for d, (segmentation, mask) in enumerate(zip(segmented_images, sky_masks)):
        #     if segmentation is None:
        #         continue

        #     segmentation = segmentation.flatten()  
        #     mask = mask.flatten()

        #     ring_indices = ring_indices_bottom if d < 4 else ring_indices_center
        #     fraction = fraction_bottom_data if d < 4 else fraction_center_data

        #     min_size = min(len(segmentation), len(ring_indices), len(fraction))
            
        #     for i in range(min_size):
        #         f = float(fraction[i])
        #         if f < 0:
        #             continue

        #         ring_index = int(ring_indices[i])
        #         if 0 <= ring_index < n_rings:
        #             ring_total[ring_index] += f
        #             if mask[i] == 1:
        #                 ring_sky[ring_index] += f

        for d, (segmentation, mask) in enumerate(zip(segmented_images, sky_masks)):
            if segmentation is None:
                continue

            segmentation = segmentation.flatten()
            mask = mask.flatten()

            ring_indices = ring_indices_bottom if d < 4 else ring_indices_center
            fraction = fraction_bottom_data if d < 4 else fraction_center_data

            min_size = min(len(segmentation), len(ring_indices), len(fraction))
            ri = ring_indices[:min_size]
            fr = fraction[:min_size]
            mk = mask[:min_size]

            # Vectorized — replaces the entire for loop
            valid = (fr >= 0) & (ri >= 0) & (ri < n_rings)
            np.add.at(ring_total, ri[valid], fr[valid])
            sky_valid = valid & (mk == 1)
            np.add.at(ring_sky, ri[sky_valid], fr[sky_valid])

        svf = 0.0
        
        if projection_type == 'angular':
            temp = n_rings / np.pi
            for i in range(n_rings):
                if ring_total[i] > 0:
                    weight = np.sin((i + 0.5) / temp)
                    svf += weight * (ring_sky[i] / ring_total[i])
            svf *= np.pi / (2 * n_rings)
            
        elif projection_type == 'cosine':
            for i in range(n_rings):
                if ring_total[i] > 0:
                    theta_mid = (i + 0.5) / n_rings * (np.pi / 2)
                    weight = np.cos(theta_mid)
                    svf += weight * (ring_sky[i] / ring_total[i])
            svf *= 2 / n_rings
            
        elif projection_type == 'equiangular':
            for i in range(n_rings):
                if ring_total[i] > 0:
                    theta_start = i / n_rings * (np.pi / 2)
                    theta_end = (i + 1) / n_rings * (np.pi / 2)
                    
                    solid_angle = np.cos(theta_start) - np.cos(theta_end)
                    sky_fraction = ring_sky[i] / ring_total[i]
                    svf += solid_angle * sky_fraction
            
        else:
            print(f"[ERROR] Unknown projection type: {projection_type}")
            return 0.5

        print(f"[Debug] Computed {projection_type} SVF: {svf:.6f}")
        return svf

    def preprocess_fisheye_segmentation(self, image):
        """Extracts the sky mask from a segmentation fisheye image."""
        if image.shape[:2] != (512, 512):
            print(f"[INFO] Resizing from {image.shape[:2]} to (512,512)")
            image_resized = cv2.resize(image, (512, 512), interpolation=cv2.INTER_NEAREST)
        else:
            image_resized = image.copy()

        if image.shape[-1] == 3:
            print("[INFO] Converting 3-channel RGB to 4-channel RGBA")
            alpha_channel = np.full((512, 512, 1), 255, dtype=np.uint8)
            image_resized = np.concatenate([image_resized, alpha_channel], axis=-1)
        
        SKY_COLOR_BGRA = np.array([255, 0, 0, 255])

        sky_mask = np.all(image_resized == SKY_COLOR_BGRA, axis=-1).astype(np.uint8)

        return sky_mask, image_resized

    def compute_sky_view_factor_angular(self, sky_mask, original_fisheye, n_rings=N_RINGS, show_plot_svf=False):
        """Computes the Sky View Factor (SVF) using rings and angular weighting."""
        if sky_mask.shape != (512, 512):
            raise ValueError(f"Expected 512x512 sky mask, got {sky_mask.shape}")

        y, x = np.indices((512, 512))
        cx, cy = 256, 256
        r = np.sqrt((x - cx) ** 2 + (y - cy) ** 2)
        r_norm = (r / 256) * n_rings
        r_indices = np.clip(r_norm.astype(np.int32), 0, n_rings - 1)

        ring_total = np.zeros(n_rings, dtype=float)
        ring_sky = np.zeros(n_rings, dtype=float)

        for i in range(n_rings):
            ring_mask = (r_indices == i)
            ring_total[i] = np.sum(ring_mask)
            ring_sky[i] = np.sum(sky_mask[ring_mask])

        svf = 0.0
        temp = n_rings / np.pi

        for i in range(n_rings):
            if ring_total[i] > 0:
                weight = np.sin((i + 0.5) / temp)
                svf += weight * (ring_sky[i] / ring_total[i])
            else:
                print(f"[Warning] ring_total[{i}] is zero, skipping division.")

        svf *= np.pi / (2 * n_rings)

        print(f"[Debug] Computed SVF: {svf:.6f}")

        if show_plot_svf :
            plt.figure(figsize=(13, 4))

            plt.subplot(1, 3, 1)
            plt.imshow(cv2.cvtColor(original_fisheye, cv2.COLOR_BGRA2RGBA))
            plt.title("Original Fisheye Segmentation")
            plt.axis("off")

            plt.subplot(1, 3, 2)
            plt.imshow(sky_mask, cmap='Blues', origin='upper')
            plt.title("Sky Mask (Extracted)")
            plt.axis("off")

            plt.subplot(1, 3, 3)
            plt.plot(range(n_rings), ring_sky / (ring_total + 1e-6), marker='o', color='blue')
            plt.xlabel("Ring Index")
            plt.ylabel("Sky Fraction")
            plt.title("Sky Fraction per Ring")
            plt.grid(True)

            plt.show()

        return svf
    
    def compute_sky_view_factor_equiangular(self, sky_mask, original_fisheye, n_rings=N_RINGS, show_plot_svf=False):
        """SVF calculation for true equiangular projection (scientifically correct)."""
        if sky_mask.shape != (512, 512):
            raise ValueError(f"Expected 512x512 sky mask, got {sky_mask.shape}")
        
        y, x = np.indices((512, 512))
        cx, cy = 256, 256
        r = np.sqrt((x - cx) ** 2 + (y - cy) ** 2)
        
        fisheye_mask = r <= 256
        
        zenith_angles = (r / 256) * (np.pi / 2)
        zenith_angles = np.clip(zenith_angles, 0, np.pi / 2)
        
        theta_i = (zenith_angles / (np.pi / 2)) * n_rings
        r_indices = np.clip(theta_i.astype(np.int32), 0, n_rings - 1)
        
        ring_total = np.zeros(n_rings, dtype=float)
        ring_sky = np.zeros(n_rings, dtype=float)
        
        for i in range(n_rings):
            ring_mask = (r_indices == i) & fisheye_mask
            ring_total[i] = np.sum(ring_mask)
            ring_sky[i] = np.sum(sky_mask[ring_mask])
        
        svf = 0.0
        for i in range(n_rings):
            if ring_total[i] > 0:
                theta_start = i / n_rings * (np.pi / 2)
                theta_end = (i + 1) / n_rings * (np.pi / 2)
                
                solid_angle = np.cos(theta_start) - np.cos(theta_end)
                sky_fraction = ring_sky[i] / ring_total[i]
                svf += solid_angle * sky_fraction
        
        print(f"[Debug] Scientifically Computed SVF: {svf:.6f}")
        
        return svf
    
    def compute_sky_view_factor_cosine(self, sky_mask, original_fisheye, n_rings=N_RINGS, show_plot_svf=False):
        """Computes the Sky View Factor (SVF) using cosine-weighted rings."""
        if sky_mask.shape != (512, 512):
            raise ValueError(f"Expected 512x512 sky mask, got {sky_mask.shape}")

        y, x = np.indices((512, 512))
        cx, cy = 256, 256
        r = np.sqrt((x - cx) ** 2 + (y - cy) ** 2)

        zenith_angles = np.arctan2(r, 256)
        theta_i = (zenith_angles / (np.pi / 2)) * n_rings
        r_indices = np.clip(theta_i.astype(np.int32), 0, n_rings - 1)

        ring_total = np.zeros(n_rings, dtype=float)
        ring_sky = np.zeros(n_rings, dtype=float)

        for i in range(n_rings):
            ring_mask = (r_indices == i)
            ring_total[i] = np.sum(ring_mask)
            ring_sky[i] = np.sum(sky_mask[ring_mask])

        svf = 0.0
        for i in range(n_rings):
            if ring_total[i] > 0:
                theta_mid = (i + 0.5) / n_rings * (np.pi / 2)
                weight = np.cos(theta_mid)
                svf += weight * (ring_sky[i] / (ring_total[i] + 1e-6))

        svf *= 2 / n_rings

        if Config.debug_mode:
            print(f"[Debug] Computed Cosine-Weighted SVF: {svf:.6f}")

        if show_plot_svf:
            plt.figure(figsize=(13, 4))

            plt.subplot(1, 3, 1)
            plt.imshow(cv2.cvtColor(original_fisheye, cv2.COLOR_BGRA2RGBA))
            plt.title("Original Fisheye Segmentation")
            plt.axis("off")

            plt.subplot(1, 3, 2)
            plt.imshow(sky_mask, cmap='Blues', origin='upper')
            plt.title("Sky Mask (Extracted)")
            plt.axis("off")

            plt.subplot(1, 3, 3)
            theta_values = [(i + 0.5) / n_rings * (np.pi / 2) for i in range(n_rings)]
            sky_fractions = ring_sky / (ring_total + 1e-6)
            cosine_weights = np.cos(theta_values)

            plt.plot(theta_values, sky_fractions, marker='o', color='blue', label="Sky Fraction")
            plt.plot(theta_values, cosine_weights, linestyle="--", color="red", label="Cosine Weighting")
            plt.xlabel("Zenith Angle (radians)")
            plt.ylabel("Value")
            plt.title("Sky Fraction & Cosine Weighting")
            plt.legend()
            plt.grid(True)

            plt.show()

        return svf

    def process_segmentation_fisheye(self, segmentation_fisheye_files, projection_type):
        """Loads segmentation fisheye images, extracts the sky mask, and computes SVF."""
        svf_results = {}

        for direction, file_path in segmentation_fisheye_files.items():
            if direction != "top":
                continue

            image = cv2.imread(file_path, cv2.IMREAD_UNCHANGED)
            if image is None:
                print(f"[ERROR] Could not load {file_path}")
                continue

            sky_mask, original_fisheye = self.preprocess_fisheye_segmentation(image)

            if projection_type == 'cosine':
                svf = self.compute_sky_view_factor_cosine(sky_mask, original_fisheye, n_rings=self.N_RINGS, show_plot_svf=False)
            elif projection_type == 'angular':
                svf = self.compute_sky_view_factor_angular(sky_mask, original_fisheye, n_rings=self.N_RINGS, show_plot_svf=False)
            elif projection_type == 'equiangular':
                svf = self.compute_sky_view_factor_equiangular(sky_mask, original_fisheye, n_rings=self.N_RINGS, show_plot_svf=True)
            
            print(f"[INFO] Computed SVF for {direction}: {svf:.6f}")

            svf_results[direction] = svf

        return svf_results

    def init_csv(csv_path, config):
        """Initialize a CSV file with appropriate headers based on configuration."""
        try:
            with open(csv_path, mode='w', newline='') as csv_file:
                csv_writer = csv.writer(csv_file)

                headers = ["Time"]

                if config.get("MRT_OUTPUT_MEASUREMENTS"):
                    headers.extend(["AirTemperature", "RelativeHumidity", "WindVelocity", "CloudCover"])
                if config.get("MRT_OUTPUT_SVF"):
                    headers.append("SVF")
                if config.get("MRT_OUTPUT_SUN"):
                    headers.append("SunVisible")
                if config.get("MRT_OUTPUT_SPF"):
                    headers.append("SurfaceProjectionFactor")
                if config.get("MRT_OUTPUT_E_R"):
                    headers.append("ExtraterrestrialRadiation")
                if config.get("MRT_OUTPUT_ATMOSPHERIC_P"):
                    headers.append("AtmosphericPressure")
                if config.get("MRT_OUTPUT_ROAM"):
                    headers.append("RelativeOpticalAirMass")
                if config.get("MRT_OUTPUT_OT"):
                    headers.append("OpticalThickness")
                if config.get("MRT_OUTPUT_VAPOR_P"):
                    headers.append("VaporPressure")
                if config.get("MRT_OUTPUT_A_R"):
                    headers.append("AtmosphericRadiation")
                if config.get("MRT_OUTPUT_I_R"):
                    headers.append("IncomingRadiation")
                if config.get("MRT_OUTPUT_G_R"):
                    headers.append("GlobalRadiationCloudless")
                if config.get("MRT_OUTPUT_D_R"):
                    headers.append("DiffuseRadiation")
                if config.get("MRT_OUTPUT_A_DSW_R"):
                    headers.extend(["ADSW_N", "ADSW_E", "ADSW_S", "ADSW_W", "ADSW_U", "ADSW_D"])
                if config.get("MRT_OUTPUT_A_LW_R"):
                    headers.extend(["ALW_N", "ALW_E", "ALW_S", "ALW_W", "ALW_U", "ALW_D"])
                if config.get("MRT_OUTPUT_B"):
                    headers.append("Qg")
                if config.get("MRT_OUTPUT_MRFD"):
                    headers.append("MeanRadiantFluxDensity")

                headers.append("MRT")

                csv_writer.writerow(headers)

            print(f"CSV file initialized with path: {csv_path}")
            return True
        except Exception as e:
            print(f"ERROR: Unable to initialize CSV file at '{csv_path}'. Exception: {e}")
            return False
        
    def create_temperature_validation_image(
        self,
        surface_temperature,
        segmentation_data,
        location,
        direction,
        timestep,
        folder_id,
        air_temperature,
        t_min_global: float = 20.0,   # fixed cold end [°C] — constant across ALL timesteps
        t_max_global: float = 70.0,   # fixed hot end  [°C] — constant across ALL timesteps
        save_npy: bool = True,        # also write raw surface-temperature array
    ):
        """
        Save a FLIR-iron thermal image and (optionally) the raw surface temperature
        array for each timestep.

        Thermal camera colour convention (FLIR iron palette, cold→hot):
            black/purple → blue → cyan → green → yellow → orange → red → white

        Using a FIXED global temperature range [t_min_global, t_max_global] means
        the same colour always maps to the same temperature, so diurnal heating is
        directly visible as colour change between frames.

        Sky pixels are rendered at air_temperature (they appear cool/blue, matching
        what a real thermal camera sees when pointed at a clear sky).

        Parameters
        ----------
        surface_temperature : np.ndarray  shape (512,512) or (262144,), °C
        segmentation_data   : np.ndarray  shape (512,512), integer class labels
        location            : dict        (unused here, kept for API consistency)
        direction           : str         cubemap face name
        timestep            : int         time index
        folder_id           : str         output subfolder
        air_temperature     : float       °C — used for sky pixels
        t_min_global        : float       global colour-scale lower bound [°C]
        t_max_global        : float       global colour-scale upper bound [°C]
        save_npy            : bool        if True, save raw array as .npy alongside image
        """

        # ── Guard: empty input ────────────────────────────────────────────────────
        if surface_temperature is None or surface_temperature.size == 0:
            print(f"[ERROR] Empty surface temperature: dir={direction}, t={timestep}")
            return

        # ── Shape normalisation ───────────────────────────────────────────────────
        if surface_temperature.ndim == 1:
            surface_temperature = surface_temperature.reshape((512, 512))

        # ── Output directories ────────────────────────────────────────────────────
        img_dir  = f"./output/{folder_id}/validation_thermal_images"
        data_dir = f"./output/{folder_id}/surface_temperature_data"
        os.makedirs(img_dir,  exist_ok=True)
        if save_npy:
            os.makedirs(data_dir, exist_ok=True)

        img_path  = f"{img_dir}/thermal_{timestep:04d}_{direction}.png"
        npy_path  = f"{data_dir}/Ts_{timestep:04d}_{direction}.npy"
        csv_path_ = f"{data_dir}/Ts_{timestep:04d}_{direction}.csv"

        # ── Sky pixels → air temperature (NaN → visible cool value) ──────────────
        sky_mask = (segmentation_data == 1)
        Ts = surface_temperature.copy().astype(np.float32)
        Ts[sky_mask] = air_temperature          # sky shows at air temp (cool/blue)
        Ts = np.nan_to_num(Ts, nan=air_temperature)

        # ── Save raw numerical data ───────────────────────────────────────────────
        if save_npy:
            np.save(npy_path, Ts)
            # Also save a human-readable CSV (rounded to 2 dp to keep file size sane)
            np.savetxt(
                csv_path_,
                np.round(Ts, 2),
                delimiter=",",
                fmt="%.2f",
                header=f"Surface temperature [°C], direction={direction}, t={timestep}, "
                    f"air_temp={air_temperature:.1f}",
                comments=""
            )

        # ── FLIR iron palette via matplotlib inferno (correct, full 256 entries) ──
        # matplotlib is already imported at the top of this file.
        # inferno: black → purple → red → orange → yellow → white
        # This matches the FLIR "iron" display mode used on T-series cameras.
        # Using a manual sparse LUT caused cool pixels (~31°C) to map into red
        # because only 24/121 entries covered the entire cold zone.
        import matplotlib.cm as _cm
        _lut_f = _cm.inferno(np.linspace(0, 1, 256))[:, :3]   # shape (256, 3), float [0,1]
        lut = (_lut_f * 255).astype(np.uint8)                  # shape (256, 3), uint8

        # ── Normalise with fixed global range → 0–255 index ──────────────────────
        t_range = max(t_max_global - t_min_global, 1.0)   # avoid div-by-zero
        norm = np.clip((Ts - t_min_global) / t_range, 0.0, 1.0)
        indices = (norm * 255).astype(np.uint8)            # shape (512,512)

        # ── Apply LUT ────────────────────────────────────────────────────────────
        rgb_array = lut[indices]                           # shape (512,512,3)

        # # ── Colour-bar strip (right edge, 20 px wide) — shows the scale ──────────
        # bar_width = 20
        # bar = np.zeros((512, bar_width, 3), dtype=np.uint8)
        # for row in range(512):
        #     idx = int((1.0 - row / 511) * 255)            # top = hot, bottom = cold
        #     bar[row] = lut[idx]

        # rgb_with_bar = np.concatenate([rgb_array, bar], axis=1)   # (512, 532, 3)

        # ── Save image ────────────────────────────────────────────────────────────
        # ── Save image — no colorbar strip, legend is in colorbar_legend.png ─────
        img = Image.fromarray(rgb_array)
        img.save(img_path)

        if Config.debug_mode:
            print(f"[THERMAL_IMG] t={timestep:04d} {direction:8s}  "
                f"Ts∈[{Ts.min():.1f}, {Ts.max():.1f}]°C  "
                f"scale=[{t_min_global},{t_max_global}]°C  → {img_path}")