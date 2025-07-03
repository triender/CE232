import cv2
import torch
import os
import time
from datetime import datetime, timezone, timedelta
import RPi.GPIO as GPIO
from mfrc522 import SimpleMFRC522
import requests
import sqlite3
import threading
from dotenv import load_dotenv
import json
import traceback
from filelock import FileLock
from constants import *
from utils import get_vietnam_time_str, get_vietnam_time_for_filename, normalize_plate, sanitize_filename_component, ensure_directories_exist

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

# --- Threading locks and events ---
DB_LOCK_FILE = DB_FILE + ".lock"
DB_ACCESS_LOCK = FileLock(DB_LOCK_FILE, timeout=15)
CAMERA_LOCK = threading.Lock()
VEHICLE_EVENT = threading.Event()
SYNC_WORK_AVAILABLE = threading.Event()
LIVE_VIEW_THREAD_RUNNING = threading.Event()

# --- Cài đặt GPIO ---

# --- LOGGING FUNCTIONS ---
def log_error(message: str, category: str = "GENERAL", exception_obj: Exception = None) -> None:
    """Log error messages to error log file."""
    try:
        with open(ERROR_LOG_FILE, "a", encoding="utf-8") as f:
            f.write(f"[{get_vietnam_time_str()}] [{category}] {message}\n")
            if exception_obj:
                f.write(traceback.format_exc())
                f.write("-" * 50 + "\n")
    except Exception as e:
        print(f"🔥 [LogError] Failed to write to error log: {e}")


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
    """
    output_path = os.path.join(TMP_DIR, "live_view.jpg")
    print(f"🖼️  [LiveView] Luồng xem trực tiếp đã bắt đầu. Sẽ lưu ảnh vào: {output_path}")
    while LIVE_VIEW_THREAD_RUNNING.is_set():
        try:
            with CAMERA_LOCK:
                if not cap.isOpened():
                    print("🖼️  [LiveView] Cảnh báo: Camera không mở.")
                    time.sleep(0.5)
                    continue
                ret, frame = cap.read()

            if ret:
                is_success, im_buf_arr = cv2.imencode(".jpg", frame, [int(cv2.IMWRITE_JPEG_QUALITY), 85])
                if is_success:
                    tmp_output_path = output_path + ".tmp"
                    with open(tmp_output_path, "wb") as f:
                        f.write(im_buf_arr)
                    os.rename(tmp_output_path, output_path)
                else:
                    print("🖼️  [LiveView] Cảnh báo: Không thể mã hóa khung hình thành JPEG.")
            else:
                print("🖼️  [LiveView] Cảnh báo: Không thể đọc khung hình từ camera (ret=False).")

        except Exception as e:
            print(f"🖼️  [LiveView] Lỗi Exception: {e}")
            log_error(f"Lỗi trong luồng xem trực tiếp: {e}", "LIVE_VIEW")
        
        time.sleep(0.5)


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
    """Initialize SQLite database."""
    with DB_ACCESS_LOCK:
        with sqlite3.connect(DB_FILE, timeout=10.0) as conn:
            cursor = conn.cursor()
            # Allow image_path_in and image_path_out to be NULL
            # to handle cases without images (e.g.: force_out from web or photo capture errors)
            cursor.execute('''
                CREATE TABLE IF NOT EXISTS parking_log (
                    id INTEGER PRIMARY KEY AUTOINCREMENT, 
                    plate TEXT NOT NULL, 
                    rfid_token TEXT NOT NULL,
                    time_in TEXT NOT NULL, 
                    time_out TEXT, 
                    image_path_in TEXT, 
                    image_path_out TEXT,
                    status INTEGER NOT NULL, 
                    synced_to_server INTEGER NOT NULL DEFAULT 0
                )
            ''')
            cursor.execute("CREATE INDEX IF NOT EXISTS idx_token_status ON parking_log (rfid_token, status)")
    print("✅ [DB] CSDL đã được khởi tạo.")
    ensure_directories_exist(IMAGE_DIR, PICTURE_OUTPUT_DIR, TMP_DIR)


def send_event_to_server(event_payload: dict, image_data_bytes: bytes = None) -> str:
    """
    Send complete event object to server endpoint.
    Updated for Express/Multer compatibility on server side.
    """
    log_identifier = event_payload.get('device_db_id') or event_payload.get('timestamp')
    print(f"📡 [Network] Chuẩn bị gửi sự kiện: ID/Time {log_identifier}, Type: {event_payload.get('event_type')}")

    # Server controller (Node.js/Express) expects individual fields in form-data,
    # not a single JSON string.
    # Rename 'rfid_token' to 'token' to match server.
    if 'rfid_token' in event_payload:
        event_payload['token'] = event_payload.pop('rfid_token')

    files_payload = {}
    if image_data_bytes:
        # When there's an image, request will be multipart/form-data.
        # `requests` will automatically handle putting `event_payload` into data fields.
        files_payload['image'] = (f"img_{log_identifier}.jpg", image_data_bytes, 'image/jpeg')
    
    try:
        if image_data_bytes:
            # Send as multipart/form-data
            response = requests.post(API_ENDPOINT, data=event_payload, files=files_payload, timeout=(5, 20))
        else:
            # Send as application/json
            response = requests.post(API_ENDPOINT, json=event_payload, timeout=(5, 15))

        if 200 <= response.status_code < 300:
            print(f"✅ [Network] Server đã chấp nhận sự kiện {log_identifier}.")
            return 'success'
        elif 400 <= response.status_code < 500:
            response_text = response.text
            print(f"❌ [Network] Server từ chối sự kiện {log_identifier} (Lỗi Client: {response.status_code}): {response_text}")
            log_error(f"Server từ chối sự kiện {log_identifier} (Code: {response.status_code}): {response_text}", category="SERVER_RESPONSE")
            return 'permanent_failure'
        else:
            print(f"❌ [Network] Lỗi phía server cho sự kiện {log_identifier} (Code: {response.status_code}).")
            log_error(f"Lỗi server cho sự kiện {log_identifier} (Code: {response.status_code}): {response.text}", category="SERVER_RESPONSE")
            return 'temporary_failure'

    except requests.exceptions.RequestException as e:
        print(f"❌ [Network] Lỗi kết nối hoặc timeout cho sự kiện {log_identifier}: {e}.")
        log_error(f"Lỗi kết nối hoặc timeout cho sự kiện {log_identifier}", category="NETWORK", exception_obj=e)
        return 'temporary_failure'


def sync_offline_data_to_server():
    while True:
        try:
            SYNC_WORK_AVAILABLE.wait(timeout=60.0)
            if VEHICLE_EVENT.is_set():
                time.sleep(0.5)
                continue

            with DB_ACCESS_LOCK:
                if VEHICLE_EVENT.is_set(): continue

                with sqlite3.connect(DB_FILE, timeout=10.0) as conn:
                    conn.row_factory = sqlite3.Row
                    cursor = conn.cursor()
                    cursor.execute("SELECT * FROM parking_log WHERE synced_to_server = 0 LIMIT 1")
                    record = cursor.fetchone()

                    if record:
                        print(f"🔄 [SyncDB] Xử lý bản ghi ID: {record['id']}, Biển số: {record['plate']}")
                        status_int = record['status']
                        
                        is_out_event = (status_int == STATUS_COMPLETED)
                        event_type = "OUT" if is_out_event else "IN"
                        timestamp = record['time_out'] if is_out_event else record['time_in']
                        image_filename = record['image_path_out'] if is_out_event else record['image_path_in']
                        
                        image_bytes = None
                        # FIX: Handle cases without images (e.g.: force_out from web)
                        if image_filename:
                            full_image_path = os.path.join(PICTURE_OUTPUT_DIR, image_filename)
                            if not os.path.exists(full_image_path):
                                log_error(f"SyncDB: File ảnh không tồn tại {full_image_path} cho log ID {record['id']}. Đánh dấu là không hợp lệ.", category="SYNC/FS")
                                # Mark as synced to avoid retrying a record without image
                                conn.execute("UPDATE parking_log SET status = ?, synced_to_server = 1 WHERE id = ?", (STATUS_INVALID, record['id']))
                                conn.commit()
                                SYNC_WORK_AVAILABLE.set() # Continue checking other work
                                continue

                            try:
                                with open(full_image_path, 'rb') as img_file:
                                    image_bytes = img_file.read()
                            except IOError as e_io:
                                log_error(f"SyncDB: Lỗi IO khi đọc ảnh {full_image_path} cho ID {record['id']}: {e_io}", category="SYNC/FS", exception_obj=e_io)
                                SYNC_WORK_AVAILABLE.clear() # Wait before retrying file read
                                continue
                        else:
                            print(f"   [SyncDB] Không có file ảnh liên kết với bản ghi ID: {record['id']}. Vẫn sẽ gửi sự kiện không có ảnh.")

                        # Build event payload
                        event_payload = {
                            "uid": UID,
                            "plate": record['plate'],
                            "token": record['rfid_token'],
                            "timestamp": timestamp,
                            "event_type": event_type,
                            "status_event": "SUCCESS",
                            "details": f"DB_ID: {record['id']}",
                            "device_db_id": record['id']
                        }

                        result = send_event_to_server(event_payload, image_bytes)

                        # Status 'already_synced' no longer applicable as new server is stateless
                        if result == 'success':
                            conn.execute("UPDATE parking_log SET synced_to_server = 1 WHERE id = ?", (record['id'],))
                            conn.commit()
                            print(f"✅ [SyncDB] Record ID: {record['id']} marked as synced.")
                            SYNC_WORK_AVAILABLE.set() # Check for more work immediately
                        elif result == 'permanent_failure':
                            conn.execute("UPDATE parking_log SET synced_to_server = 1, status = ? WHERE id = ?", (STATUS_INVALID, record['id']))
                            conn.commit()
                            print(f"🚫 [SyncDB] Record ID: {record['id']} marked as invalid due to permanent failure.")
                            SYNC_WORK_AVAILABLE.set()
                        else: # temporary_failure
                            print(f"⏳ [SyncDB] Temporary failure for record ID: {record['id']}. Will retry later.")
                            SYNC_WORK_AVAILABLE.clear()
                    else:
                        # No more work
                        SYNC_WORK_AVAILABLE.clear()
        except Exception as e:
            print(f"🔥 [SyncDB] Critical error in sync thread: {e}")
            log_error("Critical error in DB sync thread", category="SYNC_DB", exception_obj=e)
            SYNC_WORK_AVAILABLE.clear() # Stop trying on critical error
            time.sleep(30)

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
    Hàm này đóng gói toàn bộ logic xử lý cho một sự kiện xe, từ lúc quẹt thẻ đến giao dịch CSDL.
    Được gọi từ vòng lặp chính để giữ cho vòng lặp gọn gàng.
    """
    print("📸 [Main] Bắt đầu chụp ảnh và nhận dạng biển số...")
    with CAMERA_LOCK:
        for _ in range(5): cap.read() # Xả buffer để lấy khung hình mới nhất
        ret, live_frame = cap.read()

    if not ret or live_frame is None:
        print("❌ [Main] Không thể lấy khung hình từ camera.")
        log_error("Không thể lấy khung hình từ camera trong vòng lặp chính.", category="CAMERA")
        return

    # Tối ưu hóa: Di chuyển phần xử lý AI tốn thời gian ra ngoài DB Lock
    print("📸 [AI] Đang xử lý ảnh để nhận dạng biển số (ngoài DB Lock)...")
    original_frame_to_save = live_frame.copy()
    plate_detection_results = yolo_LP_detect(live_frame.copy(), size=640)
    detected_coords_list = plate_detection_results.pandas().xyxy[0].values.tolist()
    
    cropped_license_plate_img = None
    if detected_coords_list:
        # Sắp xếp các biển số phát hiện được theo diện tích giảm dần và lấy cái lớn nhất
        detected_coords_list.sort(key=lambda x: (x[2]-x[0])*(x[3]-x[1]), reverse=True)
        x1, y1, x2, y2 = map(int, detected_coords_list[0][:4])
        # Đảm bảo tọa độ cắt nằm trong kích thước ảnh
        y1, y2 = max(0, y1), min(original_frame_to_save.shape[0], y2)
        x1, x2 = max(0, x1), min(original_frame_to_save.shape[1], x2)
        if y2 > y1 and x2 > x1:
            cropped_license_plate_img = original_frame_to_save[y1:y2, x1:x2]
            found_license_plate_text = helper.read_plate(yolo_license_plate, cropped_license_plate_img.copy())
        else: # Nếu tọa độ không hợp lệ, dùng ảnh gốc
            found_license_plate_text = helper.read_plate(yolo_license_plate, live_frame.copy())
    else: # Nếu không phát hiện được biển số, dùng ảnh gốc
        found_license_plate_text = helper.read_plate(yolo_license_plate, live_frame.copy())
    
    normalized_plate = normalize_plate(found_license_plate_text)

    # Sau khi có biển số, mới vào DB Lock để xử lý logic
    with DB_ACCESS_LOCK:
        try:
            print(f"   [Main] Đã giành được khóa CSDL. Bắt đầu xử lý logic cho thẻ ID: {rfid_id}")
            with sqlite3.connect(DB_FILE, timeout=10.0) as conn:
                conn.row_factory = sqlite3.Row
                cursor = conn.cursor()
                cursor.execute("SELECT * FROM parking_log WHERE rfid_token = ? AND status = ?", (str(rfid_id), STATUS_INSIDE))
                vehicle_inside_record = cursor.fetchone()

            # KIỂM TRA BIỂN SỐ
            if not normalized_plate or normalized_plate == "UNKNOWN":
                print("❌ [AI] Không nhận dạng được biển số hợp lệ.")
                log_error(f"Không nhận dạng được biển số hợp lệ. RFID: {rfid_id}, Raw Plate: {found_license_plate_text}", category="AI/VALIDATION")
                # Không lưu ảnh vì không có biển số để đặt tên file
                return # Kết thúc xử lý cho sự kiện này

            print(f"🎉 [AI] Phát hiện biển số: '{found_license_plate_text}' -> Chuẩn hóa: '{normalized_plate}'")

            # --- LOGIC XỬ LÝ VÀO/RA ---
            # XE VÀO
            if vehicle_inside_record is None:
                print("➡️  [Logic] Xử lý luồng VÀO...")
                with sqlite3.connect(DB_FILE, timeout=10.0) as conn:
                    cursor = conn.cursor()
                    cursor.execute("SELECT id FROM parking_log WHERE plate = ? AND status = ?", (normalized_plate, STATUS_INSIDE))
                    is_plate_already_inside = cursor.fetchone()
                
                if is_plate_already_inside:
                    print(f"🚨 [Logic] Xác thực THẤT BẠI: Biển số '{normalized_plate}' đã được ghi nhận ở trong bãi với một thẻ khác.")
                    log_error(f"Xác thực THẤT BẠI VÀO: Biển số '{normalized_plate}' (RFID: {rfid_id}) đã ở trong bãi với thẻ khác.", category="LOGIC/VALIDATION")
                    _save_vehicle_images(normalized_plate, "in_fail", original_frame_to_save, cropped_license_plate_img)
                else:
                    print(f"✅ [Logic] Xác thực THÀNH CÔNG: Biển số '{normalized_plate}' hợp lệ để vào.")
                    current_time_str = get_vietnam_time_str()
                    image_paths = _save_vehicle_images(normalized_plate, "in", original_frame_to_save, cropped_license_plate_img)
                    
                    with sqlite3.connect(DB_FILE, timeout=10.0) as conn:
                        cursor = conn.cursor()
                        cursor.execute("INSERT INTO parking_log (plate, rfid_token, time_in, image_path_in, status, synced_to_server) VALUES (?, ?, ?, ?, ?, ?)",
                                        (normalized_plate, str(rfid_id), current_time_str, image_paths.get("raw"), STATUS_INSIDE, 0))
                        last_id = cursor.lastrowid
                        conn.commit()
                        print(f"💾 [DB] Sự kiện VÀO đã được lưu cục bộ. ID: {last_id}")
                        blink_success_led()

            # XE RA
            else:
                print("⬅️  [Logic] Xử lý luồng RA...")
                plate_in_db = vehicle_inside_record['plate']
                db_id_in = vehicle_inside_record['id']
                current_time_str = get_vietnam_time_str()
                
                # Luôn lưu ảnh khi xe ra để có bằng chứng
                image_paths = _save_vehicle_images(normalized_plate, "out", original_frame_to_save, cropped_license_plate_img)

                if normalized_plate != plate_in_db:
                    print(f"🚨 [Logic] Cảnh báo An ninh: Biển số ra '{normalized_plate}' KHÔNG KHỚP biển số vào '{plate_in_db}'. Từ chối cho ra.")
                    log_error(f"Cảnh báo An ninh RA: Biển số ra '{normalized_plate}' (RFID: {rfid_id}) KHÔNG KHỚP biển vào '{plate_in_db}'.", category="LOGIC/SECURITY")
                else:
                    print(f"✅ [Logic] Xác thực THÀNH CÔNG: Biển số '{normalized_plate}' khớp. Cho phép xe ra.")
                    with sqlite3.connect(DB_FILE, timeout=10.0) as conn:
                        cursor = conn.cursor()
                        cursor.execute("UPDATE parking_log SET time_out = ?, image_path_out = ?, status = ?, synced_to_server = ? WHERE id = ?",
                                        (current_time_str, image_paths.get("raw"), STATUS_COMPLETED, 0, db_id_in))
                        conn.commit()
                        print(f"💾 [DB] Sự kiện RA đã được cập nhật cục bộ cho ID: {db_id_in}")
                        blink_success_led()
            
            # Sau mỗi sự kiện, dù thành công hay thất bại, đều trigger luồng sync
            SYNC_WORK_AVAILABLE.set()

        except Exception as e_txn:
            print(f"🔥 [Main] Lỗi nghiêm trọng trong giao dịch CSDL: {e_txn}")
            log_error("Lỗi nghiêm trọng trong giao dịch CSDL", category="DB_TRANSACTION", exception_obj=e_txn)
        finally:
            print("   [Main] Hoàn tất xử lý logic. Giải phóng khóa CSDL.")


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
    cap = cv2.VideoCapture(0)
    if not cap.isOpened(): raise IOError("Không thể mở webcam")
    
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

VEHICLE_EVENT.clear()
SYNC_WORK_AVAILABLE.clear()
with DB_ACCESS_LOCK:
    with sqlite3.connect(DB_FILE) as conn:
        if conn.execute("SELECT 1 FROM parking_log WHERE synced_to_server = 0 LIMIT 1").fetchone():
            print("   [Main] Phát hiện dữ liệu cũ chưa đồng bộ. Bật tín hiệu cho luồng sync DB.")
            SYNC_WORK_AVAILABLE.set()

sync_thread = threading.Thread(target=sync_offline_data_to_server, daemon=True)
sync_thread.start()
print("🚀 [Main] Đã khởi động luồng đồng bộ CSDL theo tín hiệu.")

# --- LIVE VIEW THREAD ---
print("🚀 [Main] Khởi động luồng xem camera trực tiếp...")
LIVE_VIEW_THREAD_RUNNING.set()
live_view_thread = threading.Thread(target=live_view_capture_thread, args=(cap,), daemon=True)
live_view_thread.start()

# --- VÒNG LẶP CHÍNH CỦA ỨNG DỤNG (ĐÃ ĐƯỢC TÁI CẤU TRÚC) ---
print("✅ [Main] Hệ thống sẵn sàng. Bắt đầu vòng lặp chính...")
try:
    while True:
        print("\n💡 [Main] Vui lòng đưa thẻ vào đầu đọc...")
        rfid_id, rfid_text = reader.read()

        print(f"💳 [Main] Phát hiện thẻ! ID: {rfid_id}. Dựng cờ VEHICLE_EVENT...")
        VEHICLE_EVENT.set() # Dựng cờ để tạm dừng các luồng đồng bộ

        # Gọi hàm xử lý chính, đã được tái cấu trúc
        _process_vehicle_event(rfid_id, cap)

        print("   [Main] Hạ cờ VEHICLE_EVENT, cho phép đồng bộ hoạt động trở lại.")
        VEHICLE_EVENT.clear() # Hạ cờ để các luồng khác tiếp tục
        
        time.sleep(1) # Nghỉ một chút trước khi chờ lần quẹt thẻ tiếp theo

except KeyboardInterrupt:
    print("\n🛑 [Main] Phát hiện ngắt từ bàn phím. Đang tắt chương trình...")
    log_error("Chương trình bị ngắt bởi người dùng (KeyboardInterrupt).", category="SYSTEM")
except Exception as e_main_loop:
    print(f"🔥 [Main] Một lỗi nghiêm trọng, chưa được xử lý đã xảy ra trong vòng lặp chính: {e_main_loop}")
    log_error("Một lỗi nghiêm trọng, chưa được xử lý đã xảy ra trong vòng lặp chính.", category="FATAL", exception_obj=e_main_loop) 
finally:
    print("🧹 [Main] Dọn dẹp tài nguyên...")
    LIVE_VIEW_THREAD_RUNNING.clear() # Tắt luồng xem trực tiếp
    if 'live_view_thread' in locals() and live_view_thread.is_alive():
        live_view_thread.join(timeout=1)
    if 'cap' in locals() and cap.isOpened():
        cap.release()
        print("   [Main] Camera đã được giải phóng.")
    if 'GPIO' in locals():
        try: 
            GPIO.cleanup()
            print("   [Main] GPIO đã được dọn dẹp.")
        except Exception as e_gpio:
            print(f"   [Main] Lỗi khi dọn dẹp GPIO: {e_gpio}")
    print("👋 [Main] Chương trình đã kết thúc.")