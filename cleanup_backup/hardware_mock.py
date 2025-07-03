"""
Mock classes for hardware dependencies when running on non-Raspberry Pi systems.
This allows the application to run in development/testing environments.
"""
import time
import random
import threading
from typing import Tuple


class MockGPIO:
    """Mock GPIO class for non-Raspberry Pi systems."""
    BCM = "BCM"
    OUT = "OUT"
    IN = "IN"
    HIGH = 1
    LOW = 0
    
    _pin_states = {}
    
    @classmethod
    def setwarnings(cls, state: bool):
        print(f"🔧 [MockGPIO] setwarnings({state})")
    
    @classmethod
    def setmode(cls, mode):
        print(f"🔧 [MockGPIO] setmode({mode})")
    
    @classmethod
    def setup(cls, pin: int, mode, initial=None):
        cls._pin_states[pin] = initial if initial is not None else cls.LOW
        print(f"🔧 [MockGPIO] setup(pin={pin}, mode={mode}, initial={initial})")
    
    @classmethod
    def output(cls, pin: int, state: int):
        cls._pin_states[pin] = state
        state_name = "HIGH" if state == cls.HIGH else "LOW"
        print(f"🔧 [MockGPIO] output(pin={pin}, state={state_name})")
    
    @classmethod
    def input(cls, pin: int) -> int:
        return cls._pin_states.get(pin, cls.LOW)
    
    @classmethod
    def cleanup(cls):
        cls._pin_states.clear()
        print("🔧 [MockGPIO] cleanup() - All pins reset")


class MockSimpleMFRC522:
    """Mock RFID reader for non-Raspberry Pi systems."""
    
    def __init__(self):
        self._card_counter = 1000
        print("🔧 [MockRFID] SimpleMFRC522 initialized")
    
    def read(self) -> Tuple[int, str]:
        """Simulate RFID card reading."""
        print("🔧 [MockRFID] Waiting for RFID card (Press Enter to simulate card scan)...")
        input()  # Wait for user input to simulate card scan
        
        self._card_counter += 1
        rfid_id = self._card_counter
        rfid_text = f"MockCard_{rfid_id}"
        
        print(f"🔧 [MockRFID] Card detected: ID={rfid_id}, Text={rfid_text}")
        return rfid_id, rfid_text
    
    def write(self, text: str) -> int:
        """Simulate writing to RFID card."""
        rfid_id = random.randint(1000, 9999)
        print(f"🔧 [MockRFID] Writing '{text}' to card ID {rfid_id}")
        return rfid_id


def get_hardware_modules():
    """
    Get appropriate hardware modules based on the system.
    Returns mock modules on non-Raspberry Pi systems.
    """
    try:
        # Try to import real Raspberry Pi modules
        import RPi.GPIO as GPIO
        from mfrc522 import SimpleMFRC522
        print("✅ [Hardware] Real Raspberry Pi modules loaded")
        return GPIO, SimpleMFRC522
    except ImportError:
        print("⚠️  [Hardware] Raspberry Pi modules not available, using mock modules")
        return MockGPIO, MockSimpleMFRC522
