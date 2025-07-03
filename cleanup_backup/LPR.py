import cv2
import torch
import os
import time
from datetime import datetime, timezone, timedelta
import requests
import sqlite3
import threading
from dotenv import load_dotenv
import json
import traceback
from filelock import FileLock
from constants import *
from project_utils import get_vietnam_time_str, get_vietnam_time_for_filename, normalize_plate, sanitize_filename_component, ensure_directories_exist

# Import new modules for better error handling and thread safety
from hardware_mock import get_hardware_modules
from thread_safe_utils import ThreadSafeManager, SafeErrorLogger, safe_normalize_plate
from database_manager import SafeDatabaseManager
from network_manager import NetworkManager, SyncResult, create_event_payload
from camera_manager import SafeCameraManager

# Get appropriate hardware modules (real or mock)
GPIO, SimpleMFRC522 = get_hardware_modules()

# --- CẤU HÌNH VÀ HẰNG SỐ ---
load_dotenv()
API_ENDPOINT = os.getenv("API_ENDPOINT", "http://localhost:3000/api/events/submit")
UID = os.getenv("UID")
DB_FILE = os.getenv("DB_FILE", "parking_data.db")
IMAGE_DIR = os.getenv("IMAGE_DIR", "offline_images")
PICTURE_OUTPUT_DIR = os.getenv("PICTURE_OUTPUT_DIR", "picture")
YOLOV5_REPO_PATH = os.getenv("YOLOV5_REPO_PATH")
LP_DETECTOR_MODEL_PATH = os.getenv("LP_DETECTOR_MODEL_PATH")
LP_OCR_MODEL_PATH = os.getenv("LP_OCR_MODEL_PATH")
TMP_DIR = os.path.join(os.path.dirname(os.path.abspath(__file__)), "tmp")

# --- Initialize new managers ---
thread_manager = ThreadSafeManager(DB_FILE)
error_logger = SafeErrorLogger(ERROR_LOG_FILE)
db_manager = SafeDatabaseManager(DB_FILE)
network_manager = NetworkManager(API_ENDPOINT, error_logger)
camera_manager = None  # Will be initialized later

# --- Legacy variables for compatibility ---
DB_LOCK_FILE = DB_FILE + ".lock"
DB_ACCESS_LOCK = thread_manager.db_lock
CAMERA_LOCK = thread_manager.camera_lock
VEHICLE_EVENT = thread_manager.vehicle_event
SYNC_WORK_AVAILABLE = thread_manager.sync_work_available
LIVE_VIEW_THREAD_RUNNING = thread_manager.live_view_running

# --- Cài đặt GPIO ---

# --- LOGGING FUNCTIONS ---
def log_error(message: str, category: str = "GENERAL", exception_obj: Exception = None) -> None:
    """Log error messages to error log file."""
    error_logger.log_error(message, category, exception_obj)


def _blink_led_target() -> None:
    """LED thread target function."""
    try:
        GPIO.output(GREEN_LED_PIN, GPIO.HIGH)
        print("🟢 [LED] Đèn xanh BẬT (Thành công)")
        time.sleep(2)
    finally:
        GPIO.output(GREEN_LED_PIN, GPIO.LOW)
        print("🟢 [LED] Đèn xanh TẮT")

def blink_success_led() -> None:
    """Start new thread to blink green LED for 2 seconds."""
    led_thread = threading.Thread(target=_blink_led_target)
    led_thread.daemon = True
    led_thread.start()


def live_view_capture_thread(cap) -> None:
    """
    Thread for continuous camera frame capture and save to temporary file for web view.
    Now using SafeCameraManager for better memory management.
    """
    if camera_manager:
        camera_manager.live_view_thread_safe()
    else:
        print("❌ [LiveView] Camera manager not initialized")


def validate_environment_variables() -> bool:
    """Check required environment variables."""
    required_vars = [API_ENDPOINT, DB_FILE, IMAGE_DIR, PICTURE_OUTPUT_DIR, 
                     YOLOV5_REPO_PATH, LP_DETECTOR_MODEL_PATH, LP_OCR_MODEL_PATH]
    if not all(required_vars):
        print("❌ Lỗi: Một hoặc nhiều biến môi trường quan trọng chưa được thiết lập trong file .env.")
        log_error("Một hoặc nhiều biến môi trường quan trọng chưa được thiết lập trong file .env.", category="ENVIRONMENT")
        return False
    return True

# --- VALIDATION ---
if not validate_environment_variables():
    exit(1)

try:
    import function.helper as helper
    print("✅ Tải thành công các module helper tùy chỉnh.")
except ImportError:
    print("❌ Cảnh báo: Không thể tải các module helper. Sử dụng hàm giả lập.")
    class MockHelper:
        _plate_counter = 0
        @classmethod
        def read_plate(cls, model, image):
            cls._plate_counter +=1
            if time.time() % 10 > 2:
                 return f"MOCK{int(time.time())%1000 + cls._plate_counter:04d}LP"
            return "unknown"
    helper = MockHelper()

def init_db() -> None:
    """Initialize SQLite database using SafeDatabaseManager."""
    db_manager.init_database()
    print("✅ [DB] CSDL đã được khởi tạo với SafeDatabaseManager.")
    ensure_directories_exist(IMAGE_DIR, PICTURE_OUTPUT_DIR, TMP_DIR)


def send_event_to_server(event_payload: dict, image_data_bytes: bytes = None) -> str:
    """
    Send complete event object to server endpoint.
    Now using NetworkManager for better error handling.
    """
    result = network_manager.send_event_to_server(event_payload, image_data_bytes)
    
    # Convert SyncResult to legacy string format for compatibility
    if result == SyncResult.SUCCESS:
        return 'success'
    elif result == SyncResult.PERMANENT_FAILURE:
        return 'permanent_failure'
    else:
        return 'temporary_failure'


def sync_offline_data_to_server():
    """Improved sync function using new managers."""
    while True:
        try:
            # Wait for work or timeout after 60 seconds
            thread_manager.wait_for_sync_work(timeout=60.0)
            
            # Don't sync while processing vehicle events
            if thread_manager.is_vehicle_processing():
                time.sleep(0.5)
                continue

            # Get unsynced records using safe database manager
            unsynced_records = db_manager.get_unsynced_records(limit=1)
            
            if not unsynced_records:
                # No more work
                thread_manager.clear_sync_work()
                continue
                
            record = unsynced_records[0]
            print(f"🔄 [SyncDB] Processing record ID: {record['id']}, Plate: {record['plate']}")
            
            # Determine event type and details
            status_int = record['status']
            details_payload = f"DB_ID: {record['id']}"
            is_out_event = False
            
            # Map database status to server event type
            if status_int == STATUS_COMPLETED:
                is_out_event = True
                event_type = "OUT"
            elif status_int == STATUS_INSIDE:
                event_type = "IN"
            elif status_int == STATUS_FAIL_NO_PLATE:
                event_type = "NO_PLATE_DETECTED"
                details_payload += " - Lỗi: AI không nhận dạng được biển số."
            elif status_int == STATUS_FAIL_PLATE_INSIDE:
                event_type = "TOKEN_DUPLICATED"
                details_payload += " - Lỗi: Biển số đã có trong bãi với thẻ khác."
            elif status_int == STATUS_FAIL_PLATE_MISMATCH:
                is_out_event = True
                event_type = "PLATE_MISMATCH"
                details_payload += " - Lỗi: Biển số ra không khớp biển số vào."
            else:
                event_type = "FAIL_OUT"
                details_payload += " - Lỗi hệ thống không xác định."

            # Get correct timestamp and image
            timestamp = record['time_out'] if is_out_event and record['time_out'] else record['time_in']
            image_filename = record['image_path_out'] if is_out_event and record['image_path_out'] else record['image_path_in']
            
            # Load image data if available
            image_bytes = None
            if image_filename:
                full_image_path = os.path.join(PICTURE_OUTPUT_DIR, image_filename)
                if os.path.exists(full_image_path):
                    try:
                        with open(full_image_path, 'rb') as img_file:
                            image_bytes = img_file.read()
                    except IOError as e:
                        log_error(f"SyncDB: Error reading image {full_image_path} for ID {record['id']}: {e}", 
                                category="SYNC/FS", exception_obj=e)
                        continue
                else:
                    log_error(f"SyncDB: Image file not found {full_image_path} for log ID {record['id']}", 
                            category="SYNC/FS")

            # Create event payload using new helper function
            event_payload = create_event_payload(
                uid=UID,
                plate=record['plate'],
                rfid_token=record['rfid_token'],
                timestamp=timestamp,
                event_type=event_type,
                details=details_payload,
                device_db_id=record['id']
            )

            # Send to server using NetworkManager
            result = network_manager.send_event_to_server(event_payload, image_bytes)

            # Handle result
            if result == SyncResult.SUCCESS:
                if db_manager.mark_as_synced(record['id']):
                    print(f"✅ [SyncDB] Record ID: {record['id']} marked as synced")
                    thread_manager.signal_sync_work()  # Check for more work
                    
            elif result == SyncResult.PERMANENT_FAILURE:
                if db_manager.mark_as_invalid(record['id']):
                    print(f"🚫 [SyncDB] Record ID: {record['id']} marked as invalid due to permanent failure")
                    thread_manager.signal_sync_work()
                    
            else:  # Temporary failure or network error
                print(f"⏳ [SyncDB] Temporary failure for record ID: {record['id']}. Will retry later")
                thread_manager.clear_sync_work()

        except Exception as e:
            print(f"🔥 [SyncDB] Critical error in sync thread: {e}")
            log_error("Critical error in DB sync thread", category="SYNC_DB", exception_obj=e)
            thread_manager.clear_sync_work()
            time.sleep(30)  # Wait before retrying

def _save_vehicle_images(base_filename_part, event_type, original_frame, cropped_frame=None):
    """
    Hàm helper để lưu ảnh gốc và ảnh cắt vào thư mục picture.
    Tránh lặp lại code và làm cho logic xử lý VÀO/RA gọn gàng hơn.
    Trả về một dict chứa tên các file ảnh đã lưu.
    """
    timestamp_fn = get_vietnam_time_for_filename()
    base_fn = f"{event_type}_{timestamp_fn}_{sanitize_filename_component(base_filename_part)}"
    
    raw_image_filename = f"raw_{base_fn}.jpg"
    # Chỉ tạo tên file crop nếu có ảnh crop thực sự
    crop_image_filename = f"crop_{base_fn}.jpg" if cropped_frame is not None and cropped_frame.size > 0 else None

    image_paths = {"raw": None, "crop": None}

    try:
        raw_path_viewer = os.path.join(PICTURE_OUTPUT_DIR, raw_image_filename)
        cv2.imwrite(raw_path_viewer, original_frame)
        image_paths["raw"] = raw_image_filename
        print(f"🖼️  [FS] Đã lưu ảnh {event_type.upper()} (gốc): {raw_path_viewer}")

        if crop_image_filename:
            crop_path_viewer = os.path.join(PICTURE_OUTPUT_DIR, crop_image_filename)
            cv2.imwrite(crop_path_viewer, cropped_frame)
            image_paths["crop"] = crop_image_filename
            print(f"🖼️  [FS] Đã lưu ảnh {event_type.upper()} (biển số): {crop_path_viewer}")
            
    except Exception as e_img:
        print(f"❌ [FS] Lỗi khi lưu ảnh {event_type.upper()}: {e_img}")
        log_error(f"Lỗi khi lưu ảnh {event_type.upper()} (Plate: {base_filename_part})", category="FILESYSTEM", exception_obj=e_img)

    return image_paths

def _process_vehicle_event(rfid_id, cap):
    """
    Improved vehicle event processing using new managers.
    Thread-safe and with better error handling.
    """
    print("📸 [Main] Bắt đầu chụp ảnh và nhận dạng biển số...")
    
    # Use safe camera capture
    original_frame_to_save = camera_manager.capture_frame_safe(flush_buffer=True)
    if original_frame_to_save is None:
        print("❌ [Main] Không thể lấy khung hình từ camera.")
        log_error("Không thể lấy khung hình từ camera trong vòng lặp chính.", category="CAMERA")
        return

    # AI processing outside of database lock for better performance
    print("📸 [AI] Đang xử lý ảnh để nhận dạng biển số...")
    live_frame_copy = original_frame_to_save.copy()
    plate_detection_results = yolo_LP_detect(live_frame_copy, size=640)
    detected_coords_list = plate_detection_results.pandas().xyxy[0].values.tolist()
    
    cropped_license_plate_img = None
    if detected_coords_list:
        # Sort by area (largest first) and take the biggest detection
        detected_coords_list.sort(key=lambda x: (x[2]-x[0])*(x[3]-x[1]), reverse=True)
        x1, y1, x2, y2 = map(int, detected_coords_list[0][:4])
        
        # Ensure coordinates are within image bounds
        h, w = original_frame_to_save.shape[:2]
        y1, y2 = max(0, y1), min(h, y2)
        x1, x2 = max(0, x1), min(w, x2)
        
        if y2 > y1 and x2 > x1:
            cropped_license_plate_img = original_frame_to_save[y1:y2, x1:x2]
            found_license_plate_text = helper.read_plate(yolo_license_plate, cropped_license_plate_img.copy())
        else:
            found_license_plate_text = helper.read_plate(yolo_license_plate, live_frame_copy)
    else:
        found_license_plate_text = helper.read_plate(yolo_license_plate, live_frame_copy)
    
    # Use safe normalize function
    normalized_plate = safe_normalize_plate(found_license_plate_text)

    # Now use exclusive processing to ensure thread safety
    try:
        with thread_manager.exclusive_processing():
            print(f"   [Main] Exclusive processing started for RFID: {rfid_id}")
            
            # Get vehicle record using database manager
            vehicle_inside_record = db_manager.get_vehicle_inside_by_rfid(str(rfid_id))

            # CHECK PLATE VALIDITY
            if not normalized_plate or normalized_plate == "UNKNOWN":
                print("❌ [AI] Không nhận dạng được biển số hợp lệ.")
                log_error(f"Không nhận dạng được biển số hợp lệ. RFID: {rfid_id}, Raw Plate: {found_license_plate_text}", category="AI/VALIDATION")
                
                # Save error event to database
                current_time_str = get_vietnam_time_str()
                image_paths = _save_vehicle_images(f"rfid_{rfid_id}", "in_fail_no_plate", original_frame_to_save, cropped_license_plate_img)
                
                record_id = db_manager.insert_vehicle_entry(
                    plate="UNKNOWN",
                    rfid_token=str(rfid_id),
                    time_in=current_time_str,
                    image_path_in=image_paths.get("raw"),
                    status=STATUS_FAIL_NO_PLATE
                )
                print(f"💾 [DB] Saved error event 'No plate detected' for RFID: {rfid_id}, ID: {record_id}")
                
                thread_manager.signal_sync_work()
                return

            print(f"🎉 [AI] Detected plate: '{found_license_plate_text}' -> Normalized: '{normalized_plate}'")

            # VEHICLE ENTRY LOGIC
            if vehicle_inside_record is None:
                print("➡️  [Logic] Processing ENTRY...")
                
                # Check if plate is already inside with different RFID
                if db_manager.is_plate_inside(normalized_plate):
                    print(f"🚨 [Logic] VALIDATION FAILED: Plate '{normalized_plate}' already inside with different RFID.")
                    log_error(f"VALIDATION FAILED ENTRY: Plate '{normalized_plate}' (RFID: {rfid_id}) already inside with different RFID.", category="LOGIC/VALIDATION")
                    
                    # Save error event
                    image_paths = _save_vehicle_images(normalized_plate, "in_fail_plate_inside", original_frame_to_save, cropped_license_plate_img)
                    current_time_str = get_vietnam_time_str()
                    
                    record_id = db_manager.insert_vehicle_entry(
                        plate=normalized_plate,
                        rfid_token=str(rfid_id),
                        time_in=current_time_str,
                        image_path_in=image_paths.get("raw"),
                        status=STATUS_FAIL_PLATE_INSIDE
                    )
                    print(f"💾 [DB] Saved error event 'Plate already inside' for RFID: {rfid_id}, ID: {record_id}")
                else:
                    print(f"✅ [Logic] VALIDATION SUCCESS: Plate '{normalized_plate}' valid for entry.")
                    current_time_str = get_vietnam_time_str()
                    image_paths = _save_vehicle_images(normalized_plate, "in", original_frame_to_save, cropped_license_plate_img)
                    
                    record_id = db_manager.insert_vehicle_entry(
                        plate=normalized_plate,
                        rfid_token=str(rfid_id),
                        time_in=current_time_str,
                        image_path_in=image_paths.get("raw"),
                        status=STATUS_INSIDE
                    )
                    print(f"💾 [DB] ENTRY event saved. ID: {record_id}")
                    blink_success_led()

            # VEHICLE EXIT LOGIC
            else:
                print("⬅️  [Logic] Processing EXIT...")
                plate_in_db = vehicle_inside_record['plate']
                db_id_in = vehicle_inside_record['id']
                current_time_str = get_vietnam_time_str()
                
                # Always save exit image for evidence
                image_paths = _save_vehicle_images(normalized_plate, "out", original_frame_to_save, cropped_license_plate_img)

                if normalized_plate != plate_in_db:
                    print(f"🚨 [Logic] SECURITY WARNING: Exit plate '{normalized_plate}' DOES NOT MATCH entry plate '{plate_in_db}'. Access denied.")
                    log_error(f"SECURITY WARNING EXIT: Exit plate '{normalized_plate}' (RFID: {rfid_id}) DOES NOT MATCH entry plate '{plate_in_db}'.", category="LOGIC/SECURITY")
                    
                    # Save security error event as separate record
                    record_id = db_manager.insert_vehicle_entry(
                        plate=normalized_plate,
                        rfid_token=str(rfid_id),
                        time_in=current_time_str,
                        image_path_in=image_paths.get("raw"),
                        status=STATUS_FAIL_PLATE_MISMATCH
                    )
                    print(f"💾 [DB] Saved security error event 'Plate mismatch' for RFID: {rfid_id}, ID: {record_id}")
                else:
                    print(f"✅ [Logic] VALIDATION SUCCESS: Plate '{normalized_plate}' matches. Exit allowed.")
                    
                    success = db_manager.update_vehicle_exit(
                        record_id=db_id_in,
                        time_out=current_time_str,
                        image_path_out=image_paths.get("raw")
                    )
                    
                    if success:
                        print(f"💾 [DB] EXIT event updated for ID: {db_id_in}")
                        blink_success_led()
                    else:
                        print(f"❌ [DB] Failed to update exit for ID: {db_id_in}")
            
            # Signal sync work after every event
            thread_manager.signal_sync_work()

    except Exception as e_txn:
        print(f"🔥 [Main] Critical error in vehicle processing: {e_txn}")
        log_error("Critical error in vehicle processing", category="VEHICLE_PROCESSING", exception_obj=e_txn)
    finally:
        print("   [Main] Vehicle processing completed.")


# --- KHỞI TẠO HỆ THỐNG ---
print("🚀 [Main] Bắt đầu khởi tạo hệ thống...")
init_db()
try:
    print("   [AI] Đang tải model phát hiện biển số...")
    yolo_LP_detect = torch.hub.load(YOLOV5_REPO_PATH, 'custom', path=LP_DETECTOR_MODEL_PATH, source='local', _verbose=False)
    print("   [AI] Đang tải model OCR biển số...")
    yolo_license_plate = torch.hub.load(YOLOV5_REPO_PATH, 'custom', path=LP_OCR_MODEL_PATH, source='local', _verbose=False)
    yolo_license_plate.conf = 0.60
    
    print("   [HW] Khởi tạo camera...")
    camera_manager = SafeCameraManager(0, thread_manager, error_logger, TMP_DIR)
    if not camera_manager.initialize_camera():
        raise IOError("Không thể khởi tạo camera")
    
    print("   [HW] Khởi tạo chân GPIO...")
    GPIO.setwarnings(False)
    GPIO.setmode(GPIO.BCM)
    
    print("   [HW] Khởi tạo đầu đọc RFID...")
    reader = SimpleMFRC522()

    GPIO.setup(GREEN_LED_PIN, GPIO.OUT)
    GPIO.output(GREEN_LED_PIN, GPIO.LOW) # Đảm bảo đèn tắt khi khởi động

    print("✅ [Main] Model AI, Camera, GPIO và Đầu đọc RFID đã được khởi tạo thành công!")
except Exception as e:
    print(f"🔥 [Main] LỖI NGHIÊM TRỌNG khi khởi tạo: {e}")
    log_error("LỖI NGHIÊM TRỌNG khi khởi tạo hệ thống", category="INITIALIZATION", exception_obj=e)
    exit()

# Clear events and check for unsynced data
thread_manager.vehicle_event.clear()
thread_manager.clear_sync_work()

if db_manager.has_unsynced_data():
    print("   [Main] Phát hiện dữ liệu cũ chưa đồng bộ. Bật tín hiệu cho luồng sync DB.")
    thread_manager.signal_sync_work()

sync_thread = threading.Thread(target=sync_offline_data_to_server, daemon=True)
sync_thread.start()
print("🚀 [Main] Đã khởi động luồng đồng bộ CSDL theo tín hiệu.")

# --- LIVE VIEW THREAD ---
print("🚀 [Main] Khởi động luồng xem camera trực tiếp...")
thread_manager.start_live_view()
live_view_thread = threading.Thread(target=live_view_capture_thread, args=(None,), daemon=True)
live_view_thread.start()

# --- VÒNG LẶP CHÍNH CỦA ỨNG DỤNG (ĐÃ ĐƯỢC TÁI CẤU TRÚC) ---
print("✅ [Main] Hệ thống sẵn sàng. Bắt đầu vòng lặp chính...")
try:
    while True:
        print("\n💡 [Main] Vui lòng đưa thẻ vào đầu đọc...")
        rfid_id, rfid_text = reader.read()

        print(f"💳 [Main] Phát hiện thẻ! ID: {rfid_id}.")
        
        # Use improved processing function with thread safety
        _process_vehicle_event(rfid_id, None)  # camera_manager is global now
        
        time.sleep(1) # Nghỉ một chút trước khi chờ lần quẹt thẻ tiếp theo

except KeyboardInterrupt:
    print("\n🛑 [Main] Phát hiện ngắt từ bàn phím. Đang tắt chương trình...")
    log_error("Chương trình bị ngắt bởi người dùng (KeyboardInterrupt).", category="SYSTEM")
except Exception as e_main_loop:
    print(f"🔥 [Main] Một lỗi nghiêm trọng, chưa được xử lý đã xảy ra trong vòng lặp chính: {e_main_loop}")
    log_error("Một lỗi nghiêm trọng, chưa được xử lý đã xảy ra trong vòng lặp chính.", category="FATAL", exception_obj=e_main_loop) 
finally:
    print("🧹 [Main] Dọn dẹp tài nguyên...")
    thread_manager.stop_live_view()
    if 'live_view_thread' in locals() and live_view_thread.is_alive():
        live_view_thread.join(timeout=1)
    if 'camera_manager' in locals():
        camera_manager.release()
    if 'network_manager' in locals():
        network_manager.close()
    if 'db_manager' in locals():
        db_manager.close_connections()
    if 'GPIO' in locals():
        try: 
            GPIO.cleanup()
            print("   [Main] GPIO đã được dọn dẹp.")
        except Exception as e_gpio:
            print(f"   [Main] Lỗi khi dọn dẹp GPIO: {e_gpio}")
    print("👋 [Main] Chương trình đã kết thúc.")