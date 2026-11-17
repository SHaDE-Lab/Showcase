/*
 * MaRTiny network helpers for the ESP32-CAM sketch: URL encoding, the collector that picks the sensor JSON out of the
 * serial stream from the Arduino Uno, the device id sent with every upload, and the multipart header of the photo upload.
 *
 * Plain C with no Arduino or ESP32 dependency, so tests/ compile and check it on a PC.
 *
 * Copyright 2026 The SHaDE Lab, Arizona State University
 * This source describes Open Hardware and is licensed under the CERN-OHL-P v2.
 * You may redistribute and modify this source and make products using it under the terms of the
 * CERN-OHL-P v2 (https://ohwr.org/cern_ohl_p_v2.txt).
 * This source is distributed WITHOUT ANY EXPRESS OR IMPLIED WARRANTY, INCLUDING OF MERCHANTABILITY,
 * SATISFACTORY QUALITY AND FITNESS FOR A PARTICULAR PURPOSE.
 * Please see the CERN-OHL-P v2 for applicable conditions.
 */
#ifndef MARTINY_NET_H
#define MARTINY_NET_H

#include <stddef.h>
#include <stdint.h>
#include <stdio.h>
#include <string.h>

#ifdef __cplusplus
extern "C" {
#endif

/* Percent-encodes `in` for use in a URL query: a space becomes '+', letters and digits stay, every other byte becomes %XX
   (uppercase hex). Returns the encoded length, or -1 if `out` is too small (out then holds an empty string). */
static inline int mt_urlencode(const char *in, char *out, size_t cap) {
  static const char HEX[] = "0123456789ABCDEF";
  size_t o = 0;
  if (cap == 0) return -1;
  for (const unsigned char *p = (const unsigned char *)in; *p; p++) {
    unsigned char c = *p;
    int alnum = (c >= '0' && c <= '9') || (c >= 'A' && c <= 'Z') || (c >= 'a' && c <= 'z');
    size_t need = (alnum || c == ' ') ? 1 : 3;
    if (o + need + 1 > cap) { out[0] = '\0'; return -1; }
    if (c == ' ') out[o++] = '+';
    else if (alnum) out[o++] = (char)c;
    else { out[o++] = '%'; out[o++] = HEX[c >> 4]; out[o++] = HEX[c & 15]; }
  }
  out[o] = '\0';
  return (int)o;
}

/* The device id used as "uuid" in the photo upload: the MAC address with ':' replaced by '_'. */
static inline void mt_device_id(const char *mac, char *out, size_t cap) {
  size_t i = 0;
  if (cap == 0) return;
  for (; mac[i] && i + 1 < cap; i++) out[i] = (mac[i] == ':') ? '_' : mac[i];
  out[i] = '\0';
}

/* Picks one flat JSON object, {...}, out of a serial stream. Anything outside the braces is ignored (the Arduino also
   echoes its commands), a new '{' restarts the object, and one that outgrows the buffer is dropped. */
#define MT_JSON_MAX 320
typedef struct { char buf[MT_JSON_MAX]; uint16_t len; uint8_t active; } mt_json_collector;

static inline void mt_json_init(mt_json_collector *j) { j->len = 0; j->active = 0; j->buf[0] = '\0'; }

/* Feed one character. Returns 1 when a complete object is ready in j->buf. */
static inline int mt_json_feed(mt_json_collector *j, char c) {
  if (c == '{') { j->active = 1; j->len = 0; j->buf[j->len++] = '{'; j->buf[j->len] = '\0'; return 0; }
  if (!j->active) return 0;
  if (j->len + 2 > MT_JSON_MAX) { j->active = 0; j->len = 0; j->buf[0] = '\0'; return 0; }
  j->buf[j->len++] = c; j->buf[j->len] = '\0';
  if (c == '}') { j->active = 0; return 1; }
  return 0;
}

/* Multipart/form-data pieces for the photo upload. The boundary is fixed; the server only needs the field names
   "uuid" and "image". Total request body length = head length + image length + tail length. */
#define MT_BOUNDARY "MaRTiny-Edge"
#define MT_MULTIPART_TAIL "\r\n--" MT_BOUNDARY "--\r\n"

static inline int mt_multipart_head(char *out, size_t cap, const char *device_id) {
  int n = snprintf(out, cap,
                   "--" MT_BOUNDARY "\r\n"
                   "Content-Disposition: form-data; name=\"uuid\"\r\n\r\n"
                   "%s\r\n"
                   "--" MT_BOUNDARY "\r\n"
                   "Content-Disposition: form-data; name=\"image\"; filename=\"esp32-cam.jpg\"\r\n"
                   "Content-Type: image/jpeg\r\n\r\n",
                   device_id);
  return (n < 0 || (size_t)n >= cap) ? -1 : n;
}

#ifdef __cplusplus
}
#endif
#endif /* MARTINY_NET_H */
