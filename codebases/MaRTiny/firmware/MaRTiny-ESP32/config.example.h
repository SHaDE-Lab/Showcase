/*
 * MaRTiny ESP32-CAM settings. Copy this file to "config.h" (next to the sketch) and fill in your own values.
 * config.h is listed in .gitignore, so your network name, password and server address are never committed.
 */
#ifndef MARTINY_CONFIG_H
#define MARTINY_CONFIG_H

/* Wi-Fi the camera joins */
#define MARTINY_WIFI_SSID     "your-wifi-name"
#define MARTINY_WIFI_PASSWORD "your-wifi-password"

/* The server that receives the data (see the MaRTiny-server and MaRTiny-edge projects). Use your own host name or IP address. */
#define MARTINY_SERVER_HOST   "your-server.example.org"

/* Photo upload: multipart POST, handled by the image server */
#define MARTINY_IMAGE_PORT    8080
#define MARTINY_IMAGE_PATH    "/api/v1/"

/* Sensor data: HTTP GET with ?data=...&mac=..., handled by the edge server */
#define MARTINY_DATA_PORT     8081
#define MARTINY_DATA_PATH     "/updateData"

/* Name of the access point the camera opens when the sketch is built with SOFTAP_MODE */
#define MARTINY_SOFTAP_SSID   "martiny-softap"

#endif /* MARTINY_CONFIG_H */
