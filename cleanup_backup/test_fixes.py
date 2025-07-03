#!/usr/bin/env python3
"""
Test script to verify that the fixes are working correctly.
Tests various components of the parking system.
"""
import sys
import os
import time
import threading
from datetime import datetime

# Add current directory to path
sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))

def test_hardware_mock():
    """Test hardware mock functionality."""
    print("🧪 Testing hardware mock...")
    try:
        from hardware_mock import get_hardware_modules
        GPIO, SimpleMFRC522 = get_hardware_modules()
        
        # Test GPIO
        GPIO.setmode(GPIO.BCM)
        GPIO.setup(23, GPIO.OUT)
        GPIO.output(23, GPIO.HIGH)
        GPIO.output(23, GPIO.LOW)
        GPIO.cleanup()
        
        # Test RFID (mock)
        rfid = SimpleMFRC522()
        print("   ✅ Hardware mock working correctly")
        return True
    except Exception as e:
        print(f"   ❌ Hardware mock test failed: {e}")
        return False

def test_thread_safety():
    """Test thread-safe utilities."""
    print("🧪 Testing thread-safe utilities...")
    try:
        from thread_safe_utils import ThreadSafeManager, SafeErrorLogger, safe_normalize_plate
        
        # Test ThreadSafeManager
        tm = ThreadSafeManager("test.db")
        
        # Test camera access
        with tm.camera_access():
            time.sleep(0.1)
        
        # Test events
        tm.signal_sync_work()
        tm.clear_sync_work()
        
        # Test error logger
        logger = SafeErrorLogger("test_error.log")
        logger.log_error("Test error message", "TEST")
        
        # Test safe normalize
        result = safe_normalize_plate("ABC-123")
        assert result == "ABC123", f"Expected ABC123, got {result}"
        
        print("   ✅ Thread-safe utilities working correctly")
        return True
    except Exception as e:
        print(f"   ❌ Thread-safe utilities test failed: {e}")
        return False

def test_database_manager():
    """Test database manager."""
    print("🧪 Testing database manager...")
    try:
        from database_manager import SafeDatabaseManager
        from constants import STATUS_INSIDE, STATUS_COMPLETED
        
        # Use test database
        db_manager = SafeDatabaseManager("test_parking.db")
        db_manager.init_database()
        
        # Test insert
        record_id = db_manager.insert_vehicle_entry(
            plate="TEST123",
            rfid_token="12345",
            time_in="2025-07-03 10:00:00",
            image_path_in="test.jpg",
            status=STATUS_INSIDE
        )
        assert record_id > 0, "Record ID should be positive"
        
        # Test query
        vehicle = db_manager.get_vehicle_inside_by_rfid("12345")
        assert vehicle is not None, "Should find the inserted vehicle"
        assert vehicle['plate'] == "TEST123", "Plate should match"
        
        # Test update
        success = db_manager.update_vehicle_exit(
            record_id, "2025-07-03 11:00:00", "test_out.jpg"
        )
        assert success, "Update should succeed"
        
        # Clean up
        os.remove("test_parking.db")
        if os.path.exists("test_parking.db-wal"):
            os.remove("test_parking.db-wal")
        if os.path.exists("test_parking.db-shm"):
            os.remove("test_parking.db-shm")
        
        print("   ✅ Database manager working correctly")
        return True
    except Exception as e:
        print(f"   ❌ Database manager test failed: {e}")
        return False

def test_network_manager():
    """Test network manager (without actual network calls)."""
    print("🧪 Testing network manager...")
    try:
        from network_manager import NetworkManager, create_event_payload, SyncResult
        from thread_safe_utils import SafeErrorLogger
        
        logger = SafeErrorLogger("test_error.log")
        nm = NetworkManager("http://localhost:3000/api/test", logger)
        
        # Test event payload creation
        payload = create_event_payload(
            uid="123",
            plate="TEST123",
            rfid_token="12345",
            timestamp="2025-07-03 10:00:00",
            event_type="IN",
            details="Test event",
            device_db_id=1
        )
        
        assert payload['uid'] == "123", "UID should match"
        assert payload['plate'] == "TEST123", "Plate should match"
        assert payload['event_type'] == "IN", "Event type should match"
        
        print("   ✅ Network manager working correctly")
        return True
    except Exception as e:
        print(f"   ❌ Network manager test failed: {e}")
        return False

def test_memory_management():
    """Test memory management with mock camera."""
    print("🧪 Testing camera/memory management...")
    try:
        from camera_manager import SafeCameraManager
        from thread_safe_utils import ThreadSafeManager, SafeErrorLogger
        import numpy as np
        
        # Create mock dependencies
        tm = ThreadSafeManager("test.db")
        logger = SafeErrorLogger("test_error.log")
        
        # This will fail to initialize real camera, but we can test the structure
        cm = SafeCameraManager(0, tm, logger, "/tmp")
        
        # Test that it doesn't crash
        frame = cm.capture_frame_safe()  # Should return None since no real camera
        assert frame is None, "Should return None when no camera available"
        
        print("   ✅ Camera manager structure working correctly")
        return True
    except Exception as e:
        print(f"   ❌ Camera manager test failed: {e}")
        return False

def test_concurrent_access():
    """Test concurrent database access."""
    print("🧪 Testing concurrent access...")
    try:
        from database_manager import SafeDatabaseManager
        from constants import STATUS_INSIDE
        import threading
        
        db_manager = SafeDatabaseManager("test_concurrent.db")
        db_manager.init_database()
        
        results = []
        errors = []
        
        def worker(worker_id):
            try:
                for i in range(5):
                    record_id = db_manager.insert_vehicle_entry(
                        plate=f"WORKER{worker_id}_{i}",
                        rfid_token=f"token_{worker_id}_{i}",
                        time_in="2025-07-03 10:00:00",
                        image_path_in=None,
                        status=STATUS_INSIDE
                    )
                    results.append(record_id)
                    time.sleep(0.01)  # Small delay
            except Exception as e:
                errors.append(f"Worker {worker_id}: {e}")
        
        # Start multiple threads
        threads = []
        for i in range(3):
            t = threading.Thread(target=worker, args=(i,))
            threads.append(t)
            t.start()
        
        # Wait for all threads
        for t in threads:
            t.join()
        
        # Check results
        if errors:
            print(f"   ❌ Concurrent access errors: {errors}")
            return False
        
        assert len(results) == 15, f"Expected 15 records, got {len(results)}"
        assert len(set(results)) == 15, "All record IDs should be unique"
        
        # Clean up
        os.remove("test_concurrent.db")
        if os.path.exists("test_concurrent.db-wal"):
            os.remove("test_concurrent.db-wal")
        if os.path.exists("test_concurrent.db-shm"):
            os.remove("test_concurrent.db-shm")
        
        print("   ✅ Concurrent access working correctly")
        return True
    except Exception as e:
        print(f"   ❌ Concurrent access test failed: {e}")
        return False

def main():
    """Run all tests."""
    print("🚀 Running parking system tests...\n")
    
    tests = [
        test_hardware_mock,
        test_thread_safety,
        test_database_manager,
        test_network_manager,
        test_memory_management,
        test_concurrent_access
    ]
    
    passed = 0
    failed = 0
    
    for test in tests:
        try:
            if test():
                passed += 1
            else:
                failed += 1
        except Exception as e:
            print(f"   ❌ Test {test.__name__} crashed: {e}")
            failed += 1
        print()
    
    print(f"📊 Test Results: {passed} passed, {failed} failed")
    
    # Clean up test files
    for file in ["test_error.log", "test.db.lock"]:
        if os.path.exists(file):
            os.remove(file)
    
    if failed == 0:
        print("✅ All tests passed! The fixes are working correctly.")
        return 0
    else:
        print("❌ Some tests failed. Please check the issues above.")
        return 1

if __name__ == "__main__":
    exit(main())
