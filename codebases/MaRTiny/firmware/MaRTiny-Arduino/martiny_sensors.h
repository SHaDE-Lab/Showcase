/*
 * MaRTiny sensor logic: the maths, the JSON message and the serial command parser used by the Arduino Uno sketch.
 *
 * Plain C that needs no Arduino library, so the same code runs on the Uno (avr-gcc) and on a PC, where
 * tests/ compile and check it. It avoids printf("%f") and malloc, neither of which suits an AVR.
 *
 * Copyright 2026 The SHaDE Lab, Arizona State University
 * This source describes Open Hardware and is licensed under the CERN-OHL-P v2.
 * You may redistribute and modify this source and make products using it under the terms of the
 * CERN-OHL-P v2 (https://ohwr.org/cern_ohl_p_v2.txt).
 * This source is distributed WITHOUT ANY EXPRESS OR IMPLIED WARRANTY, INCLUDING OF MERCHANTABILITY,
 * SATISFACTORY QUALITY AND FITNESS FOR A PARTICULAR PURPOSE.
 * Please see the CERN-OHL-P v2 for applicable conditions.
 */
#ifndef MARTINY_SENSORS_H
#define MARTINY_SENSORS_H

#include <stddef.h>
#include <stdint.h>
#include <string.h>

#ifdef __cplusplus
extern "C" {
#endif

/* ---------- calibration of the cup anemometer (analog voltage output) ---------- */
#define MT_WIND_V_MIN      0.454f       /* volts at zero wind. Differs for every sensor: measure yours with the cups held still. */
#define MT_WIND_V_MAX      2.0f         /* volts at full scale */
#define MT_WIND_SPEED_MAX  32.0f        /* m/s at MT_WIND_V_MAX */
#define MT_ADC_VOLTS       0.004882814f /* volts per ADC step on a 5 V reference */

/* readings at or below this are a disconnected DS18B20 (the library returns -127) */
#define MT_DALLAS_INVALID  (-126.0f)

/* ---------- small conversions ---------- */
static inline float mt_map_float(float x, float in_min, float in_max, float out_min, float out_max) {
  return (x - in_min) * (out_max - out_min) / (in_max - in_min) + out_min;
}

/* ML8511 UV sensor: scale the output by the 3.3 V reference reading, then map 0.99 to 2.8 V onto 0 to 15 (mW/cm^2). Never negative. */
static inline float mt_uv_intensity(int uv_level, int ref_level) {
  if (ref_level <= 0) return 0.0f;
  float volts = 3.3f / (float)ref_level * (float)uv_level;
  float raw = mt_map_float(volts, 0.99f, 2.8f, 0.0f, 15.0f);
  return raw > 0.0f ? raw : 0.0f;
}

/* Cup anemometer: linear between the zero-wind voltage and full scale. Outside that range the sample counts as 0 m/s. */
static inline float mt_wind_speed(int adc) {
  float v = (float)adc * MT_ADC_VOLTS;
  if (v > MT_WIND_V_MIN && v <= MT_WIND_V_MAX) return (v - MT_WIND_V_MIN) * MT_WIND_SPEED_MAX / (MT_WIND_V_MAX - MT_WIND_V_MIN);
  return 0.0f;
}

/* Battery voltage through a 1:2 divider on a 5 V reference. */
static inline float mt_battery_voltage(int adc) { return (float)adc * (5.0f / 1023.0f) * 2.0f; }

/* ---------- running sums between two "Send" requests ---------- */
typedef struct {
  float temp, hum, uv, dallas1, dallas2, wind;
  uint16_t n;        /* measurement loops (UV and wind are added every loop) */
  uint16_t n_dht;    /* valid DHT22 readings */
  uint16_t n_d1, n_d2; /* valid DS18B20 readings */
} mt_accum;

static inline void mt_accum_reset(mt_accum *a) { memset(a, 0, sizeof(*a)); }
static inline void mt_accum_tick(mt_accum *a, float uv, float wind) { a->uv += uv; a->wind += wind; a->n++; }
static inline void mt_accum_add_dht(mt_accum *a, float t, float h) {
  if (t != t || h != h) return;                    /* NaN: the DHT22 read failed, so it must not pull the average down */
  a->temp += t; a->hum += h; a->n_dht++;
}
static inline void mt_accum_add_dallas(mt_accum *a, int index, float c) {
  if (c != c || c <= MT_DALLAS_INVALID) return;    /* disconnected probe */
  if (index == 0) { a->dallas1 += c; a->n_d1++; } else { a->dallas2 += c; a->n_d2++; }
}

/* ---------- number formatting without printf("%f") ---------- */
static inline int mt_copy(char *out, size_t cap, const char *s) {
  size_t n = strlen(s);
  if (n + 1 > cap) return -1;
  memcpy(out, s, n + 1);
  return (int)n;
}

/* Writes v with `dec` decimals (0 to 4). NaN, infinity or a value too large for the arithmetic becomes the text null, so the JSON stays valid.
   Returns the length, or -1 if the buffer is too small. */
static inline int mt_fmt_float(char *out, size_t cap, float v, int dec) {
  static const uint32_t P10[5] = {1u, 10u, 100u, 1000u, 10000u};
  if (out == 0 || cap < 2) return -1;
  if (dec < 0 || dec > 4) dec = 2;
  float av = v < 0 ? -v : v;
  if (v != v || av * (float)P10[dec] >= 4.0e9f) return mt_copy(out, cap, "null");
  uint32_t scale = P10[dec];
  uint32_t r = (uint32_t)(av * (float)scale + 0.5f);
  int neg = (v < 0 && r != 0);
  uint32_t ip = r / scale, fp = r % scale;
  char digits[12]; int nd = 0;
  do { digits[nd++] = (char)('0' + ip % 10u); ip /= 10u; } while (ip > 0 && nd < 11);
  size_t need = (size_t)(neg ? 1 : 0) + (size_t)nd + (dec ? (size_t)(1 + dec) : 0) + 1;
  if (need > cap) return -1;
  size_t i = 0;
  if (neg) out[i++] = '-';
  while (nd > 0) out[i++] = digits[--nd];
  if (dec) {
    out[i++] = '.';
    for (int k = dec - 1; k >= 0; k--) { out[i + (size_t)k] = (char)('0' + fp % 10u); fp /= 10u; }
    i += (size_t)dec;
  }
  out[i] = '\0';
  return (int)i;
}

/* ---------- the JSON line sent to the ESP32-CAM ---------- */
typedef struct { char *p; size_t cap, len; int bad; } mt_sb;
static inline void mt_sb_str(mt_sb *s, const char *t) {
  size_t n = strlen(t);
  if (s->bad || s->len + n + 1 > s->cap) { s->bad = 1; return; }
  memcpy(s->p + s->len, t, n + 1); s->len += n;
}
static inline void mt_sb_value(mt_sb *s, const char *key, float sum, uint16_t count, int last) {
  char num[20];
  mt_sb_str(s, "\"");  mt_sb_str(s, key);  mt_sb_str(s, "\":");
  if (count == 0) mt_sb_str(s, "null");                    /* nothing valid was measured: say so */
  else if (mt_fmt_float(num, sizeof num, sum / (float)count, 2) < 0) s->bad = 1;
  else mt_sb_str(s, num);
  if (!last) mt_sb_str(s, ",");
}

/* {"Temperature":..,"Humidity":..,"UV_Intensity":..,"Dallas1":..,"Dallas2":..,"Wind_Speed":..,"Battery_Voltage":..}
   Sums are divided by their own counts. Returns the length, or 0 if the buffer is too small. */
static inline size_t mt_build_message(char *out, size_t cap, const mt_accum *a, float battery_volts) {
  mt_sb s; s.p = out; s.cap = cap; s.len = 0; s.bad = 0;
  if (cap) out[0] = '\0';
  mt_sb_str(&s, "{");
  mt_sb_value(&s, "Temperature", a->temp, a->n_dht, 0);
  mt_sb_value(&s, "Humidity", a->hum, a->n_dht, 0);
  mt_sb_value(&s, "UV_Intensity", a->uv, a->n, 0);
  mt_sb_value(&s, "Dallas1", a->dallas1, a->n_d1, 0);
  mt_sb_value(&s, "Dallas2", a->dallas2, a->n_d2, 0);
  mt_sb_value(&s, "Wind_Speed", a->wind, a->n, 0);
  mt_sb_value(&s, "Battery_Voltage", battery_volts, 1, 1);
  mt_sb_str(&s, "}");
  if (s.bad) { if (cap) out[0] = '\0'; return 0; }
  return s.len;
}

/* ---------- serial commands from the ESP32-CAM, written as [Send] or [ResetESP32] ---------- */
#define MT_CMD_MAX 24
typedef struct { char buf[MT_CMD_MAX]; uint8_t len; uint8_t active; } mt_cmd_parser;

static inline void mt_cmd_init(mt_cmd_parser *p) { p->len = 0; p->active = 0; p->buf[0] = '\0'; }

/* Feed one received character. Returns 1 when a complete command is ready in p->buf. Text outside brackets is ignored,
   a new "[" restarts the command, and a command longer than the buffer is dropped. */
static inline int mt_cmd_feed(mt_cmd_parser *p, char c) {
  if (c == '[') { p->active = 1; p->len = 0; p->buf[0] = '\0'; return 0; }
  if (!p->active) return 0;
  if (c == ']') { p->active = 0; p->buf[p->len] = '\0'; return 1; }
  if (p->len < MT_CMD_MAX - 1) { p->buf[p->len++] = c; p->buf[p->len] = '\0'; return 0; }
  p->active = 0; p->len = 0; p->buf[0] = '\0';
  return 0;
}
static inline int mt_cmd_is(const mt_cmd_parser *p, const char *name) { return strcmp(p->buf, name) == 0; }

#ifdef __cplusplus
}
#endif
#endif /* MARTINY_SENSORS_H */
