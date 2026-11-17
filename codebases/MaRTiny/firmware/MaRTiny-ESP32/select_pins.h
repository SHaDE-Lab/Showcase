/*
 * Camera pin map for the AI-Thinker ESP32-CAM board (the board MaRTiny uses), as in the Espressif camera examples.
 * The sketch defines CAMERA_MODEL_AI_THINKER; for another board, replace the numbers below with that board's pin map.
 */
#ifndef MARTINY_SELECT_PINS_H
#define MARTINY_SELECT_PINS_H

#if defined(CAMERA_MODEL_AI_THINKER)
#define PWDN_GPIO_NUM     32
#define RESET_GPIO_NUM    -1
#define XCLK_GPIO_NUM      0
#define SIOD_GPIO_NUM     26
#define SIOC_GPIO_NUM     27

#define Y9_GPIO_NUM       35
#define Y8_GPIO_NUM       34
#define Y7_GPIO_NUM       39
#define Y6_GPIO_NUM       36
#define Y5_GPIO_NUM       21
#define Y4_GPIO_NUM       19
#define Y3_GPIO_NUM       18
#define Y2_GPIO_NUM        5
#define VSYNC_GPIO_NUM    25
#define HREF_GPIO_NUM     23
#define PCLK_GPIO_NUM     22
#else
#error "Define a camera model and its pin map in select_pins.h"
#endif

#endif /* MARTINY_SELECT_PINS_H */
