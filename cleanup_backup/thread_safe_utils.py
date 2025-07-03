"""
Thread-safe utilities for the parking management system.
Handles lock ordering and prevents race conditions.
"""
import threading
import time
from typing import Optional
from filelock import FileLock
from contextlib import contextmanager


class ThreadSafeManager:
    """Manages thread synchronization and prevents deadlocks."""
    
    def __init__(self, db_file: str):
        # Lock hierarchy (always acquire in this order to prevent deadlock)
        self.camera_lock = threading.Lock()           # Level 1
        self.db_lock = FileLock(f"{db_file}.lock", timeout=15)  # Level 2
        
        # Thread coordination events
        self.vehicle_event = threading.Event()
        self.sync_work_available = threading.Event()
        self.live_view_running = threading.Event()
        
        # Additional state tracking
        self._processing_lock = threading.Lock()
        self._is_processing = False
    
    @contextmanager
    def camera_access(self):
        """Safe camera access with timeout."""
        acquired = self.camera_lock.acquire(timeout=5.0)
        if not acquired:
            raise TimeoutError("Could not acquire camera lock within 5 seconds")
        try:
            yield
        finally:
            self.camera_lock.release()
    
    @contextmanager
    def database_access(self):
        """Safe database access with proper error handling."""
        try:
            with self.db_lock:
                yield
        except Exception as e:
            print(f"🔥 [ThreadSafe] Database access error: {e}")
            raise
    
    @contextmanager
    def exclusive_processing(self):
        """Ensure only one vehicle event is processed at a time."""
        with self._processing_lock:
            if self._is_processing:
                raise RuntimeError("Another vehicle event is already being processed")
            self._is_processing = True
            self.vehicle_event.set()
        
        try:
            yield
        finally:
            with self._processing_lock:
                self._is_processing = False
                self.vehicle_event.clear()
    
    def wait_for_sync_work(self, timeout: Optional[float] = None) -> bool:
        """Wait for sync work with proper event handling."""
        return self.sync_work_available.wait(timeout=timeout)
    
    def signal_sync_work(self):
        """Signal that sync work is available."""
        self.sync_work_available.set()
    
    def clear_sync_work(self):
        """Clear sync work signal."""
        self.sync_work_available.clear()
    
    def is_vehicle_processing(self) -> bool:
        """Check if a vehicle event is currently being processed."""
        with self._processing_lock:
            return self._is_processing
    
    def start_live_view(self):
        """Start live view thread."""
        self.live_view_running.set()
    
    def stop_live_view(self):
        """Stop live view thread."""
        self.live_view_running.clear()
    
    def is_live_view_running(self) -> bool:
        """Check if live view is running."""
        return self.live_view_running.is_set()


class SafeErrorLogger:
    """Thread-safe error logging."""
    
    def __init__(self, log_file: str):
        self.log_file = log_file
        self._log_lock = threading.Lock()
    
    def log_error(self, message: str, category: str = "GENERAL", exception_obj: Exception = None) -> None:
        """Thread-safe error logging."""
        try:
            from project_utils import get_vietnam_time_str
            import traceback
            
            with self._log_lock:
                with open(self.log_file, "a", encoding="utf-8") as f:
                    timestamp = get_vietnam_time_str()
                    f.write(f"[{timestamp}] [{category}] {message}\n")
                    if exception_obj:
                        f.write(traceback.format_exc())
                        f.write("-" * 50 + "\n")
        except Exception as e:
            print(f"🔥 [SafeErrorLogger] Failed to write to error log: {e}")


def safe_normalize_plate(plate_text: str) -> str:
    """Safely normalize plate text with error handling."""
    try:
        from project_utils import normalize_plate
        if not plate_text:
            return "UNKNOWN"
        result = normalize_plate(plate_text)
        return result if result else "UNKNOWN"
    except Exception as e:
        print(f"🔥 [SafeNormalize] Error normalizing plate '{plate_text}': {e}")
        return "UNKNOWN"
