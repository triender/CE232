# Installation Guide

## Prerequisites

### Hardware Setup
- Raspberry Pi 4+ (4GB RAM recommended) or compatible PC
- USB Camera or IP Camera
- MFRC522 RFID Reader module
- RFID tags/cards
- Green LED for status indication
- Jumper wires and breadboard

### Software Requirements
- Python 3.8 or higher
- Git
- Internet connection for initial setup

## Step-by-Step Installation

### 1. System Preparation

```bash
# Update system packages (Raspberry Pi)
sudo apt update && sudo apt upgrade -y

# Install required system packages
sudo apt install python3-pip python3-venv git -y

# Enable SPI for RFID reader (Raspberry Pi)
sudo raspi-config
# Navigate to: Interfacing Options > SPI > Enable
```

### 2. Clone Repository

```bash
# Clone the project
git clone <repository-url>
cd minhtest

# Verify project structure
ls -la
```

### 3. Python Environment Setup

```bash
# Create virtual environment
python3 -m venv ai_env

# Activate virtual environment
source ai_env/bin/activate

# Upgrade pip
pip install --upgrade pip

# Install dependencies
pip install -r requirements.txt
```

### 4. YOLOv5 Setup

```bash
# Download YOLOv5 framework
git clone https://github.com/ultralytics/yolov5.git

# Install YOLOv5 dependencies
cd yolov5
pip install -r requirements.txt
cd ..
```

### 5. AI Models

```bash
# Create model directory if not exists
mkdir -p model

# Download or place your trained models:
# - LP_detector_nano_61.pt (License plate detection)
# - LP_ocr_nano_62.pt (Character recognition)

# Verify models are in place
ls -la model/
```

### 6. Configuration

```bash
# Copy environment template
cp .env.example .env

# Edit configuration file
nano .env
```

Update the following variables in `.env`:
```bash
API_ENDPOINT="http://your-server:3000/api/parking/events/submit"
UID="your-unique-device-id"
YOLOV5_REPO_PATH="/home/minhtest/yolov5"
LP_DETECTOR_MODEL_PATH="model/LP_detector_nano_61.pt"
LP_OCR_MODEL_PATH="model/LP_ocr_nano_62.pt"
```

### 7. Hardware Connections

#### MFRC522 RFID Reader Wiring (Raspberry Pi)
```
MFRC522    Raspberry Pi
SDA    ->  Pin 24 (GPIO 8)
SCK    ->  Pin 23 (GPIO 11)
MOSI   ->  Pin 19 (GPIO 10)
MISO   ->  Pin 21 (GPIO 9)
IRQ    ->  Not connected
GND    ->  Pin 6 (GND)
RST    ->  Pin 22 (GPIO 25)
3.3V   ->  Pin 1 (3.3V)
```

#### LED Status Indicator
```
LED        Raspberry Pi
Anode  ->  Pin 36 (GPIO 16) through 220Ω resistor
Cathode -> Pin 34 (GND)
```

#### Camera
```bash
# USB Camera: Simply connect to USB port
# IP Camera: Configure network settings

# Test camera
python3 -c "import cv2; cap = cv2.VideoCapture(0); print('Camera OK' if cap.isOpened() else 'Camera Error')"
```

### 8. Permissions Setup

```bash
# Add user to GPIO group (Raspberry Pi)
sudo usermod -a -G gpio $USER

# Add user to video group for camera access
sudo usermod -a -G video $USER

# Logout and login again, or reboot
sudo reboot
```

### 9. Test Installation

```bash
# Navigate to project directory
cd /home/minhtest

# Activate environment
source ai_env/bin/activate

# Test components individually
python3 -c "import cv2; print('OpenCV OK')"
python3 -c "import torch; print('PyTorch OK')"
python3 -c "from mfrc522 import SimpleMFRC522; print('RFID OK')"

# Make startup script executable
chmod +x start.sh

# Test run (will start the system)
./start.sh
```

### 10. First Run Verification

1. **Web Interface**: Open browser and go to `http://localhost:5000`
2. **Camera Feed**: Verify live video is working
3. **RFID Test**: Try scanning an RFID card
4. **Database**: Check if `parking_data.db` is created
5. **Logs**: Verify `access_log.jsonl` and `error_log.txt` are created

## Troubleshooting Installation

### Common Issues

**SPI Not Enabled**
```bash
# Enable SPI manually
echo 'dtparam=spi=on' | sudo tee -a /boot/config.txt
sudo reboot
```

**Permission Denied on GPIO**
```bash
# Add user to gpio group
sudo usermod -a -G gpio $USER
# Logout and login again
```

**Camera Not Found**
```bash
# List video devices
ls /dev/video*

# Test with different camera index
python3 -c "import cv2; cap = cv2.VideoCapture(1); print(cap.isOpened())"
```

**PyTorch Installation Issues**
```bash
# For Raspberry Pi, use pip wheel
pip install torch torchvision --extra-index-url https://download.pytorch.org/whl/cpu
```

**Model Files Missing**
```bash
# Verify model files exist and have correct permissions
ls -la model/
chmod 644 model/*.pt
```

## Performance Optimization

### For Raspberry Pi
```bash
# Increase GPU memory split
sudo raspi-config
# Advanced Options > Memory Split > 128

# Optimize swap file
sudo dphys-swapfile swapoff
sudo nano /etc/dphys-swapfile
# Set CONF_SWAPSIZE=2048
sudo dphys-swapfile setup
sudo dphys-swapfile swapon
```

### For Better Performance
- Use faster SD card (Class 10, U3)
- Enable GPU acceleration if available
- Adjust camera resolution in configuration
- Consider using lighter AI models

## Next Steps

After successful installation:
1. Read the [User Manual](USER_MANUAL.md) for usage instructions
2. Configure your server endpoint
3. Train or obtain appropriate AI models
4. Set up monitoring and maintenance procedures
