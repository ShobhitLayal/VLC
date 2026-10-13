# Optical Visible Light Communication (VLC) System

An end-to-end hardware and software implementation of a Visible Light Communication (VLC) system. This project utilizes laser transmitters and light-dependent resistors (LDRs) interfaced with ESP8266 microcontrollers to transmit both plaintext messages and 16x16 grayscale images physically through light pulses using standard Morse Code. 

Developed as an academic electronics and communication engineering prototype at Dr. B. R. Ambedkar National Institute of Technology, Jalandhar, this system features a robust physical layer and a live-rendering Streamlit dashboard.

## Key Features
* **Dual-Payload Support:** Dynamically routes incoming light pulses as standard text messages or image payloads based on an `IMG ` prefix header.
* **Live Pixel Rendering:** The receiver’s Streamlit UI visually draws the transmitted 16x16 image line-by-line in real time as the hex characters arrive over the serial port.
* **Hardware Error Highlighting:** Incomplete or corrupted light pulses (caused by chemical lag in the LDR or physical interference) are caught by the Python receiver and actively rendered as bright red pixels on the dashboard.
* **Stable Baseline Architecture:** Operates on a highly stable standard Morse code 1:3 ratio translation to guarantee hardware reliability during live demonstrations.

## Repository Structure
```text
.
├── .vscode/               # Workspace configurations
├── Receiver/              # Receiver software and firmware
│   ├── vlc_receiver/      # C++ firmware directory
│   │   └── vlc_receiver.ino # ESP8266 LDR reading and Morse decoding
│   └── app.py             # Streamlit UI for live image rendering
└── Transmitter/           # Transmitter software and firmware
    ├── vlc_transmitter/   # C++ firmware directory
    │   └── vlc_transmitter.ino # ESP8266 laser pulsing logic
    ├── app.py             # Streamlit UI for image hex encoding
    └── config.toml        # Streamlit configuration settings
```

## System Architecture
The system is divided into two decoupled nodes communicating entirely via optical transmission.

### 1. The Transmitter Node
* **Hardware:** ESP8266 + Laser Diode Module.
* **Software (`Transmitter/app.py`):** A Streamlit dashboard that accepts an image upload, shrinks it to 16x16, maps the pixels to 16 grayscale shades (Hex `0-F`), and generates a 256-character payload.
* **Firmware (`Transmitter/vlc_transmitter.ino`):** Reads the hex string over the serial port and translates it into physical light flashes using standard International Morse Code logic.

### 2. The Receiver Node
* **Hardware:** ESP8266 + Light Dependent Resistor (LDR) circuit.
* **Firmware (`Receiver/vlc_receiver.ino`):** Measures the duration of incoming light pulses (dots vs. dashes), decodes the Morse patterns back into alphanumeric characters, and pushes them to the serial port.
* **Software (`Receiver/app.py`):** Monitors the serial buffer. If standard text arrives, it displays it in a messaging tab. If the `IMG ` prefix is detected, it actively paints the 256 hex characters onto a live canvas.

## Getting Started

**Hardware Setup:**
1. Connect a Laser Diode to the designated GPIO pin on the Transmitter ESP8266.
2. Connect an LDR (with an appropriate pull-down resistor) to the analog pin on the Receiver ESP8266.

**Firmware Flashing:**
1. Open `vlc_transmitter.ino` and `vlc_receiver.ino` in the Arduino IDE.
2. Verify the COM ports and flash the respective ESP8266 boards.

**Running the Dashboards:**
Open two separate terminal windows (one for the transmitter, one for the receiver):
```bash
# Terminal 1
cd Transmitter
streamlit run app.py

# Terminal 2
cd Receiver
streamlit run app.py
```

## Future Scope (The Layal Protocol)
While the current stable build utilizes standard Morse Code to ensure hardware reliability, future optimizations for the physical layer include a custom variable-length dictionary. Since standard Morse is highly inefficient for hex numbers (e.g., `0` requires 5 dashes), proposed firmware upgrades involve reallocating the shortest 1-pulse and 2-pulse codes (`.`, `-`, `..`, etc.) strictly to the highest-frequency payload characters: `0`, `F`, `E`, `1`, `T`, and a Run-Length Encoding delimiter `Q`. This theoretical adjustment could reduce overall transmission time by 40% without compromising data integrity.