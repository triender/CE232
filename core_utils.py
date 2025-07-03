# -*- coding: utf-8 -*-
"""
Parking System Core Utilities
Gộp tất cả các utility functions và classes cần thiết
"""

import os
import sqlite3
import threading
import time
import logging
from datetime import datetime
from typing import Optional, List, Dict, Any
from filelock import FileLock, Timeout

# === CONSTANTS ===
STATUS_INSIDE = 0
STATUS_COMPLETED = 1  
STATUS_INVALID = 2

# === TIME UTILITIES ===
def get_vietnam_time_str() -> str:
    """Get current Vietnam time as formatted string."""
    from datetime import datetime, timezone, timedelta
    vietnam_tz = timezone(timedelta(hours=7))
    return datetime.now(vietnam_tz).strftime("%Y-%m-%d %H:%M:%S")

# === SAFE ERROR LOGGER ===
class SafeErrorLogger:
    """Thread-safe error logger."""
    
    def __init__(self, log_file: str):
        self.log_file = log_file
        self._lock = threading.Lock()
        
        # Setup logging
        logging.basicConfig(
            level=logging.INFO,
            format='%(asctime)s [%(levelname)s] %(message)s',
            handlers=[
                logging.FileHandler(log_file),
                logging.StreamHandler()
            ]
        )
        self.logger = logging.getLogger(__name__)
    
    def log_error(self, message: str, component: str, exception: Exception = None):
        """Log error message with thread safety."""
        with self._lock:
            full_message = f"[{component}] {message}"
            if exception:
                full_message += f" | Exception: {str(exception)}"
            self.logger.error(full_message)

# === SAFE DATABASE MANAGER ===
class SafeDatabaseManager:
    """Thread-safe database manager with connection pooling."""
    
    def __init__(self, db_file: str):
        self.db_file = db_file
        self.lock_file = db_file + ".lock"
        self._lock = threading.Lock()
        
    def _get_connection(self):
        """Get database connection with proper settings."""
        conn = sqlite3.connect(self.db_file, timeout=10.0)
        conn.row_factory = sqlite3.Row
        return conn
    
    def get_vehicles_inside(self, search_query: Optional[str] = None) -> List[Dict]:
        """Get list of vehicles currently inside the parking lot."""
        with self._lock:
            try:
                with FileLock(self.lock_file, timeout=5.0):
                    with self._get_connection() as conn:
                        cursor = conn.cursor()
                        
                        query = """
                        SELECT id, plate, time_in, image_path_in 
                        FROM parking_log 
                        WHERE status = ?
                        """
                        params = [STATUS_INSIDE]
                        
                        if search_query:
                            query += " AND plate LIKE ?"
                            params.append(f"%{search_query}%")
                        
                        query += " ORDER BY time_in DESC"
                        
                        cursor.execute(query, params)
                        rows = cursor.fetchall()
                        
                        vehicles = []
                        for row in rows:
                            vehicles.append({
                                'id': row['id'],
                                'plate': row['plate'],
                                'time_in': row['time_in'],
                                'image_path': row['image_path_in']
                            })
                        
                        return vehicles
                        
            except Exception as e:
                raise Exception(f"Database error in get_vehicles_inside: {e}")
    
    def update_vehicle_exit(self, vehicle_id: int, exit_time: str, image_path: Optional[str]) -> bool:
        """Update vehicle exit information."""
        with self._lock:
            try:
                with FileLock(self.lock_file, timeout=5.0):
                    with self._get_connection() as conn:
                        cursor = conn.cursor()
                        
                        # Check if vehicle exists and is inside
                        cursor.execute(
                            "SELECT id FROM parking_log WHERE id = ? AND status = ?",
                            (vehicle_id, STATUS_INSIDE)
                        )
                        
                        if not cursor.fetchone():
                            return False
                        
                        # Update exit information
                        cursor.execute("""
                            UPDATE parking_log 
                            SET time_out = ?, image_path_out = ?, status = ?, synced_to_server = 0
                            WHERE id = ?
                        """, (exit_time, image_path, STATUS_COMPLETED, vehicle_id))
                        
                        conn.commit()
                        return True
                        
            except Exception as e:
                raise Exception(f"Database error in update_vehicle_exit: {e}")

# === NETWORK MANAGER ===
class NetworkManager:
    """Handle network operations and server synchronization."""
    
    def __init__(self, server_url: str):
        self.server_url = server_url
        self._lock = threading.Lock()
    
    def sync_record(self, record_data: Dict) -> bool:
        """Sync a single record to server (mock implementation)."""
        with self._lock:
            try:
                # Mock successful sync - replace with actual HTTP request
                time.sleep(0.1)  # Simulate network delay
                print(f"✅ [Network] Server accepted event {record_data.get('id', 'unknown')}")
                return True
            except Exception as e:
                print(f"❌ [Network] Failed to sync record: {e}")
                return False

# === CAMERA MANAGER ===
class SafeCameraManager:
    """Safe camera operations with hardware abstraction."""
    
    def __init__(self, mock_mode: bool = False):
        self.mock_mode = mock_mode
        self._lock = threading.Lock()
    
    def capture_image(self, output_path: str) -> bool:
        """Capture image from camera."""
        with self._lock:
            try:
                if self.mock_mode:
                    # Create a simple mock image file
                    with open(output_path, 'w') as f:
                        f.write("mock_image_data")
                    return True
                else:
                    # TODO: Implement actual camera capture
                    return False
            except Exception as e:
                print(f"❌ [Camera] Error capturing image: {e}")
                return False

# === HARDWARE MOCK ===
class HardwareMock:
    """Mock hardware components for testing."""
    
    @staticmethod
    def read_rfid() -> Optional[str]:
        """Mock RFID reading."""
        import random
        if random.random() < 0.3:  # 30% chance of reading
            return f"MOCK_RFID_{random.randint(1000, 9999)}"
        return None
    
    @staticmethod
    def control_led(state: bool):
        """Mock LED control."""
        print(f"🔵 [LED] {'ON' if state else 'OFF'}")
    
    @staticmethod
    def control_barrier(action: str):
        """Mock barrier control."""
        print(f"🚧 [Barrier] {action.upper()}")

# === THREAD SAFE UTILITIES ===
class ThreadSafeManager:
    """Manage thread-safe operations for the parking system."""
    
    def __init__(self):
        self._shutdown_event = threading.Event()
        self._threads = []
    
    def start_background_thread(self, target, name: str, *args, **kwargs):
        """Start a background thread with proper management."""
        thread = threading.Thread(target=target, name=name, args=args, kwargs=kwargs)
        thread.daemon = True
        thread.start()
        self._threads.append(thread)
        return thread
    
    def shutdown(self):
        """Gracefully shutdown all managed threads."""
        self._shutdown_event.set()
        for thread in self._threads:
            if thread.is_alive():
                thread.join(timeout=5.0)
    
    def is_shutdown_requested(self) -> bool:
        """Check if shutdown has been requested."""
        return self._shutdown_event.is_set()

# === CONFIGURATION ===
class Config:
    """Centralized configuration management."""
    
    # Database
    DB_FILE = os.getenv("DB_FILE", "parking_data.db")
    
    # Directories  
    PICTURE_OUTPUT_DIR = os.getenv("PICTURE_OUTPUT_DIR", "picture")
    TMP_DIR = "tmp"
    
    # Network
    SERVER_URL = os.getenv("SERVER_URL", "http://localhost:8080")
    
    # Hardware
    MOCK_HARDWARE = os.getenv("MOCK_HARDWARE", "true").lower() == "true"
    
    # Flask
    FLASK_HOST = "0.0.0.0"
    FLASK_PORT = 5000
    FLASK_DEBUG = False

# Export all components
__all__ = [
    'STATUS_INSIDE', 'STATUS_COMPLETED', 'STATUS_INVALID',
    'get_vietnam_time_str',
    'SafeErrorLogger', 'SafeDatabaseManager', 'NetworkManager',
    'SafeCameraManager', 'HardwareMock', 'ThreadSafeManager',
    'Config'
]
