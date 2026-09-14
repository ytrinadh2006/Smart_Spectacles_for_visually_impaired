/*
 * Smart Specs — ESP32-CAM Firmware
 * =================================
 * Captures images and sends them to the Raspberry Pi
 * detection server via HTTP POST.
 *
 * Board: AI Thinker ESP32-CAM-MB with OV2640 camera
 * Upload speed: 115200
 * After first flash: updates via WiFi OTA
 */

#include "esp_camera.h"
#include <WiFi.h>
#include <HTTPClient.h>
#include <ArduinoOTA.h>
#include "audio_player.h"

// ==========================================
// CONFIGURATION
// ==========================================
const char* FW_VERSION = "v6.0";  // change this each time
// Connect to your laptop hotspot (same network as Pi)
const char* WIFI_SSID     = "wifi";       // Your laptop hotspot SSID
const char* WIFI_PASSWORD = "12345678";       // Your laptop hotspot password

// Pi's IP on the laptop hotspot network
const char* SERVER_URL = "http://192.168.12.42:5000/detect";
const char* HEALTH_URL = "http://192.168.12.42:5000/health";

// Capture every N milliseconds
const int CAPTURE_INTERVAL_MS = 1000;

// JPEG quality: 10=best/large, 63=worst/small
const int JPEG_QUALITY = 12;

// ==========================================
// ESP32-CAM Pin definitions (AI Thinker)
// ==========================================
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
#define LED_GPIO           4  // Built-in flash LED
#define STATUS_LED        33  // Small red LED (active LOW — LOW=ON)

// ==========================================
// Global state
// ==========================================
int frameCount   = 0;
int successCount = 0;
int failCount    = 0;

// ==========================================
// Camera initialization
// ==========================================
bool initCamera() {
    camera_config_t config;
    config.ledc_channel = LEDC_CHANNEL_0;
    config.ledc_timer   = LEDC_TIMER_0;
    config.pin_d0       = Y2_GPIO_NUM;
    config.pin_d1       = Y3_GPIO_NUM;
    config.pin_d2       = Y4_GPIO_NUM;
    config.pin_d3       = Y5_GPIO_NUM;
    config.pin_d4       = Y6_GPIO_NUM;
    config.pin_d5       = Y7_GPIO_NUM;
    config.pin_d6       = Y8_GPIO_NUM;
    config.pin_d7       = Y9_GPIO_NUM;
    config.pin_xclk     = XCLK_GPIO_NUM;
    config.pin_pclk     = PCLK_GPIO_NUM;
    config.pin_vsync    = VSYNC_GPIO_NUM;
    config.pin_href     = HREF_GPIO_NUM;
    config.pin_sccb_sda = SIOD_GPIO_NUM;
    config.pin_sccb_scl = SIOC_GPIO_NUM;
    config.pin_pwdn     = PWDN_GPIO_NUM;
    config.pin_reset    = RESET_GPIO_NUM;
    config.xclk_freq_hz = 10000000;  // 10MHz — reduces FB-OVF overflow spam
    config.pixel_format = PIXFORMAT_JPEG;
    config.grab_mode    = CAMERA_GRAB_WHEN_EMPTY;

    // Start with lower resolution — works reliably for all sensors
    // We will step up after init if PSRAM is available
    config.frame_size   = FRAMESIZE_QVGA;  // 320x240 for safe init
    config.jpeg_quality = JPEG_QUALITY;
    config.fb_count     = 1;

    if (psramFound()) {
        Serial.println("  PSRAM found");
        config.fb_location = CAMERA_FB_IN_PSRAM;
        config.fb_count    = 2;
        config.grab_mode   = CAMERA_GRAB_LATEST;
    } else {

        Serial.println("  No PSRAM, using DRAM");
        config.fb_location = CAMERA_FB_IN_DRAM;
    }

    // First init attempt
    esp_err_t err = esp_camera_init(&config);
    if (err != ESP_OK) {
        Serial.printf("  Camera init error: 0x%x\n", err);
        return false;
    }

    // Silence cam_hal FB-OVF spam in serial monitor
    esp_log_level_set("cam_hal", ESP_LOG_ERROR);
    esp_log_level_set("s3 ll_cam", ESP_LOG_ERROR);

    // Get sensor info
    sensor_t* s = esp_camera_sensor_get();
    if (!s) {
        Serial.println("  Could not get sensor handle");
        return false;
    }

    Serial.printf("  Sensor PID: 0x%04x\n", s->id.PID);

    // OV2640: go straight to VGA (640x480) — no stepping needed
    if (s->id.PID == 0x3660) {
        Serial.println("  OV3660 detected — stepping up frame size...");
        delay(200);
        s->set_framesize(s, FRAMESIZE_SVGA);
        delay(200);
        s->set_framesize(s, FRAMESIZE_VGA);
        delay(200);
    } else {
        // OV2640: go straight to VGA
        Serial.println("  OV2640 detected — setting VGA directly");
        s->set_framesize(s, FRAMESIZE_VGA);
        delay(100);
    }

    // Image quality for outdoor Indian road conditions
    s->set_brightness(s, 1);    // Slightly brighter
    s->set_contrast(s, 1);      // More contrast
    s->set_saturation(s, 0);    // Normal saturation
    s->set_whitebal(s, 1);      // Auto white balance
    s->set_awb_gain(s, 1);      // AWB gain
    s->set_exposure_ctrl(s, 1); // Auto exposure
    s->set_aec2(s, 1);          // AEC DSP
    s->set_gainceiling(s, (gainceiling_t)4);

    // Warm up: take a few dummy frames and discard
    Serial.println("  Warming up camera...");
    for (int i = 0; i < 3; i++) {
        camera_fb_t* fb = esp_camera_fb_get();
        if (fb) {
            esp_camera_fb_return(fb);
        }
        delay(100);
    }

    return true;
}

// ==========================================
// WiFi connection
// ==========================================
void connectWiFi() {
    Serial.printf("Connecting to WiFi: %s", WIFI_SSID);

    WiFi.mode(WIFI_STA);
    WiFi.setSleep(false);

    WiFi.begin(WIFI_SSID, WIFI_PASSWORD);

    int attempts = 0;
    while (WiFi.status() != WL_CONNECTED && attempts < 40) {
        delay(500);
        Serial.print(".");
        attempts++;
    }

    if (WiFi.status() == WL_CONNECTED) {
        Serial.println(" Connected!");
        Serial.printf("  ESP32 IP: %s\n", WiFi.localIP().toString().c_str());
        Serial.printf("  RSSI:     %d dBm\n", WiFi.RSSI());
    } else {
        Serial.println(" FAILED!");
        Serial.println("  Make sure the Pi hotspot is running.");
        Serial.println("  Run on Pi: sudo ./setup_hotspot.sh");
        Serial.println("  Rebooting in 5s...");
        delay(5000);
        ESP.restart();
    }
}

// ==========================================
// Wait for Pi server to be ready
// ==========================================
void waitForServer() {
    Serial.printf("Waiting for Pi server at %s", SERVER_URL);

    for (int i = 0; i < 3; i++) {  // Only 3 attempts (was 20)
        ArduinoOTA.handle();  // Keep OTA responsive during wait
        HTTPClient http;
        http.begin(HEALTH_URL);

        int code = http.GET();
        if (code == 200) {
            Serial.println(" Ready!");
            http.end();
            return;
        }
        http.end();
        Serial.print(".");
        // OTA-friendly wait instead of blocking delay
        unsigned long w = millis() + 1000;
        while (millis() < w) { ArduinoOTA.handle(); delay(10); }
    }
    Serial.println("\n  Server not responding — starting capture anyway");
}

// ==========================================
// OTA (Over-the-Air) update setup
// ==========================================
void setupOTA() {
    ArduinoOTA.setHostname("smartspecs-cam");
    ArduinoOTA.setPassword("0102");  // OTA upload password

    ArduinoOTA.onStart([]() {
        Serial.println("OTA update starting...");
        stopAudio();          // silence + stop the sample timer ISR
        esp_camera_deinit();  // free camera DMA/PSRAM so flash write isn't disturbed
    });
    ArduinoOTA.onEnd([]() {
        Serial.println("\nOTA update done! Rebooting.");
    });
    ArduinoOTA.onProgress([](unsigned int progress, unsigned int total) {
        Serial.printf("OTA Progress: %u%%\r", (progress / (total / 100)));
    });
    ArduinoOTA.onError([](ota_error_t error) {
        Serial.printf("OTA Error[%u]: ", error);
    });

    ArduinoOTA.begin();
    Serial.println("OTA ready — hostname: smartspecs-cam");
    Serial.println("  Upload via: Arduino IDE > Tools > Port > smartspecs-cam");
}

// ==========================================
// Send image via HTTP POST
// ==========================================
bool sendImage(uint8_t* data, size_t len) {
    if (WiFi.status() != WL_CONNECTED) return false;

    HTTPClient http;
    http.begin(SERVER_URL);
    http.setTimeout(8000);  // 8s timeout — gives OTA more windows to respond
    http.addHeader("Content-Type", "image/jpeg");

    unsigned long t0 = millis();
    int code = http.POST(data, len);
    unsigned long ms = millis() - t0;

    if (code == 200) {
        String response = http.getString();
        Serial.printf("  OK (%lums): %s\n", ms, response.c_str());

        // Double-blink LED if objects were detected
        bool hasDetections = response.indexOf("\"count\":0") == -1 &&
                             response.indexOf("\"count\": 0") == -1 &&
                             response.indexOf("\"detections\":[]") == -1;
        if (hasDetections) {
            for (int b = 0; b < 2; b++) {
                digitalWrite(LED_GPIO, HIGH); delay(80);
                digitalWrite(LED_GPIO, LOW);  delay(80);
            }
        }

        // Speak the announcement the Pi picked (if any)
        int p = response.indexOf("\"speak_url\":\"");
        if (p >= 0) {
            int endq = response.indexOf('"', p + 13);
            String url = (endq > p) ? response.substring(p + 13, endq) : "";
            int q = response.indexOf("\"speak_prio\":");
            int prio = (q >= 0) ? response.substring(q + 13, q + 15).toInt() : 0;
            if (url.length() > 1) maybePlay(url, prio);
        }

        http.end();
        return true;
    } else {
        Serial.printf("  HTTP error: %d (%lums)\n", code, ms);
        http.end();
        return false;
    }
}

// ==========================================
// setup()
// ==========================================
void setup() {
    Serial.begin(115200);
    Serial.println();
    Serial.println("=========================================");
    Serial.println("  Smart Specs — ESP32-CAM");
    Serial.println("=========================================");

    pinMode(LED_GPIO, OUTPUT);
    digitalWrite(LED_GPIO, LOW);

    // Turn on small red LED as power indicator
    pinMode(STATUS_LED, OUTPUT);
    digitalWrite(STATUS_LED, LOW);  // LOW = ON

    Serial.printf("Smart Specs Firmware %s\n", FW_VERSION);
    // Init camera
    if (!initCamera()) {
        Serial.println("Camera init failed — restarting");
        delay(3000);
        ESP.restart();
    }
    Serial.println("Camera OK");

    // Init audio output (sigma-delta on GPIO14 -> PAM8403)
    audioInit();
#if AUDIO_TEST_TONE
    playTestTone();
#endif

    // Connect WiFi
    connectWiFi();

    // Setup OTA BEFORE waiting for server (so OTA works immediately)
    setupOTA();

    // Wait for server (non-blocking, OTA-friendly)
    waitForServer();

    Serial.println("Starting capture...");
    Serial.println("=========================================");
}

// ==========================================
// loop()
// ==========================================
void loop() {
    // Handle OTA updates (must be first thing in loop)
    ArduinoOTA.handle();

#if AUDIO_TEST_TONE
    // Hardware test mode: beep every 5s so soldering can be verified any time
    static unsigned long lastTone = 0;
    if (!audioPlaying && millis() - lastTone > 5000) {
        playTestTone();
        lastTone = millis();
    }
#endif

    // Reconnect WiFi if dropped
    if (WiFi.status() != WL_CONNECTED) {
        Serial.println("WiFi lost, reconnecting...");
        connectWiFi();
    }

    frameCount++;
    Serial.printf("\n[Frame %d] Capturing...\n", frameCount);

    // Flash LED during capture
    digitalWrite(LED_GPIO, HIGH);
    camera_fb_t* fb = esp_camera_fb_get();
    digitalWrite(LED_GPIO, LOW);

    if (!fb) {
        Serial.println("  Capture failed, skipping");
        failCount++;
        delay(1000);
        return;
    }

    Serial.printf("  Size: %d bytes (%dx%d)\n", fb->len, fb->width, fb->height);

    bool ok = sendImage(fb->buf, fb->len);
    esp_camera_fb_return(fb);

    if (ok) successCount++;
    else    failCount++;

    Serial.printf("  [Stats] OK:%d Fail:%d Total:%d\n", successCount, failCount, frameCount);

    // OTA-friendly wait: call handle() every 10ms instead of blocking delay
    unsigned long waitUntil = millis() + CAPTURE_INTERVAL_MS;
    while (millis() < waitUntil) {
        ArduinoOTA.handle();
        delay(10);
    }
}
