# FridgeBud

A smart fridge companion that tracks food freshness and reduces waste using AI vision, barcode scanning, sensors, and a pixel-art touchscreen interface.

## What It Does

FridgeBud is an IoT system that mounts on your refrigerator and automatically manages food inventory. A camera recognizes what you put in, a barcode scanner identifies packaged items, and an AI estimates how long everything will last — all surfaced through a playful pixel-art UI on a touchscreen.

**Goal: less food waste · easier inventory · smarter meal planning**

## Features

- **AI Food Recognition** — Real-time classification via a HuggingFace vision model (`AutoModelForImageClassification`) and USB camera
- **Barcode Scanning** — Scan product barcodes to auto-lookup and add items to inventory
- **Smart Shelf-Life Estimation** — Calls OpenAI API to estimate days until spoilage at fridge temperature, with a local fallback when offline
- **Priority Queue Inventory** — Items sorted by expiration date; expiring-soon items float to the top
- **Pixel-Art Touchscreen UI** — Built with Pygame; supports adding, removing, and editing items with animations (flying fruit, particle effects, bag shake)
- **Sensor Fusion** — Arduino firmware reads ultrasonic distance, potentiometer, and buttons, sending data to the Pi over serial
- **LCD Status Display** — 1602 LCD shows a quick fridge summary

## Architecture

```
┌───────────────┐   Serial/UART   ┌────────────────────────┐
│    Arduino     │ ─────────────▶  │     Raspberry Pi       │
│  sensorFusion  │                 │                        │
│  · ultrasonic  │                 │  app/test13_pq.py      │
│  · potentiometer│                │  · Pygame UI           │
│  · buttons     │                 │  · AI classification   │
└───────────────┘                  │  · barcode scanning    │
                                   │  · OpenAI shelf-life   │
                                   │  · priority queue      │
                                   │                        │
                                   │  raspi/lcd2.py         │
                                   │  · 1602 LCD driver     │
                                   └────────────────────────┘
```

## Repository Structure

```
FridgeBud/
├── app/
│   └── test13_pq.py          # Main application (latest working version)
├── firmware/
│   └── sensorFusion.ino      # Arduino sensor firmware
├── raspi/
│   ├── pi.py                 # Raspberry Pi integration
│   ├── lcd2.py               # 1602 LCD driver (GPIO, BCM mode)
│   └── system.py             # Serial + LCD system layer
├── docs/
│   ├── fridgebud_architecture.docx
│   └── pic/                  # Setup & demo photos (step1–step5)
├── ppt/
│   ├── FridgeBud_Pitch_Deck (1).pptx
│   └── FridgeBud_Summary.docx
├── FreePixelFood/            # Pixel-art food sprite assets
└── archive/                  # Earlier development iterations
```

## Tech Stack

| Layer | Technology |
|---|---|
| UI | Python, Pygame |
| Vision | PyTorch, HuggingFace Transformers, OpenCV |
| Shelf-life AI | OpenAI API (GPT-4o-mini) |
| Barcode | OpenCV + pyzbar |
| Firmware | Arduino (C++), ultrasonic + potentiometer + buttons |
| Hardware | Raspberry Pi, USB camera, 1602 LCD, Arduino |
| Communication | Serial / UART |

## Getting Started

### Prerequisites

- Raspberry Pi (tested on Pi 5) with a display
- Arduino board with ultrasonic sensor, potentiometer, and buttons
- USB camera
- Python 3.9+

### Installation

```bash
# Clone the repo
git clone https://github.com/hmei3-hash/FridgeBud.git
cd FridgeBud

# Install Python dependencies
pip install pygame opencv-python torch torchvision transformers numpy pyzbar

# Set your OpenAI API key (optional — local fallback available)
export OPENAI_API_KEY="your-key-here"
```

### Run

```bash
# Flash firmware to Arduino
# Open firmware/sensorFusion.ino in Arduino IDE and upload

# Run the main app on Raspberry Pi
python app/test13_pq.py
```

## Demo

Setup and demo photos are available in `docs/pic/` (step1.JPG – step5.JPG).

## License

This project is for educational and personal use.
