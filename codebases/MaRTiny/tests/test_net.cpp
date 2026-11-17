// Tests for firmware/MaRTiny-ESP32/martiny_net.h, plus an end-to-end check that ties it to martiny_sensors.h:
// the Arduino's JSON line is read by the ESP32 collector and URL-encoded exactly as it goes onto the wire.
#include <cstdio>
#include <cstring>
#include <string>
#include "../firmware/MaRTiny-Arduino/martiny_sensors.h"
#include "../firmware/MaRTiny-ESP32/martiny_net.h"

static int failures = 0, checks = 0;
#define CHECK(cond, name) do { checks++; if (cond) std::printf("ok   %s\n", name); else { failures++; std::printf("FAIL %s  (line %d)\n", name, __LINE__); } } while (0)
static std::string enc(const char *s) { char b[600]; int n = mt_urlencode(s, b, sizeof b); return n < 0 ? "<overflow>" : std::string(b); }
static std::string hex(const std::string &s) { std::string h; char t[4]; for (unsigned char c : s) { std::snprintf(t, sizeof t, "%02x", c); h += t; } return h; }

static void test_urlencode() {
  CHECK(enc("abcXYZ019") == "abcXYZ019", "urlencode: letters and digits unchanged");
  CHECK(enc("a b") == "a+b", "urlencode: space becomes +");
  CHECK(enc("{\"a\":1}") == "%7B%22a%22%3A1%7D", "urlencode: braces, quotes and colon");
  CHECK(enc("AA:BB") == "AA%3ABB", "urlencode: MAC address colon");
  CHECK(enc("100%") == "100%25", "urlencode: percent sign");
  CHECK(enc("\xC3\xA9") == "%C3%A9", "urlencode: bytes above 127 use unsigned hex");
  CHECK(enc("") == "", "urlencode: empty string");
  char tiny[5];
  CHECK(mt_urlencode("{\"a\"}", tiny, sizeof tiny) == -1 && tiny[0] == '\0', "urlencode: reports a too-small buffer");
  CHECK(mt_urlencode("x", tiny, 0) == -1, "urlencode: zero-size buffer");
  // Strings whose encoding is checked against Python's unquote_plus by the pytest wrapper.
  const char *samples[] = {"plain", "with space", "{\"Temperature\":23.45,\"Humidity\":40.00}", "AA:BB:CC:DD:EE:FF", "50% + 50%", "caf\xC3\xA9", "~_.-"};
  for (const char *s : samples) std::printf("DATA enc %s %s\n", hex(s).c_str(), enc(s).c_str());
}

static void test_device_id() {
  char id[24];
  mt_device_id("24:6F:28:AA:BB:CC", id, sizeof id);
  CHECK(std::string(id) == "24_6F_28_AA_BB_CC", "device id: colons become underscores");
  char small[6];
  mt_device_id("24:6F:28:AA", small, sizeof small);
  CHECK(std::strlen(small) == 5, "device id: truncated to fit, still terminated");
}

static void test_collector() {
  mt_json_collector j; mt_json_init(&j);
  auto feed = [&](const char *s) { int done = 0; for (; *s; s++) done += mt_json_feed(&j, *s); return done; };
  CHECK(feed("{\"a\":1}") == 1 && std::string(j.buf) == "{\"a\":1}", "collector: one object");
  mt_json_init(&j);
  CHECK(feed("Send\r\n{\"a\":2}\r\n") == 1 && std::string(j.buf) == "{\"a\":2}", "collector: ignores the echoed command around it");
  mt_json_init(&j);
  CHECK(feed("{\"a\":") == 0 && feed("3}") == 1 && std::string(j.buf) == "{\"a\":3}", "collector: object split across reads");
  mt_json_init(&j);
  CHECK(feed("{\"x\":{\"y\":1}") == 1, "collector: a flat object ends at the first closing brace");
  mt_json_init(&j);
  CHECK(feed("{\"a\":1") == 0 && feed("{\"b\":2}") == 1 && std::string(j.buf) == "{\"b\":2}", "collector: a new { restarts");
  mt_json_init(&j);
  std::string big = "{\"k\":\"" + std::string(400, 'x') + "\"}";
  CHECK(feed(big.c_str()) == 0, "collector: an over-long object is dropped");
  CHECK(feed("{\"a\":4}") == 1, "collector: recovers after an over-long object");
}

static void test_multipart() {
  char head[320];
  int n = mt_multipart_head(head, sizeof head, "24_6F_28_AA_BB_CC");
  CHECK(n > 0 && (size_t)n == std::strlen(head), "multipart: head built, length matches");
  CHECK(std::strstr(head, "name=\"uuid\"\r\n\r\n24_6F_28_AA_BB_CC\r\n") != nullptr, "multipart: device id field");
  CHECK(std::strstr(head, "name=\"image\"; filename=\"esp32-cam.jpg\"") != nullptr, "multipart: image field");
  CHECK(std::strstr(head, "Content-Type: image/jpeg\r\n\r\n") != nullptr && std::strcmp(head + n - 4, "\r\n\r\n") == 0, "multipart: head ends where the image starts");
  CHECK(std::strcmp(MT_MULTIPART_TAIL, "\r\n--MaRTiny-Edge--\r\n") == 0, "multipart: closing boundary");
  char tiny[20];
  CHECK(mt_multipart_head(tiny, sizeof tiny, "x") == -1, "multipart: reports a too-small buffer");
}

static void test_end_to_end() {
  // Arduino side: build the line. ESP32 side: collect it from a noisy stream and encode it for the URL.
  mt_accum a; mt_accum_reset(&a);
  mt_accum_add_dht(&a, 31.5f, 22.0f); mt_accum_add_dallas(&a, 0, 30.1f); mt_accum_add_dallas(&a, 1, 54.9f);
  mt_accum_tick(&a, 7.2f, 3.1f);
  char line[200];
  size_t len = mt_build_message(line, sizeof line, &a, 12.4f);
  CHECK(len > 0, "end to end: Arduino builds the message");
  std::string stream = std::string("Send\r\n") + line + "\r\n";
  mt_json_collector j; mt_json_init(&j);
  int got = 0;
  for (char c : stream) got += mt_json_feed(&j, c);
  CHECK(got == 1 && std::string(j.buf) == std::string(line), "end to end: ESP32 collects exactly what the Arduino sent");
  char wire[MT_JSON_MAX * 3 + 1];
  CHECK(mt_urlencode(j.buf, wire, sizeof wire) > 0, "end to end: message encodes into the URL buffer");
  std::printf("DATA wire %s\n", wire);
  std::printf("DATA original %s\n", line);
}

int main() {
  test_urlencode(); test_device_id(); test_collector(); test_multipart(); test_end_to_end();
  std::printf("%d checks, %d failed\n", checks, failures);
  return failures ? 1 : 0;
}
