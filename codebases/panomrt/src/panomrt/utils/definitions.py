#
#   File for basics definitions
#

import math
#
# ------------------------------------
#    PET Calculator Definitions
# ------------------------------------
#


po = 1013.25
p = 1013.25
rob = 1.06
cb = 3.64e3
food = 0.0
emsk = 0.99
emcl = 0.95
evap = 2.42e6
sigm = 5.67e-8
eta = 0.0
fcl = 1.15
height = 1.75
weight = 75
age = 35
sex = 1
clothing = 0.9
activity = 80
standing = 1


#
# ------------------------------------
#    Surface Temperature Definitions
# ------------------------------------
#

rad = math.pi/180
dEarthMeanRadius = 6371.01
dAstronomicalUnit = 149597890

C_STEFAN_BOLTZMANN = 5.670367e-8
C_ENV_EMISSION = 0.95
C_BODY_EMISSION = 0.97
C_BODY_ABSORPTION = 0.7
C_LINKE_TURBIDITY = 4.2
G_SC = 1367
C_ALBEDO_ENV = 0.3
C_BOWEN_RATIO = 1
C_PRESSURE_AT_SEA_LEVEL = 101325
C_BOWEN_RATIO_TREE = 20
C_BOWEN_RATIO_IMPERVIOUS = 20
C_BOWEN_RATIO_PERVIOUS = 0.3
C_BOWEN_RATIO_BUILDING = 20
C_BOWEN_RATIO_MOVING_OBJECTS = 20
N_RINGS = 32

numLayers = 4

NORTH = 0
EAST = 1
SOUTH = 2
WEST = 3
UP = 4
DOWN = 5

TOP = 0
RIGHT = 1
BOTTOM = 2
LEFT = 3
CENTER = 4

longWaveIndicies = [
    [UP, EAST, DOWN, WEST, NORTH],
    [UP, SOUTH, DOWN, NORTH, EAST],
    [UP, WEST, DOWN, EAST, SOUTH],
    [UP, NORTH, DOWN, SOUTH, WEST],
    [NORTH, EAST, SOUTH, WEST, UP],
    [NORTH, EAST, SOUTH, WEST, DOWN]
]

fisheyeIndicies = [
    [TOP, RIGHT, BOTTOM, LEFT, CENTER],
    [LEFT, RIGHT, LEFT, LEFT, CENTER],
    [BOTTOM, RIGHT, TOP, LEFT, CENTER],
    [RIGHT, RIGHT, RIGHT, RIGHT, CENTER],
    [BOTTOM, BOTTOM, BOTTOM, BOTTOM, CENTER],
    [TOP, TOP, TOP, TOP, CENTER]
]
