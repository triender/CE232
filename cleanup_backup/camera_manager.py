"""
Camera management utilities with proper memory handling.
Prevents memory leaks and handles camera errors gracefully.
"""
import cv2
import os
import time
import threading
import numpy as np
from typing import Optional, Tuple
from thread_safe_utils import ThreadSafeManager, SafeErrorLogger


class SafeCameraManager:
    """Thread-safe camera manager with memory leak prevention."""
    
    def __init__(self, camera_index: int, thread_manager: ThreadSafeManager, 
                 error_logger: SafeErrorLogger, tmp_dir: str):
        self.camera_index = camera_index
        self.thread_manager = thread_manager
        self.error_logger = error_logger
        self.tmp_dir = tmp_dir
        
        # Camera configuration
        self.frame_width = 640
        self.frame_height = 480
        self.fps = 15
        self.jpeg_quality = 85
        
        # Frame buffer management
        self._frame_buffer_size = 5
        self._last_frame_time = 0
        self._min_frame_interval = 1.0 / self.fps  # Minimum time between frames
        
        self._cap: Optional[cv2.VideoCapture] = None
        self._is_initialized = False
    
    def initialize_camera(self) -> bool:
        """Initialize camera with proper configuration."""
        try:
            self._cap = cv2.VideoCapture(self.camera_index)
            if not self._cap.isOpened():
                raise IOError(f"Cannot open camera {self.camera_index}")
            
            # Configure camera properties
            self._cap.set(cv2.CAP_PROP_FRAME_WIDTH, self.frame_width)
            self._cap.set(cv2.CAP_PROP_FRAME_HEIGHT, self.frame_height)
            self._cap.set(cv2.CAP_PROP_FPS, self.fps)
            self._cap.set(cv2.CAP_PROP_BUFFERSIZE, 1)  # Minimize buffer to get latest frame
            
            # Test frame capture
            ret, test_frame = self._cap.read()
            if not ret or test_frame is None:
                raise IOError("Cannot read test frame from camera")
            
            # Explicitly delete test frame to prevent memory leak
            del test_frame
            
            self._is_initialized = True
            print(f"✅ [Camera] Initialized camera {self.camera_index} ({self.frame_width}x{self.frame_height})")
            return True
            
        except Exception as e:
            error_msg = f"Failed to initialize camera {self.camera_index}: {e}"
            print(f"❌ [Camera] {error_msg}")
            self.error_logger.log_error(error_msg, category="CAMERA_INIT", exception_obj=e)
            if self._cap:
                self._cap.release()
                self._cap = None
            return False
    
    def capture_frame_safe(self, flush_buffer: bool = True) -> Optional[np.ndarray]:
        """
        Safely capture a frame with proper memory management.
        
        Args:
            flush_buffer: Whether to flush camera buffer first
            
        Returns:
            Frame as numpy array or None if failed
        """
        if not self._is_initialized or not self._cap or not self._cap.isOpened():
            return None
        
        try:
            with self.thread_manager.camera_access():
                # Flush buffer to get latest frame
                if flush_buffer:
                    for _ in range(self._frame_buffer_size):
                        ret, _ = self._cap.read()
                        if not ret:
                            break
                
                # Capture actual frame
                ret, frame = self._cap.read()
                if not ret or frame is None:
                    print("⚠️  [Camera] Failed to capture frame")
                    return None
                
                # Create a copy to ensure memory safety
                frame_copy = frame.copy()
                
                # Explicitly delete original frame
                del frame
                
                return frame_copy
                
        except Exception as e:
            error_msg = f"Error capturing frame: {e}"
            print(f"❌ [Camera] {error_msg}")
            self.error_logger.log_error(error_msg, category="CAMERA_CAPTURE", exception_obj=e)
            return None
    
    def save_frame_as_jpeg(self, frame: np.ndarray, output_path: str) -> bool:
        """
        Save frame as JPEG with proper error handling.
        
        Args:
            frame: Frame to save
            output_path: Output file path
            
        Returns:
            True if successful, False otherwise
        """
        try:
            # Encode frame as JPEG
            encode_param = [int(cv2.IMWRITE_JPEG_QUALITY), self.jpeg_quality]
            is_success, im_buf_arr = cv2.imencode(".jpg", frame, encode_param)
            
            if not is_success:
                print("❌ [Camera] Failed to encode frame as JPEG")
                return False
            
            # Write to temporary file first, then rename (atomic operation)
            tmp_output_path = output_path + ".tmp"
            with open(tmp_output_path, "wb") as f:
                f.write(im_buf_arr.tobytes())
            
            # Atomic rename
            os.rename(tmp_output_path, output_path)
            
            # Explicitly delete buffer
            del im_buf_arr
            
            return True
            
        except Exception as e:
            error_msg = f"Error saving frame to {output_path}: {e}"
            print(f"❌ [Camera] {error_msg}")
            self.error_logger.log_error(error_msg, category="CAMERA_SAVE", exception_obj=e)
            return False
    
    def live_view_thread_safe(self):
        """
        Thread function for live view with proper memory management.
        """
        output_path = os.path.join(self.tmp_dir, "live_view.jpg")
        print(f"🖼️  [LiveView] Thread started, saving to: {output_path}")
        
        frame_count = 0
        error_count = 0
        max_consecutive_errors = 10
        
        while self.thread_manager.is_live_view_running():
            try:
                current_time = time.time()
                
                # Rate limiting
                if current_time - self._last_frame_time < self._min_frame_interval:
                    time.sleep(self._min_frame_interval)
                    continue
                
                # Capture frame
                frame = self.capture_frame_safe(flush_buffer=False)
                if frame is None:
                    error_count += 1
                    if error_count >= max_consecutive_errors:
                        print(f"🖼️  [LiveView] Too many consecutive errors ({error_count}), stopping")
                        break
                    time.sleep(0.5)
                    continue
                
                # Reset error count on successful capture
                error_count = 0
                
                # Save frame
                if self.save_frame_as_jpeg(frame, output_path):
                    frame_count += 1
                    self._last_frame_time = current_time
                    
                    # Log every 100 frames
                    if frame_count % 100 == 0:
                        print(f"🖼️  [LiveView] Processed {frame_count} frames")
                
                # Explicitly delete frame to prevent memory leak
                del frame
                
                # Small delay to prevent excessive CPU usage
                time.sleep(0.05)
                
            except Exception as e:
                error_count += 1
                error_msg = f"Error in live view thread: {e}"
                print(f"🖼️  [LiveView] {error_msg}")
                self.error_logger.log_error(error_msg, category="LIVE_VIEW", exception_obj=e)
                
                if error_count >= max_consecutive_errors:
                    print(f"🖼️  [LiveView] Too many errors ({error_count}), stopping thread")
                    break
                
                time.sleep(1.0)  # Longer delay on error
        
        print(f"🖼️  [LiveView] Thread stopped after processing {frame_count} frames")
    
    def release(self):
        """Release camera resources."""
        try:
            if self._cap and self._cap.isOpened():
                self._cap.release()
                print("✅ [Camera] Camera released")
        except Exception as e:
            print(f"⚠️  [Camera] Error releasing camera: {e}")
        finally:
            self._cap = None
            self._is_initialized = False
