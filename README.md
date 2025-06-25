# CE232 - License Plate Recognition & RFID Parking System

## Project Overview

This project is an on-premise, automated parking management system that uses computer vision and RFID technology to control vehicle access. It is designed for robust, offline-first operation, ensuring continuous functionality even without a stable network connection. The system captures vehicle entries and exits, validates them against a local database, and synchronizes event data with a remote server.

## Features

*   **Real-time License Plate Recognition**: Employs a YOLOv5-based model to automatically detect and read vehicle license plates from a live camera feed.
*   **RFID Integration**: Uses an MFRC522 reader to associate each vehicle with a unique RFID tag for fast and reliable authentication.
*   **Offline-First Operation**: All parking events are first recorded in a local SQLite database, allowing the system to function independently of network connectivity.
*   **Robust Data Synchronization**: A dedicated background thread handles the synchronization of local data to a remote server. It intelligently manages temporary network failures and handles server-side validation errors to prevent data loss or corruption.
*   **Detailed Event Logging**:
    *   **Access Log**: Records every successful or failed entry/exit event in a structured `access_log.jsonl` file, complete with timestamps, plate numbers, RFID tokens, and image paths.
    *   **Error Log**: Captures system-level errors, network issues, and validation failures in `error_log.txt` for diagnostics and troubleshooting.
*   **Security Validation Logic**: Implements critical security checks, such as preventing a vehicle from entering if it's already marked as inside and flagging a mismatch between the license plate at entry and exit.
*   **Web Monitoring Interface**: Includes a companion Flask web application that provides a local dashboard to view access history, see vehicles currently in the lot, and review operational statistics.

## Hardware Requirements

*   A computer capable of running Python (e.g., Raspberry Pi 4+, Jetson Nano, or a standard PC).
*   A Webcam or IP Camera compatible with OpenCV.
*   An MFRC522 RFID Reader and associated RFID tags.

## Software & Libraries

*   **Python 3.8+**
*   **AI & Vision**:
    *   YOLOv5
    *   PyTorch
    *   OpenCV
*   **Hardware Interface**:
    *   RPi.GPIO
    *   mfrc522
*   **Web & Network**:
    *   Flask
    *   Requests
    *   Watchdog
*   **Database**:
    *   SQLite3 (standard library)

## How It Works

1.  **Initialization**: Upon startup, the system initializes the SQLite database, loads the YOLOv5 models for plate detection and OCR, and establishes a connection with the camera and RFID reader. A background thread for data synchronization is also started.

2.  **Event-Driven Loop**: The main application enters a loop, waiting for an RFID tag to be scanned.

3.  **Event Processing**: When a tag is detected, the system captures an image from the camera. The image is processed through the AI pipeline to extract the license plate number.

4.  **Logic & Validation**:
    *   **Vehicle Entry**: If the scanned RFID tag is not currently associated with a vehicle inside the lot, the system verifies that the detected license plate is also not already present. If the entry is valid, a new record is created in the local database with an `INSIDE` status.
    *   **Vehicle Exit**: If the RFID tag is recognized as being inside the lot, the system compares the newly detected license plate with the one stored from the entry event. If they match, the database record is updated to `COMPLETED`. If they do not match, a security alert is logged.

5.  **Data Persistence & Synchronization**: Every event is immediately saved to the local SQLite database and logged to the appropriate text file. The background synchronization thread is then signaled. It checks for unsynced records, sends them to the remote API endpoint, and updates their status locally upon successful transmission. This ensures data integrity and eventual consistency with the central server.
