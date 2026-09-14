# Smart Specs 👓

[![License: MIT](https://img.shields.io/badge/License-MIT-blue.svg)](LICENSE)
[![Platform: ESP32-CAM](https://img.shields.io/badge/Platform-ESP32--CAM-red.svg)](https://www.espressif.com/)
[![Edge AI: Raspberry Pi Zero 2W](https://img.shields.io/badge/Edge%20AI-Raspberry%20Pi%20Zero%202W-brightgreen.svg)](https://www.raspberrypi.com/)
[![Model: YOLOv8 Quantized INT8](https://img.shields.io/badge/Model-YOLOv8%20(INT8%20TFLite)-orange.svg)](https://github.com/ultralytics/ultralytics)

> **AI-Powered Wearable Navigation Assistant for the Visually Impaired**  
> Real-time obstacle detection, spatial tracking, and low-latency directional audio feedback designed for complex outdoor and indoor navigation environments.

---

## 📌 System Architecture

```
                                    +-----------------------------------------------+
                                    |          Smart Specs Wearable Frame           |
                                    |                                               |
                                    |  +------------+         +------------------+  |
                                    |  |   OV2640   |  FPC    |    ESP32-CAM     |  |
                                    |  | 2MP Camera |-------->|  Wireless Node   |  |
                                    |  +------------+         +--------+---------+  |
                                    |                                  |            |
                                    |  +------------+                  | GPIO 14    |
                                    |  | 2x Speakers|<-----+           v (PWM)      |
                                    |  |  (8Ω, 1W)  |      |   +-----------------+  |
                                    |  +------------+      +---|     PAM8403     |  |
                                    |                          | Audio Amplifier |  |
                                    |                          +-----------------+  |
                                    +----------------------------------+------------+
                                                                       |
                                                Wi-Fi (HTTP POST)      |  Wi-Fi (PCM Audio)
                                                Frames @ 1-2 FPS       v  Low-latency stream
                                    +-----------------------------------------------+
                                    |       Edge Computing Unit (In Pocket)         |
                                    |                                               |
                                    |          Raspberry Pi Zero 2W                 |
                                    |  - Flask Inference Server                     |
                                    |  - YOLOv8 (INT8 TFLite) ~100ms inference      |
                                    |  - Cross-frame Object Tracker                 |
                                    |  - Context-aware Audio Feedback Announcer     |
                                    +-----------------------------------------------+
```

---

## 🎯 Supported Detection Classes (10 Classes)

The integrated quantized YOLOv8 model runs on the Pi Zero 2W with ~100ms inference time:

| Class | Type | Directional Warning |
|---|---|---|
| **Pothole** | Hazard | Immediate hazard warning (center / left / right) |
| **Vehicle** | Hazard | Approach / receding motion tracking |
| **Obstacle** | Hazard | Proximity & spatial alert |
| **Stairs** | Structure | Step level warning |
| **Safe Path** | Navigation | Confirms unobstructed walkway |
| **Person** | Dynamic | Pedestrian tracking & avoidance |
| **Speed Bump** | Structure | Ground surface change alert |
| **Traffic Light**| Navigation | Signal state announcement |
| **Door** | Structure | Entrance / exit detection |
| **Animal** | Dynamic | Approach warning |

---

## 🧰 Hardware Bill of Materials (BOM)

| Component | Specification | Function |
|---|---|---|
| **ESP32-CAM** | AI-Thinker (ESP32-S + OV2640) | Image capture & audio playback node |
| **Camera Ribbon** | 75mm 24-pin FPC cable | Center frame camera placement |
| **Raspberry Pi Zero 2W** | Quad-core 1GHz, 512MB RAM | Mobile edge AI inference engine |
| **Audio Amplifier** | PAM8403 3W+3W Stereo Class-D | Audio amplification |
| **Mini Speakers** | 2x 24x15mm Oval 8Ω 1W | Left and right binaural directional audio |
| **Battery** | 3.7V LiPo Cell (420mAh+ / Parallel) | Lightweight wearable power |
| **Charger** | TP4056 USB-C Module | Li-ion battery charging with protection |
| **Boost Converter** | MT3608 Step-up Module | Boosts 3.7V $\rightarrow$ regulated 5.0V |
| **Frame** | Custom 3D Printed Frame (PLA/PETG) | Ergonomic eyewear housing |

Detailed wiring and schematics can be found in [docs/wiring_guide.md](docs/wiring_guide.md).

---

## 📂 Repository Structure

```
smart-specs/
├── docs/                   # Schematics, 3D specs, and wiring guides
│   ├── wiring_guide.md
│   ├── smart_specs_architecture.svg
│   └── smart_specs_3d_reference.html
├── firmware/               # ESP32-CAM source code
│   └── smart_specs_cam/
│       ├── smart_specs_cam.ino   # Core camera loop & OTA updates
│       └── audio_player.h        # Sigma-delta PCM audio driver
├── server/                 # Raspberry Pi edge inference software
│   ├── server.py                 # Flask server & REST API
│   ├── inference.py              # TFLite YOLOv8 inference wrapper
│   ├── tracker.py                # Cross-frame IoU & motion tracker
│   ├── announcer.py              # Prioritized speech alert selector
│   ├── phrases.py                # Alert templates & vocabulary
│   ├── gen_audio.py              # Offline speech clip synthesizer
│   ├── setup.sh                  # One-click Pi environment installer
│   └── requirements.txt          # Python dependencies
├── model/                  # Deep learning models & metrics
│   ├── best_int8.tflite          # Quantized edge deployment model
│   ├── labels.txt                # 10-class labels
│   ├── data.yaml                 # Dataset configuration
│   └── training_metrics/         # Loss, mAP, and training rounds
└── hardware/               # CAD & OpenSCAD models
    └── 3d_models/
        ├── smart_specs_frame.scad
        └── smart_specs_v2.scad
```

---

## 🚀 Quick Start & Setup

### 1. Raspberry Pi Setup
```bash
# Clone the repository
git clone https://github.com/<YOUR_GROUP>/smart-specs.git
cd smart-specs/server

# Run the automated setup script
chmod +x setup.sh
./setup.sh

# Run the inference server
source venv/bin/activate
python3 server.py
```

### 2. ESP32-CAM Firmware
1. Open `firmware/smart_specs_cam/smart_specs_cam.ino` in the **Arduino IDE**.
2. Select Board: **AI Thinker ESP32-CAM**.
3. Partition Scheme: **Minimal SPIFFS (1.9MB APP with OTA/190KB SPIFFS)**.
4. Update `WIFI_SSID`, `WIFI_PASSWORD`, and `SERVER_URL` with your network configuration.
5. Upload via USB using the ESP32-CAM-MB programmer board.
6. Subsequent updates can be flashed Over-The-Air (OTA) over Wi-Fi.

---

## 👥 Project Team & Contributors

This project was created collaboratively by:
- **Member 1** - *System Architecture, Firmware & Edge Server*
- **Member 2** - *Machine Learning & Model Quantization*
- **Member 3** - *Hardware Assembly, Circuit & Power Subsystem*
- **Member 4** - *3D CAD Modeling & Ergonomic Frame Design*
- **Member 5** - *Audio Feedback Pipeline & Field Testing*

---

## 📄 License
This project is open source and available under the [MIT License](LICENSE).
