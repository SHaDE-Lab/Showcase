/*
 * MaRTiny: Arduino Uno sketch.
 *
 * Reads the weather sensors, keeps running averages, and answers the ESP32-CAM over the serial line:
 *   ESP32-CAM -> Uno : [Send]        reply with one JSON line of averages, then start a new averaging window
 *   ESP32-CAM -> Uno : [ResetESP32]  power-cycle the ESP32-CAM
 * If no [Send] arrives for 10 minutes, the Uno power-cycles the ESP32-CAM by itself.
 *
 * The maths, the JSON message and the command parser live in martiny_sensors.h, which is tested on a PC (see tests/).
 *
 * Copyright 2026 The SHaDE Lab, Arizona State University
 * This source describes Open Hardware and is licensed under the CERN-OHL-P v2.
 * You may redistribute and modify this source and make products using it under the terms of the
 * CERN-OHL-P v2 (https://ohwr.org/cern_ohl_p_v2.txt).
 * This source is distributed WITHOUT ANY EXPRESS OR IMPLIED WARRANTY, INCLUDING OF MERCHANTABILITY,
 * SATISFACTORY QUALITY AND FITNESS FOR A PARTICULAR PURPOSE.
 * Please see the CERN-OHL-P v2 for applicable conditions.
 */

//========== PIN CONFIGURATION =================//
// UV sensor (ML8511): signal on A0, 3.3 V reference on A1
// DS18B20 Dallas probes (OneWire bus): D4
// DHT22 humidity sensor: D3
// Cup anemometer (analog voltage): A4
// Battery voltage (1:2 divider): A2
// ESP32-CAM power control: D6 and D7 (LOW = off, HIGH = on)

#include <avr/wdt.h>
#include "DHT.h"                // DHT Sensor
#include <OneWire.h>            // For Dallas sensor communication
#include <DallasTemperature.h>  // For Dallas sensor reading
#include "martiny_sensors.h"    // maths, JSON message and command parser

#define DHTPIN 3
#define DHTTYPE DHT22
#define ONE_WIRE_BUS 4
#define ESP_POWER_PIN_A 7
#define ESP_POWER_PIN_B 6

#define UVOUT A0
#define REF_3V3 A1
#define WIND_SENSOR A4
#define VOLTAGE_OUT A2

#define MESSAGE_LEN 200
#define ESP_SILENCE_LIMIT_S 600.0     // 10 minutes without [Send]: power-cycle the ESP32-CAM
#define ESP_OFF_TIME_MS 20000UL

//========================= DEBUG INFO ============================//
bool debugFlag = false;               // true prints debug lines on the same serial line the ESP32-CAM listens to

//====================== Global state =========================//
mt_accum acc;                         // running sums since the last [Send]
mt_cmd_parser parser;
bool sendReceived = false;
float arduino_on_time = millis() / 1000.0;

OneWire oneWire(ONE_WIRE_BUS);
DallasTemperature sensors(&oneWire);
DHT dht(DHTPIN, DHTTYPE);

void printSerial(const String &message) {
  if (debugFlag) Serial.print(message);
}

void printlnSerial(const String &message) {
  printSerial(message + "\n");
}

void clearSerialBuffer() {
  while (Serial.available() > 0) Serial.read();
}

// Power-cycles the ESP32-CAM and restarts the sensors.
void reinitialize() {
  float start_time_ESP32_off = millis() / 1000.0;

  mt_accum_reset(&acc);
  mt_cmd_init(&parser);
  sendReceived = false;
  clearSerialBuffer();

  digitalWrite(ESP_POWER_PIN_A, LOW);
  digitalWrite(ESP_POWER_PIN_B, LOW);
  wdt_disable();                      // the long pause below would trip the watchdog

  delay(ESP_OFF_TIME_MS);

  wdt_enable(WDTO_8S);
  digitalWrite(ESP_POWER_PIN_A, HIGH);
  digitalWrite(ESP_POWER_PIN_B, HIGH);

  sensors.begin();
  dht.begin();

  float end_time_ESP32_off = millis() / 1000.0;
  printSerial("ESP32 off time diff: ");
  printlnSerial(String(end_time_ESP32_off - start_time_ESP32_off) + " seconds");
}

// Answers one command received from the ESP32-CAM.
void doAction() {
  if (mt_cmd_is(&parser, "Send")) {
    sendReceived = true;
    arduino_on_time = millis() / 1000.0;
    char msg[MESSAGE_LEN];
    float battery = mt_battery_voltage(analogRead(VOLTAGE_OUT));
    if (mt_build_message(msg, sizeof msg, &acc, battery) > 0) Serial.println(msg);
    mt_accum_reset(&acc);             // start a new averaging window
  }
  if (mt_cmd_is(&parser, "ResetESP32")) {
    reinitialize();
    arduino_on_time = millis() / 1000.0;
  }
}

void setup() {
  pinMode(LED_BUILTIN, OUTPUT);
  pinMode(ESP_POWER_PIN_A, OUTPUT);
  pinMode(ESP_POWER_PIN_B, OUTPUT);
  digitalWrite(ESP_POWER_PIN_A, LOW);
  digitalWrite(ESP_POWER_PIN_B, LOW);
  delay(1000);
  digitalWrite(ESP_POWER_PIN_A, HIGH);
  digitalWrite(ESP_POWER_PIN_B, HIGH);

  Serial.begin(115200);

  pinMode(UVOUT, INPUT);
  pinMode(REF_3V3, INPUT);
  pinMode(VOLTAGE_OUT, INPUT);

  sensors.begin();
  dht.begin();

  mt_accum_reset(&acc);
  mt_cmd_init(&parser);

  wdt_enable(WDTO_8S);
}

void loop() {
  wdt_reset();
  float start_loop_time = millis() / 1000.0;
  sendReceived = false;

  digitalWrite(LED_BUILTIN, HIGH);
  delay(1000);
  digitalWrite(LED_BUILTIN, LOW);

  //========================== UV sensor ==============================//
  float uv = mt_uv_intensity(averageAnalogRead(UVOUT), averageAnalogRead(REF_3V3));

  //=========================== Dallas ===============================//
  sensors.requestTemperatures();
  mt_accum_add_dallas(&acc, 0, sensors.getTempCByIndex(0));
  mt_accum_add_dallas(&acc, 1, sensors.getTempCByIndex(1));

  //=========================== DHT ==================================//
  mt_accum_add_dht(&acc, dht.readTemperature(), dht.readHumidity());

  //======================== Wind sensor ============================//
  analogRead(WIND_SENSOR);            // the first reading after a pause is discarded
  delay(20);
  float wind = mt_wind_speed(analogRead(WIND_SENSOR));

  mt_accum_tick(&acc, uv, wind);

  //======================== Commands from the ESP32-CAM ============//
  while (Serial.available() > 0) {
    char received = Serial.read();
    if (mt_cmd_feed(&parser, received)) {
      Serial.println(parser.buf);
      Serial.flush();
      Serial.end();                   // restart the serial port to clear its buffer
      Serial.begin(115200);
      doAction();
    }
  }

  float end_loop_time = millis() / 1000.0;
  printlnSerial("loop time difference: " + String(end_loop_time - start_loop_time));

  // If [Send] has not arrived for 10 minutes, hard-reset the ESP32-CAM.
  float silent_for = end_loop_time - arduino_on_time;
  printlnSerial("arduino on time diff: " + String(silent_for));
  if (silent_for > ESP_SILENCE_LIMIT_S && sendReceived == false) {
    reinitialize();
    arduino_on_time = millis() / 1000.0;
  }
}

// Mean of 8 analog readings, to smooth out noise.
int averageAnalogRead(int pinToRead) {
  byte numberOfReadings = 8;
  unsigned int runningValue = 0;
  for (int x = 0; x < numberOfReadings; x++) runningValue += analogRead(pinToRead);
  runningValue /= numberOfReadings;
  return runningValue;
}
