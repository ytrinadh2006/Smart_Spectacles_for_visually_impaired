/*
 * Smart Specs — Audio Player
 * ===========================
 * Plays speech clips through the PAM8403 amp using the ESP32's sigma-delta
 * peripheral on GPIO14 (both DAC pins are taken by the camera).
 *
 * Direct-connect wiring (no filter parts):
 *   GPIO14 -> PAM8403 L-IN + R-IN (tied together)
 *   GND    -> PAM8403 GND
 * The PAM8403's input caps block DC and the amp/speakers can't reproduce
 * the 312 kHz carrier, so it acts as its own filter. Loudness is set in
 * software via AUDIO_VOLUME (the amp has fixed 24 dB gain).
 *
 * Clip format: raw headerless PCM, 16 kHz, mono, unsigned 8-bit — fetched
 * from the Pi (GET /audio/<name>.pcm) into PSRAM, played by a timer ISR.
 */

#pragma once

#include <HTTPClient.h>

#define AUDIO_PIN          14
#define AUDIO_SAMPLE_RATE  16000
#define AUDIO_VOLUME       0.50f   // 50% — reduce distortion until RC filter added
#define AUDIO_BUF_SIZE     (80 * 1024)  // PSRAM buffer — fits full speech clips
#define AUDIO_TEST_TONE    0       // 0 = real speech from Pi, 1 = test beep only

static uint8_t* audioBuf = nullptr;
static volatile uint32_t audioLen = 0;
static volatile uint32_t audioIdx = 0;
static volatile bool audioPlaying = false;
static volatile int audioPrio = 0;
static hw_timer_t* audioTimer = nullptr;

void IRAM_ATTR onAudioSample() {
    if (audioIdx < audioLen) {
        sigmaDeltaWrite(AUDIO_PIN, audioBuf[audioIdx++]);
    } else {
        sigmaDeltaWrite(AUDIO_PIN, 128);  // back to midpoint = silence
        timerStop(audioTimer);
        audioPlaying = false;
    }
}

bool audioInit() {
    // Use PSRAM for large audio buffer
    audioBuf = (uint8_t*) ps_malloc(AUDIO_BUF_SIZE);
    if (!audioBuf) {
        // Fallback to DRAM if PSRAM not ready
        audioBuf = (uint8_t*) malloc(32 * 1024);
    }
    if (!audioBuf) {
        Serial.println("Audio: buffer alloc FAILED — no audio!");
        return false;
    }
    Serial.printf("Audio: buffer OK (%d bytes)\n", AUDIO_BUF_SIZE);
    // 1MHz carrier — above speaker/amp range, much less audible noise than 312kHz
    if (!sigmaDeltaAttach(AUDIO_PIN, 1000000)) {
        Serial.println("Audio: sigmaDeltaAttach failed!");
        return false;
    }
    sigmaDeltaWrite(AUDIO_PIN, 128);  // idle at midpoint (no DC step/thump)

    // 2 MHz timer / 125 ticks = exactly 16 kHz sample clock
    audioTimer = timerBegin(2000000);
    timerAttachInterrupt(audioTimer, &onAudioSample);
    timerAlarm(audioTimer, 2000000 / AUDIO_SAMPLE_RATE, true, 0);
    timerStop(audioTimer);  // armed but idle until a clip starts

    Serial.printf("Audio ready — GPIO%d, %d Hz, volume %.0f%%\n",
                  AUDIO_PIN, AUDIO_SAMPLE_RATE, AUDIO_VOLUME * 100);
    return true;
}

void stopAudio() {
    if (audioTimer) timerStop(audioTimer);
    audioPlaying = false;
    sigmaDeltaWrite(AUDIO_PIN, 128);
}

static void startPlayback(uint32_t len, int prio) {
    audioLen = len;
    audioIdx = 0;
    audioPrio = prio;
    audioPlaying = true;
    timerRestart(audioTimer);
    timerStart(audioTimer);
}

// Fetch a clip from the Pi and start playing it.
// Priority rule: prio-3 (danger) interrupts a lower-prio clip already playing;
// anything else is dropped — never queued, the next frame re-decides.
void maybePlay(const String& url, int prio) {
    if (audioPlaying) {
        if (prio >= 3 && prio > audioPrio) {
            stopAudio();  // danger interrupts chatter
        } else {
            return;
        }
    }

    HTTPClient http;
    http.begin(String("http://192.168.12.42:5000") + url);
    http.setTimeout(3000);
    int code = http.GET();
    if (code != 200) {
        Serial.printf("  Audio fetch failed: %d (%s)\n", code, url.c_str());
        http.end();
        return;
    }

    WiFiClient* stream = http.getStreamPtr();
    int total = http.getSize();  // may be -1 (chunked); buffer bound applies anyway
    uint32_t got = 0;
    unsigned long deadline = millis() + 3000;
    while (http.connected() && millis() < deadline && got < AUDIO_BUF_SIZE) {
        size_t avail = stream->available();
        if (!avail) { delay(2); continue; }
        size_t n = stream->readBytes(audioBuf + got, min(avail, (size_t)(AUDIO_BUF_SIZE - got)));
        got += n;
        if (total > 0 && got >= (uint32_t)total) break;
    }
    http.end();

    if (got < AUDIO_SAMPLE_RATE / 10) {  // less than 0.1s of audio — junk
        Serial.printf("  Audio fetch too short: %u bytes\n", got);
        return;
    }

    // Apply software volume: scale swing around the 128 midpoint
    for (uint32_t i = 0; i < got; i++) {
        audioBuf[i] = 128 + (int)((audioBuf[i] - 128) * AUDIO_VOLUME);
    }

    Serial.printf("  Speaking: %s (%u bytes, %.1fs, prio %d)\n",
                  url.c_str(), got, (float)got / AUDIO_SAMPLE_RATE, prio);
    startPlayback(got, prio);
}

#if AUDIO_TEST_TONE
// 2s 440Hz sine — validates GPIO14 -> PAM8403 -> speakers with no Pi involved
void playTestTone() {
    uint32_t n = AUDIO_SAMPLE_RATE * 2;
    for (uint32_t i = 0; i < n; i++) {
        float s = sinf(2.0f * PI * 440.0f * i / AUDIO_SAMPLE_RATE);
        audioBuf[i] = 128 + (int)(s * 127.0f * AUDIO_VOLUME);
    }
    Serial.println("Audio: playing 2s test tone...");
    startPlayback(n, 0);
}
#endif
