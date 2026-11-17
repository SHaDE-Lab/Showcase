// Tests for firmware/MaRTiny-Arduino/martiny_sensors.h. Build and run through tests/test_firmware.py, or compile by hand.
// Prints one "ok"/"FAIL" line per check, and a few "DATA" lines that the Python side parses independently.
#include <cmath>
#include <cstdio>
#include <cstring>
#include <string>
#include "../firmware/MaRTiny-Arduino/martiny_sensors.h"

static int failures = 0, checks = 0;
#define CHECK(cond, name) do { checks++; if (cond) std::printf("ok   %s\n", name); else { failures++; std::printf("FAIL %s  (line %d)\n", name, __LINE__); } } while (0)
static bool near(double a, double b, double tol = 1e-3) { return std::fabs(a - b) <= tol; }
static std::string fmt(float v, int dec = 2) { char b[32]; int n = mt_fmt_float(b, sizeof b, v, dec); return n < 0 ? "<overflow>" : std::string(b); }

static void test_format() {
  CHECK(fmt(0.0f) == "0.00", "format zero");
  CHECK(fmt(23.456f) == "23.46", "format rounds half up");
  CHECK(fmt(-1.5f) == "-1.50", "format negative");
  CHECK(fmt(0.004f) == "0.00", "format tiny positive is 0.00");
  CHECK(fmt(-0.004f) == "0.00", "format tiny negative has no minus sign");
  CHECK(fmt(5.0f, 0) == "5", "format zero decimals");
  CHECK(fmt(12.3456f, 3) == "12.346", "format three decimals");
  CHECK(fmt(12345.67f) == "12345.67", "format large value (7 significant digits is the limit of a 32-bit float)");
  CHECK(fmt(NAN) == "null", "format NaN is null");
  CHECK(fmt(INFINITY) == "null", "format infinity is null");
  CHECK(fmt(1.0e9f) == "null", "format too-large value is null");
  char tiny[4];
  CHECK(mt_fmt_float(tiny, sizeof tiny, 123.45f, 2) == -1, "format reports a too-small buffer");
}

static void test_conversions() {
  // UV: 3.3 V reference reading of 675 counts; sensor reading chosen for 1.5 V and for 0.5 V.
  int ref = 675;
  int uv15 = (int)std::lround(1.5 / (3.3 / ref));
  double expect = (1.5 - 0.99) * 15.0 / (2.8 - 0.99);
  CHECK(near(mt_uv_intensity(uv15, ref), expect, 0.05), "uv mid-range value");
  CHECK(mt_uv_intensity((int)std::lround(0.5 / (3.3 / ref)), ref) == 0.0f, "uv below the offset voltage is never negative");
  CHECK(near(mt_uv_intensity((int)std::lround(2.8 / (3.3 / ref)), ref), 15.0, 0.1), "uv full scale");
  CHECK(mt_uv_intensity(300, 0) == 0.0f, "uv with a missing reference reading is 0, not a divide by zero");

  // Wind: zero below the offset, linear in between, zero above full scale.
  CHECK(mt_wind_speed(0) == 0.0f, "wind: no signal is 0 m/s");
  CHECK(mt_wind_speed((int)(0.40 / MT_ADC_VOLTS)) == 0.0f, "wind: below the zero-wind voltage is 0 m/s");
  int adc = 300;                                      // 1.4648 V
  double v = adc * (double)MT_ADC_VOLTS;
  CHECK(near(mt_wind_speed(adc), (v - 0.454) * 32.0 / (2.0 - 0.454), 0.01), "wind: linear in the working range");
  CHECK(mt_wind_speed(409) > 31.0f && mt_wind_speed(409) <= 32.0f, "wind: near full scale");
  CHECK(mt_wind_speed(430) == 0.0f, "wind: above full scale counts as 0 m/s");

  CHECK(near(mt_battery_voltage(0), 0.0), "battery: 0 counts");
  CHECK(near(mt_battery_voltage(1023), 10.0, 0.01), "battery: full scale through the 1:2 divider is 10 V");
  CHECK(near(mt_battery_voltage(600), 600 * 5.0 / 1023.0 * 2.0, 0.01), "battery: mid value");
}

static void test_accumulator() {
  mt_accum a; mt_accum_reset(&a);
  mt_accum_add_dht(&a, 20.0f, 40.0f);
  mt_accum_add_dht(&a, NAN, NAN);                     // failed DHT22 read
  mt_accum_add_dht(&a, 30.0f, 60.0f);
  CHECK(a.n_dht == 2, "dht: failed reads are not counted");
  mt_accum_add_dallas(&a, 0, 25.0f);
  mt_accum_add_dallas(&a, 0, -127.0f);                // disconnected probe
  mt_accum_add_dallas(&a, 0, 27.0f);
  mt_accum_add_dallas(&a, 1, -127.0f);
  CHECK(a.n_d1 == 2 && a.n_d2 == 0, "dallas: -127 (disconnected) is ignored");
  mt_accum_tick(&a, 2.0f, 4.0f); mt_accum_tick(&a, 4.0f, 6.0f);
  CHECK(a.n == 2 && near(a.uv, 6.0) && near(a.wind, 10.0), "tick adds uv and wind every loop");

  char msg[200];
  size_t len = mt_build_message(msg, sizeof msg, &a, 7.25f);
  CHECK(len > 0 && len == std::strlen(msg), "message built, length matches");
  // Averages use each sensor's own count: temperature (20+30)/2, humidity (40+60)/2, UV 6/2, wind 10/2, dallas1 (25+27)/2, dallas2 none.
  std::printf("DATA message %s\n", msg);

  mt_accum e; mt_accum_reset(&e);
  size_t elen = mt_build_message(msg, sizeof msg, &e, 0.0f);
  CHECK(elen > 0, "message with no readings still builds");
  std::printf("DATA empty %s\n", msg);

  char small[40];
  CHECK(mt_build_message(small, sizeof small, &a, 7.25f) == 0 && small[0] == '\0', "message that does not fit returns 0 and an empty string");
}

static void test_parser() {
  mt_cmd_parser p; mt_cmd_init(&p);
  auto feed = [&](const char *s) { int done = 0; for (; *s; s++) done += mt_cmd_feed(&p, *s); return done; };
  CHECK(feed("[Send]") == 1 && mt_cmd_is(&p, "Send"), "parser: [Send]");
  mt_cmd_init(&p);
  CHECK(feed("noise[ResetESP32]more") == 1 && mt_cmd_is(&p, "ResetESP32"), "parser: ignores text outside brackets");
  mt_cmd_init(&p);
  CHECK(feed("Send") == 0, "parser: no brackets, no command");
  mt_cmd_init(&p);
  CHECK(feed("[Sen[Send]") == 1 && mt_cmd_is(&p, "Send"), "parser: a new [ restarts the command");
  mt_cmd_init(&p);
  CHECK(feed("[Se") == 0 && feed("nd]") == 1 && mt_cmd_is(&p, "Send"), "parser: command split across reads");
  mt_cmd_init(&p);
  CHECK(feed("[ThisCommandIsFarTooLongForTheBuffer]") == 0, "parser: over-long command is dropped");
  CHECK(feed("[Send]") == 1 && mt_cmd_is(&p, "Send"), "parser: recovers after an over-long command");
  mt_cmd_init(&p);
  CHECK(feed("[]") == 1 && mt_cmd_is(&p, ""), "parser: empty command is reported as empty");
}

int main() {
  test_format(); test_conversions(); test_accumulator(); test_parser();
  std::printf("%d checks, %d failed\n", checks, failures);
  return failures ? 1 : 0;
}
