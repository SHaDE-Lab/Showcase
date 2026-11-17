/*
 * MaRTiny: ESP32-CAM sketch.
 *
 * Every cycle: take a photo and upload it, ask the Arduino Uno for its sensor averages with [Send], upload them, and restart.
 * Network name, password and server address come from config.h (copy config.example.h and edit it; config.h is not committed).
 * The URL encoding, the JSON collector and the upload header live in martiny_net.h, which is tested on a PC (see tests/).
 *
 * Copyright 2026 The SHaDE Lab, Arizona State University
 * This source describes Open Hardware and is licensed under the CERN-OHL-P v2.
 * You may redistribute and modify this source and make products using it under the terms of the
 * CERN-OHL-P v2 (https://ohwr.org/cern_ohl_p_v2.txt).
 * This source is distributed WITHOUT ANY EXPRESS OR IMPLIED WARRANTY, INCLUDING OF MERCHANTABILITY,
 * SATISFACTORY QUALITY AND FITNESS FOR A PARTICULAR PURPOSE.
 * Please see the CERN-OHL-P v2 for applicable conditions.
 */
#include <esp_task_wdt.h>
#include <WiFi.h>
#include <Wire.h>
#include <HTTPClient.h>
#include "esp_camera.h"
#include "soc/soc.h"
#include "soc/rtc_cntl_reg.h"

#define WDT_TIMEOUT 120

#define CAMERA_MODEL_AI_THINKER
/***************************************
 *  Settings (see config.example.h)
 **************************************/
#if defined(__has_include)
#if !__has_include("config.h")
#error "config.h is missing: copy config.example.h to config.h and fill in your Wi-Fi and server settings."
#endif
#endif
#include "config.h"
#include "martiny_net.h"

unsigned long sendInterval = 1;
unsigned long sendIntervalMillis = sendInterval * 1000;
unsigned long nextSend = millis();
int lastSendSec = -1;
String mac_address;

bool cam_status = false;
/***************************************
 *  Function
 **************************************/

#include "select_pins.h"

#if defined(SOFTAP_MODE)
#endif
String macAddress = "";
String ipAddress = "ip";

// extern void startCameraServer();

bool deviceProbe(uint8_t addr)
{
    Wire.beginTransmission(addr);
    return Wire.endTransmission() == 0;
}

bool setupCamera()
{
    delay(1000);
    camera_config_t config;

    #if defined(Y2_GPIO_NUM)
        config.ledc_channel = LEDC_CHANNEL_0;
        config.ledc_timer = LEDC_TIMER_0;
        config.pin_d0 = Y2_GPIO_NUM;
        config.pin_d1 = Y3_GPIO_NUM;
        config.pin_d2 = Y4_GPIO_NUM;
        config.pin_d3 = Y5_GPIO_NUM;
        config.pin_d4 = Y6_GPIO_NUM;
        config.pin_d5 = Y7_GPIO_NUM;
        config.pin_d6 = Y8_GPIO_NUM;
        config.pin_d7 = Y9_GPIO_NUM;
        config.pin_xclk = XCLK_GPIO_NUM;
        config.pin_pclk = PCLK_GPIO_NUM;
        config.pin_vsync = VSYNC_GPIO_NUM;
        config.pin_href = HREF_GPIO_NUM;
        config.pin_sscb_sda = SIOD_GPIO_NUM;
        config.pin_sscb_scl = SIOC_GPIO_NUM;
        config.pin_pwdn = PWDN_GPIO_NUM;
        config.pin_reset = RESET_GPIO_NUM;
        config.xclk_freq_hz = 20000000;
        config.pixel_format = PIXFORMAT_JPEG;
        //init with high specs to pre-allocate larger buffers
        if (psramFound()) 
        {
            config.frame_size = FRAMESIZE_UXGA;
            config.jpeg_quality = 10;
            config.fb_count = 2;
        } else 
        {
            config.frame_size = FRAMESIZE_SVGA;
            config.jpeg_quality = 12;
            config.fb_count = 1;
        }
    #endif

    #if defined(ESPRESSIF_ESP_EYE) || defined(T_Camera_V162_VERSION) || defined(T_Camera_MINI_VERSION)
        /* IO13, IO14 is designed for JTAG by default,
         * to use it as generalized input,
         * firstly declair it as pullup input */
        pinMode(13, INPUT_PULLUP);
        pinMode(14, INPUT_PULLUP);
    #endif

    // camera init
    esp_err_t err = esp_camera_init(&config);
    if (err != ESP_OK) {
        //Serial.printf("Camera init failed with error 0x%x\n", err);
        return false;
    }

    sensor_t *s = esp_camera_sensor_get();
    //initial sensors are flipped vertically and colors are a bit saturated
    if (s->id.PID == OV3660_PID) {
        s->set_vflip(s, 1);//flip it back
        s->set_brightness(s, 1);//up the blightness just a bit
        s->set_saturation(s, -2);//lower the saturation
    }
    //drop down frame size for higher initial frame rate
    s->set_framesize(s, FRAMESIZE_VGA);

    #if  defined(T_Camera_V162_VERSION)
        s->set_vflip(s, 1);
        s->set_hmirror(s, 1);
    #endif
    return true;
}

void setupNetwork()
{
    delay(1000);
    macAddress = "";
    
    #ifdef SOFTAP_MODE
        WiFi.softAP(MARTINY_SOFTAP_SSID);  
    #else
        WiFi.begin(MARTINY_WIFI_SSID, MARTINY_WIFI_PASSWORD);
        int retriesWifi = 0;
        while (WiFi.status() != WL_CONNECTED) 
        {
          delay(500);
          Serial.print(".");
          retriesWifi++;
          
          if(retriesWifi >= 200)
            esp_restart();
        }
        Serial.println("");
        Serial.println("WiFi connected");
        ipAddress = WiFi.localIP().toString();
    #endif
    #if defined(ENABLE_TFT)
    #if defined(T_Camera_PLUS_VERSION)
        tft.drawString("ipAddress:", tft.width() / 2, tft.height() / 2 + 50);
        tft.drawString(ipAddress, tft.width() / 2, tft.height() / 2 + 72);
    #endif
    #endif
}

void setup()
{
    WRITE_PERI_REG(RTC_CNTL_BROWN_OUT_REG, 0);
    pinMode(33, OUTPUT);
    digitalWrite(33, LOW);
    delay(100);
    digitalWrite(33, HIGH);
    Serial.begin(115200);

    #if defined(I2C_SDA) && defined(I2C_SCL)
        Wire.begin(I2C_SDA, I2C_SCL);
    #endif
    
    // setup WDT
    esp_task_wdt_init(WDT_TIMEOUT, true); //enable panic so ESP32 restarts
    esp_task_wdt_add(NULL); //add current thread to WDT watch

    // bool status;
    cam_status = setupCamera();
    
    Serial.print("setupCamera status "); 
    Serial.println(cam_status);
    // if (!status){
    //     delay(10000); esp_restart();
    // }
    
    setupNetwork();

//    startCameraServer();

    Serial.print("Camera Ready! Use 'http://");
    Serial.print(ipAddress);
    Serial.println("' to connect");
    mac_address = WiFi.macAddress();
    Serial.println(mac_address);
}

mt_json_collector collector;       // picks {...} out of the serial stream from the Arduino Uno

void receiveJSON() {
  mt_json_init(&collector);
  while (Serial.available() > 0)
  {
    char received = Serial.read();
    if (mt_json_feed(&collector, received))
    {
      Serial.println("stop receiving");
      Serial.println(collector.buf);
      sendSensorData(String(collector.buf));
      Serial.flush();
      mt_json_init(&collector);
    }
  }
  Serial.print("In data: ");
  Serial.println(collector.buf);
}

String serverName = MARTINY_SERVER_HOST;
String serverPath = MARTINY_IMAGE_PATH;
const int serverPort = MARTINY_IMAGE_PORT;

WiFiClient client;

String sendPhoto() 
{
  String getAll = "";
  String getBody = "";

  camera_fb_t * fb = NULL;
  fb = esp_camera_fb_get();
  if(!fb) 
  {
    Serial.println("Camera capture failed");
    delay(1000);
    esp_restart();
  }
  
  Serial.println("Connecting to server: " + serverName);

  if (client.connect(serverName.c_str(), serverPort)) 
  {
    Serial.println("Connection successful!");  
    
    char deviceId[24];
    mt_device_id(mac_address.c_str(), deviceId, sizeof deviceId);

    // Craft HTTPBody
    char headBuf[320];
    int headLen = mt_multipart_head(headBuf, sizeof headBuf, deviceId);
    String httpBody = String(headBuf);
    String HTTPtail = MT_MULTIPART_TAIL;

    uint32_t imageLen = fb->len;
    uint32_t extraLen = (headLen > 0 ? headLen : 0) + HTTPtail.length();
    uint32_t totalLen = imageLen + extraLen;
    
    // Craft HTTP request - Add header
    client.println("POST " + serverPath + " HTTP/1.1");
    client.println("Host: " + serverName);
    client.println("Content-Length: " + String(totalLen));
    client.println("Content-Type: multipart/form-data; boundary=" MT_BOUNDARY);
    client.println();    

    // Add body
    client.print(httpBody);

    // Add image
    uint8_t *fbBuf = fb->buf;
    size_t fbLen = fb->len;
    for (size_t n=0; n<fbLen; n=n+1024) 
    {
      if (n+1024 < fbLen) 
      {
        client.write(fbBuf, 1024);
        fbBuf += 1024;
      }
      else if (fbLen%1024>0) 
      {
        size_t remainder = fbLen%1024;
        client.write(fbBuf, remainder);
      }
    }

    // Add HTTP tail
    client.print(HTTPtail);
    
    esp_camera_fb_return(fb);
    
    int timoutTimer = 10000;
    long startTimer = millis();
    boolean state = false;
    
//    while ((startTimer + timoutTimer) > millis()) 
//    {
//      Serial.print(".");
//      delay(100);      
//      while (client.available()) 
//      {
//        char c = client.read();
//        if (c == '\n') 
//        {
//          if (getAll.length()==0) { state=true; }
//          getAll = "";
//        }
//        else if (c != '\r') { getAll += String(c); }
//        if (state==true) { getBody += String(c); }
//        startTimer = millis();
//      }
//      if (getBody.length()>0) { break; }
//    }
//    Serial.println();
    client.stop();
//    Serial.println(getBody);
  }
  else 
  {
    getBody = "Connection to " + serverName +  " failed.";
    Serial.println(getBody);
  }
  return getBody;
}

HTTPClient http;

void sendSensorData(String s)
{
  char encData[MT_JSON_MAX * 3 + 1], encMac[64];
  if (mt_urlencode(s.c_str(), encData, sizeof encData) < 0 || mt_urlencode(mac_address.c_str(), encMac, sizeof encMac) < 0)
  {
    Serial.println("Sensor data too long to send");
    return;
  }
  String serverName = String("http://") + MARTINY_SERVER_HOST + ":" + String(MARTINY_DATA_PORT) + MARTINY_DATA_PATH;
  String serverPath = serverName + "?data=" + encData + "&mac=" + encMac;
  Serial.println(serverPath);
      
  // Your Domain name with URL path or IP address with path
  http.begin(serverPath.c_str());
  
  // Send HTTP GET request
  int httpResponseCode = http.GET();
  
  if (httpResponseCode>0) 
  {
    Serial.print("HTTP Response code: ");
    Serial.println(httpResponseCode);
//    String payload = http.getString();
//    Serial.println(payload);
  }
  else 
  {
    Serial.print("Error code: ");
    Serial.println(httpResponseCode);
  }
  // Free resources
  http.end();
}
