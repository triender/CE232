#!/usr/bin/env python3
"""
Quick test script to verify the main components are working after fixes.
This is a simplified test focused on the core functionality.
"""
import sys
import os

# Add current directory to path
sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))

def test_imports():
    """Test that all modules can be imported without errors."""
    print("🧪 Testing imports...")
    try:
        # Test hardware mock
        from hardware_mock import get_hardware_modules
        GPIO, SimpleMFRC522 = get_hardware_modules()
        
        # Test thread safety
        from thread_safe_utils import ThreadSafeManager, SafeErrorLogger
        
        # Test database manager  
        from database_manager import SafeDatabaseManager
        
        # Test network manager
        from network_manager import NetworkManager, SyncResult
        
        # Test camera manager
        from camera_manager import SafeCameraManager
        
        print("   ✅ All imports successful")
        return True
    except Exception as e:
        print(f"   ❌ Import failed: {e}")
        return False

def test_basic_functionality():
    """Test basic functionality without hardware."""
    print("🧪 Testing basic functionality...")
    try:
        from database_manager import SafeDatabaseManager
        from constants import STATUS_INSIDE
        
        # Test database creation and basic operations
        db_manager = SafeDatabaseManager("test_basic.db")
        db_manager.init_database()
        
        # Test insert
        record_id = db_manager.insert_vehicle_entry(
            plate="TEST123",
            rfid_token="12345",
            time_in="2025-07-03 10:00:00",
            image_path_in=None,
            status=STATUS_INSIDE
        )
        
        # Test query
        vehicle = db_manager.get_vehicle_inside_by_rfid("12345")
        assert vehicle is not None, "Should find the inserted vehicle"
        assert vehicle['plate'] == "TEST123", "Plate should match"
        
        # Clean up
        os.remove("test_basic.db")
        if os.path.exists("test_basic.db-wal"):
            os.remove("test_basic.db-wal")
        if os.path.exists("test_basic.db-shm"):
            os.remove("test_basic.db-shm")
        
        print("   ✅ Basic functionality working")
        return True
    except Exception as e:
        print(f"   ❌ Basic functionality test failed: {e}")
        return False

def test_main_modules():
    """Test that main modules can be loaded."""
    print("🧪 Testing main modules...")
    try:
        # Test LPR module syntax
        with open('LPR.py', 'r') as f:
            lpr_content = f.read()
        compile(lpr_content, 'LPR.py', 'exec')
        
        # Test app module syntax  
        with open('app.py', 'r') as f:
            app_content = f.read()
        compile(app_content, 'app.py', 'exec')
        
        print("   ✅ Main modules syntax valid")
        return True
    except Exception as e:
        print(f"   ❌ Main modules test failed: {e}")
        return False

def main():
    """Run quick verification tests."""
    print("🚀 Running quick verification tests...\n")
    
    tests = [
        test_imports,
        test_basic_functionality,
        test_main_modules
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
    
    if failed == 0:
        print("✅ All quick tests passed! The system is ready.")
        print("\n🎯 NEXT STEPS:")
        print("   1. Run: python3 app.py  (to start web interface)")
        print("   2. Run: python3 LPR.py  (to start main parking system)")
        print("   3. Open: http://localhost:5000 (to view web interface)")
        return 0
    else:
        print("❌ Some tests failed. Please check the issues above.")
        return 1

if __name__ == "__main__":
    exit(main())
