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

# --- CẤU HÌNH VÀ HẰNG SỐ ---
load_dotenv()
API_ENDPOINT = os.getenv("API_ENDPOINT", "http://localhost:3000/parking/add")
UID = os.getenv("UID")
DB_FILE = os.getenv("DB_FILE", "parking_data.db")
IMAGE_DIR = os.getenv("IMAGE_DIR", "offline_images")
PICTURE_OUTPUT_DIR = os.getenv("PICTURE_OUTPUT_DIR", "picture")
YOLOV5_REPO_PATH = os.getenv("YOLOV5_REPO_PATH")
LP_DETECTOR_MODEL_PATH = os.getenv("LP_DETECTOR_MODEL_PATH")
LP_OCR_MODEL_PATH = os.getenv("LP_OCR_MODEL_PATH")

ACCESS_LOG_FILE = "access_log.jsonl"
ERROR_LOG_FILE = "error_log.txt"

STATUS_INSIDE = 1
STATUS_COMPLETED = 2
STATUS_INVALID = 99
STATUS_MAP_TO_SERVER_API = { STATUS_INSIDE: 0, STATUS_COMPLETED: 1 }
STATUS_MAP_TO_STRING = { STATUS_INSIDE: 'INSIDE', STATUS_COMPLETED: 'COMPLETED', STATUS_INVALID: 'INVALID' }

DB_ACCESS_LOCK = threading.Lock()
VEHICLE_EVENT = threading.Event()
SYNC_WORK_AVAILABLE = threading.Event()

# --- LOGGING FUNCTIONS ---
def log_access(event_type, plate, rfid, status_event, image_paths_event: dict, timestamp_event, details=""): # MODIFIED
    log_entry = {
        "timestamp": timestamp_event,
        "event_type": event_type,  # "IN", "OUT", "FAIL_IN", "FAIL_OUT"
        "plate": plate,
        "rfid_token": str(rfid),
        "status_event": status_event, # e.g. "SUCCESS", "PLATE_MISMATCH", "ALREADY_INSIDE", "NO_PLATE_DETECTED"
        "image_paths": image_paths_event, # MODIFIED from "image_path" to "image_paths"
        "details": details
    }
    try:
        with open(ACCESS_LOG_FILE, "a", encoding="utf-8") as f:
            f.write(json.dumps(log_entry, ensure_ascii=False) + "\n")
    except Exception as e:
        print(f"🔥 [LogAccess] Failed to write to access log: {e}")

def log_error(message, category="GENERAL", exception_obj=None):
    try:
        with open(ERROR_LOG_FILE, "a", encoding="utf-8") as f:
            f.write(f"[{get_vietnam_time_str()}] [{category}] {message}\n")
            if exception_obj:
                f.write(traceback.format_exc())
                f.write("-" * 50 + "\n")
    except Exception as e:
        print(f"🔥 [LogError] Failed to write to error log: {e}")

if not all([API_ENDPOINT, DB_FILE, IMAGE_DIR, PICTURE_OUTPUT_DIR, YOLOV5_REPO_PATH, LP_DETECTOR_MODEL_PATH, LP_OCR_MODEL_PATH]):
    print("❌ Lỗi: Một hoặc nhiều biến môi trường quan trọng chưa được thiết lập trong file .env.")
    log_error("Một hoặc nhiều biến môi trường quan trọng chưa được thiết lập trong file .env.", category="ENVIRONMENT")
    exit()

try:
    import function.utils_rotate as utils_rotate
    import function.helper as helper
    print("✅ Tải thành công các module helper tùy chỉnh.")
except ImportError:
    print("❌ Cảnh báo: Không thể tải các module helper. Sử dụng hàm giả lập.")
    class MockHelper:
        _plate_counter = 0
        @classmethod
        def read_plate(cls, model, image):
            cls._plate_counter +=1
            # Giả lập việc đọc biển số khác nhau cho mỗi lần gọi để test lỗi duplicate
            # return f"MOCKPLATE{int(time.time()*10 % 100) + cls._plate_counter}" 
            if time.time() % 10 > 2:
                 return f"MOCK{int(time.time())%1000 + cls._plate_counter:04d}LP"
            return "unknown" # Hoặc trả về một biển số cố định để test
            # return "60B188188" 
    helper = MockHelper()

def get_vietnam_time_object():
    return datetime.now(timezone(timedelta(hours=7)))
def get_vietnam_time_str():
    return get_vietnam_time_object().strftime("%Y-%m-%d %H:%M:%S")
def get_vietnam_time_for_filename():
    return get_vietnam_time_object().strftime("%d_%m_%Y_%Hh%Mm%S")
def normalize_plate(plate_text: str) -> str:
    if not plate_text: return ""
    return "".join(filter(str.isalnum, plate_text)).upper()
def sanitize_filename_component(name_part: str) -> str:
    return "".join(c if c.isalnum() else "_" for c in str(name_part)).rstrip("_")

def init_db():
    with DB_ACCESS_LOCK:
        with sqlite3.connect(DB_FILE, timeout=10.0) as conn:
            cursor = conn.cursor()
            cursor.execute('''
                CREATE TABLE IF NOT EXISTS parking_log (
                    id INTEGER PRIMARY KEY AUTOINCREMENT, plate TEXT NOT NULL, rfid_token TEXT NOT NULL,
                    time_in TEXT NOT NULL, time_out TEXT, image_path_in TEXT NOT NULL, image_path_out TEXT,
                    status INTEGER NOT NULL, synced_to_server INTEGER NOT NULL DEFAULT 0
                )
            ''')
            cursor.execute("CREATE INDEX IF NOT EXISTS idx_token_status ON parking_log (rfid_token, status)")
    print("✅ [DB] CSDL đã được khởi tạo.")
    os.makedirs(IMAGE_DIR, exist_ok=True)
    os.makedirs(PICTURE_OUTPUT_DIR, exist_ok=True)

def send_data_to_server(uid, log_id, plate_text, token_id, timestamp_str, image_data_bytes, event_status_for_api) -> str:
    print(f"📡 [Network] Đang thử gửi dữ liệu: ID {log_id}, Biển số {plate_text}, Status API: {event_status_for_api}")
    # SỬA ĐỔI: Đổi tên key 'status' thành 'in_or_out' để khớp với API của server Node.js
    payload = { 'uid': uid, 'plate': plate_text, 'token': str(token_id), 'time': timestamp_str, 'in_or_out': event_status_for_api }
    filename_for_server = f"{sanitize_filename_component(plate_text)}_{log_id}_{int(time.time())}.jpg"
    files_payload = {'image': (filename_for_server, image_data_bytes, 'image/jpeg')}
    try:
        response = requests.post(API_ENDPOINT, data=payload, files=files_payload, timeout=(5, 20))
        if 200 <= response.status_code < 300:
            print(f"✅ [Network] Server đã chấp nhận dữ liệu thành công cho ID {log_id}.")
            return 'success'
        elif 400 <= response.status_code < 500:
            response_text = response.text
            print(f"❌ [Network] Server từ chối dữ liệu ID {log_id} không hợp lệ (Mã: {response.status_code}): {response_text}")
            log_error(f"Server từ chối dữ liệu ID {log_id} không hợp lệ (Mã: {response.status_code}): {response_text}", category="SERVER_RESPONSE")
            
            # SỬA ĐỔI: Xử lý thông minh các lỗi cho thấy server đã ở đúng trạng thái
            if "Xe đã có trong bãi" in response_text or "Xe chưa vào, không thể ra" in response_text:
                print(f"ℹ️ [Network] Lỗi này cho thấy server đã ở trạng thái đồng bộ. Đánh dấu là đã đồng bộ.")
                return 'already_synced' # Trạng thái mới để xử lý đặc biệt

            return 'permanent_failure'
        else:
            print(f"❌ [Network] Lỗi phía server khi gửi ID {log_id} (Mã: {response.status_code}).")
            log_error(f"Lỗi phía server khi gửi ID {log_id} (Mã: {response.status_code}): {response.text}", category="SERVER_RESPONSE")
            return 'temporary_failure'
    except requests.exceptions.RequestException as e:
        print(f"❌ [Network] Lỗi kết nối hoặc timeout khi gửi ID {log_id}: {e}.")
        log_error(f"Lỗi kết nối hoặc timeout khi gửi ID {log_id}", category="NETWORK", exception_obj=e)
        return 'temporary_failure'

def sync_offline_data_to_server():
    while True:
        try:
            SYNC_WORK_AVAILABLE.wait(timeout=60.0) # Đợi tín hiệu hoặc timeout 60 giây
            if VEHICLE_EVENT.is_set():
                time.sleep(0.5) # Nếu có xe đang xử lý, nhường quyền, kiểm tra lại sau
                continue

            with DB_ACCESS_LOCK: # Khóa CSDL để thao tác
                if VEHICLE_EVENT.is_set(): continue # Kiểm tra lại cờ xe sau khi có khóa

                with sqlite3.connect(DB_FILE, timeout=10.0) as conn:
                    conn.row_factory = sqlite3.Row
                    cursor = conn.cursor()
                    # Lấy một bản ghi chưa đồng bộ
                    cursor.execute("SELECT * FROM parking_log WHERE synced_to_server = 0 LIMIT 1")
                    record = cursor.fetchone()

                    if record:
                        print(f"🔄 [Sync] Processing record ID: {record['id']}, Plate: {record['plate']}")
                        status_int = record['status']
                        api_status = STATUS_MAP_TO_SERVER_API.get(status_int)

                        # Nếu trạng thái không hợp lệ để gửi lên server API
                        if api_status is None:
                            log_error(f"Sync: Invalid status {status_int} for API sync on record ID {record['id']}. Marking as synced.", category="SYNC")
                            conn.execute("UPDATE parking_log SET synced_to_server = 1 WHERE id = ?", (record['id'],))
                            conn.commit()
                            SYNC_WORK_AVAILABLE.set() # Có thể còn việc khác
                            continue

                        is_out_event = (status_int == STATUS_COMPLETED)
                        timestamp = record['time_out'] if is_out_event else record['time_in']
                        image_filename = record['image_path_out'] if is_out_event else record['image_path_in']
                        full_image_path = os.path.join(PICTURE_OUTPUT_DIR, image_filename)

                        if not os.path.exists(full_image_path):
                            log_error(f"Sync: Image file not found {full_image_path} for log ID {record['id']}. Marking invalid.", category="SYNC/FS")
                            conn.execute("UPDATE parking_log SET status = ?, synced_to_server = 1 WHERE id = ?", (STATUS_INVALID, record['id']))
                            conn.commit()
                            SYNC_WORK_AVAILABLE.set() # Có thể còn việc khác
                            continue

                        image_bytes = b''
                        try:
                            with open(full_image_path, 'rb') as img_file:
                                image_bytes = img_file.read()
                        except IOError as e_io:
                            log_error(f"Sync: IOError reading image {full_image_path} for ID {record['id']}: {e_io}", category="SYNC/FS", exception_obj=e_io)
                            # Không đánh dấu là đã đồng bộ, sẽ thử lại sau hoặc cần can thiệp thủ công nếu lỗi IO persist
                            # Cân nhắc: nếu lỗi IO lặp lại nhiều lần, có thể đánh dấu là STATUS_INVALID
                            # conn.execute("UPDATE parking_log SET status = ?, synced_to_server = 1 WHERE id = ?", (STATUS_INVALID, record['id']))
                            # conn.commit()
                            SYNC_WORK_AVAILABLE.clear() # Tạm dừng, đợi xử lý thủ công hoặc lần sau
                            continue


                        result = send_data_to_server(UID, record['id'], record['plate'], record['rfid_token'], timestamp, image_bytes, api_status)

                        # SỬA ĐỔI: Xử lý kết quả `already_synced` như một thành công
                        if result == 'success' or result == 'already_synced':
                            conn.execute("UPDATE parking_log SET synced_to_server = 1 WHERE id = ?", (record['id'],))
                            conn.commit()
                            print(f"✅ [Sync] Record ID: {record['id']} marked as synced (Result: {result}).")
                            SYNC_WORK_AVAILABLE.set() # Đã xử lý xong, báo có thể còn việc
                        elif result == 'permanent_failure':
                            # Lỗi vĩnh viễn, đánh dấu đã đồng bộ để không thử lại
                            conn.execute("UPDATE parking_log SET synced_to_server = 1, status = ? WHERE id = ?", (STATUS_INVALID, record['id']))
                            conn.commit()
                            print(f"🚫 [Sync] Record ID: {record['id']} marked as synced due to permanent failure.")
                            SYNC_WORK_AVAILABLE.set() # Đã xử lý xong, báo có thể còn việc
                        else: # temporary_failure
                            # Lỗi tạm thời, không làm gì cả, sẽ thử lại sau
                            print(f"⏳ [Sync] Temporary failure for record ID: {record['id']}. Will retry later.")
                            SYNC_WORK_AVAILABLE.clear() # Dừng tín hiệu, đợi timeout hoặc sự kiện mới
                    else:
                        # Không có bản ghi nào cần đồng bộ
                        # print("👍 [Sync] No records to sync.")
                        SYNC_WORK_AVAILABLE.clear() # Không có việc, xóa tín hiệu
        except Exception as e:
            print(f"🔥 [Sync] Lỗi nghiêm trọng trong luồng đồng bộ: {e}")
            log_error("Lỗi nghiêm trọng trong luồng đồng bộ", category="SYNC", exception_obj=e)
            SYNC_WORK_AVAILABLE.clear() # Dừng tín hiệu
            time.sleep(30) # Nghỉ 30 giây trước khi thử lại vòng lặp
            # SYNC_WORK_AVAILABLE.set() # Cân nhắc set lại để chủ động thử lại sau khi nghỉ
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
    print("   [HW] Khởi tạo đầu đọc RFID...")
    reader = SimpleMFRC522()
    print("✅ [Main] Model AI, Camera và Đầu đọc RFID đã được khởi tạo thành công!")
except Exception as e:
    print(f"🔥 [Main] LỖI NGHIÊM TRỌNG khi khởi tạo: {e}")
    log_error("LỖI NGHIÊM TRỌNG khi khởi tạo hệ thống", category="INITIALIZATION", exception_obj=e)
    exit()

VEHICLE_EVENT.clear()
SYNC_WORK_AVAILABLE.clear()
with DB_ACCESS_LOCK:
    with sqlite3.connect(DB_FILE) as conn:
        if conn.execute("SELECT 1 FROM parking_log WHERE synced_to_server = 0 LIMIT 1").fetchone():
            print("   [Main] Phát hiện dữ liệu cũ chưa đồng bộ. Bật tín hiệu cho luồng sync.")
            SYNC_WORK_AVAILABLE.set()

sync_thread = threading.Thread(target=sync_offline_data_to_server, daemon=True)
sync_thread.start()
print("🚀 [Main] Đã khởi động luồng đồng bộ theo tín hiệu.")

# --- VÒNG LẶP CHÍNH CỦA ỨNG DỤNG ---
print("✅ [Main] Hệ thống sẵn sàng. Bắt đầu vòng lặp chính...")
try:
    while True:
        print("\n💡 [Main] Vui lòng đưa thẻ vào đầu đọc...")
        rfid_id, rfid_text = reader.read()

        print(f"💳 [Main] Phát hiện thẻ! ID: {rfid_id}. Dựng cờ VEHICLE_EVENT...")
        VEHICLE_EVENT.set()

        print("📸 [Main] Bắt đầu chụp ảnh và nhận dạng biển số...")

        for _ in range(5): cap.read()
        ret, live_frame = cap.read()

        if not ret or live_frame is None:
            print("❌ [Main] Không thể lấy khung hình từ camera.")
            log_error("Không thể lấy khung hình từ camera trong vòng lặp chính.", category="CAMERA")
            VEHICLE_EVENT.clear()
            continue

        # Biến để lưu ảnh crop, sẽ được dùng ở cả IN và OUT
        cropped_license_plate_img = None
        normalized_plate = ""
        original_frame_to_save = None # Sẽ được gán sau khi chụp ảnh thành công

        with DB_ACCESS_LOCK: # Khóa truy cập CSDL cho toàn bộ quá trình xử lý thẻ RFID
            try:
                print(f"   [Main] Đã giành được khóa CSDL. Bắt đầu xử lý cho thẻ ID: {rfid_id}")
                # 1. KIỂM TRA THẺ RFID TRONG CSDL
                with sqlite3.connect(DB_FILE, timeout=10.0) as conn_check_rfid:
                    conn_check_rfid.row_factory = sqlite3.Row
                    cursor_check_rfid = conn_check_rfid.cursor()
                    cursor_check_rfid.execute("SELECT * FROM parking_log WHERE rfid_token = ? AND status = ?", (str(rfid_id), STATUS_INSIDE))
                    vehicle_inside_record = cursor_check_rfid.fetchone()

                # 2. CHỤP ẢNH VÀ NHẬN DẠNG BIỂN SỐ
                print("📸 [AI] Đang chụp và xử lý ảnh...")
                for _ in range(3): cap.read()
                ret, live_frame = cap.read()
                if not ret:
                    print("❌ [AI] Không thể chụp khung hình từ camera.")
                    log_error("Không thể chụp khung hình từ camera cho AI.", category="CAMERA/AI")
                    VEHICLE_EVENT.clear()
                    continue # Bỏ qua và chờ lượt quét thẻ tiếp theo

                original_frame_to_save = live_frame.copy()
                # Phát hiện vùng biển số
                plate_detection_results = yolo_LP_detect(live_frame.copy(), size=640)
                detected_coords_list = plate_detection_results.pandas().xyxy[0].values.tolist()

                if detected_coords_list:
                    detected_coords_list.sort(key=lambda x: (x[2]-x[0])*(x[3]-x[1]), reverse=True)
                    x1, y1, x2, y2 = map(int, detected_coords_list[0][:4])
                    y1, y2 = max(0, y1), min(original_frame_to_save.shape[0], y2)
                    x1, x2 = max(0, x1), min(original_frame_to_save.shape[1], x2)
                    if y2 > y1 and x2 > x1:
                        cropped_license_plate_img = original_frame_to_save[y1:y2, x1:x2]
                        found_license_plate_text = helper.read_plate(yolo_license_plate, cropped_license_plate_img.copy())
                    else:
                        found_license_plate_text = helper.read_plate(yolo_license_plate, live_frame.copy())
                else:
                    found_license_plate_text = helper.read_plate(yolo_license_plate, live_frame.copy())
                
                normalized_plate = normalize_plate(found_license_plate_text)

                if not normalized_plate or normalized_plate == "UNKNOWN":
                    print("❌ [AI] Không nhận dạng được biển số hợp lệ.")
                    log_error(f"Không nhận dạng được biển số hợp lệ. RFID: {rfid_id}, Raw Plate: {found_license_plate_text}", category="AI/VALIDATION") 
                    # Pass a dictionary for image_paths_event
                    image_paths_failure_no_plate = {"raw": "", "crop": ""}
                    log_access("FAIL_IN" if vehicle_inside_record is None else "FAIL_OUT", found_license_plate_text, rfid_id, "NO_PLATE_DETECTED", image_paths_failure_no_plate, get_vietnam_time_str()) 
                    VEHICLE_EVENT.clear()
                    continue
                print(f"🎉 [AI] Phát hiện biển số: '{found_license_plate_text}' -> Chuẩn hóa: '{normalized_plate}'")

                # --- 3. LOGIC XỬ LÝ VÀO/RA ---
                # --- NHÁNH 1.1: XE ĐANG VÀO (Thẻ RFID này chưa được ghi nhận là ở trong bãi) ---
                if vehicle_inside_record is None:
                    print("➡️  [Logic] Xử lý luồng VÀO...")
                    is_plate_already_inside = False
                    # Thực hiện kiểm tra biển số trong CSDL để xem có biển số này đã được ghi nhận là ở trong bãi với một thẻ khác hay không
                    with sqlite3.connect(DB_FILE, timeout=10.0) as conn_check_plate:
                        cursor_check_plate = conn_check_plate.cursor()
                        cursor_check_plate.execute("SELECT id FROM parking_log WHERE plate = ? AND status = ?", (normalized_plate, STATUS_INSIDE))
                        if cursor_check_plate.fetchone():
                            is_plate_already_inside = True
                    
                    if is_plate_already_inside:
                        print(f"🚨 [Logic] Xác thực THẤT BẠI: Biển số '{normalized_plate}' đã được ghi nhận ở trong bãi với một thẻ khác. Từ chối cho vào.")
                        log_error(f"Xác thực THẤT BẠI VÀO: Biển số '{normalized_plate}' (RFID: {rfid_id}) đã ở trong bãi với thẻ khác.", category="LOGIC/VALIDATION") 
                        # Define image_paths_event dictionary
                        image_paths_failure_already_inside = {
                            "raw": raw_image_filename if 'raw_image_filename' in locals() else "",
                            "crop": crop_image_filename if 'crop_image_filename' in locals() and cropped_license_plate_img is not None and cropped_license_plate_img.size > 0 else ""
                        }
                        log_access("FAIL_IN", normalized_plate, rfid_id, "ALREADY_INSIDE_DIFF_RFID", image_paths_failure_already_inside, get_vietnam_time_str(), details="Plate already inside with different RFID") 
                        # Không cần `continue` ở đây vì đã có DB_ACCESS_LOCK, luồng sẽ đi xuống cuối và clear event
                    else:
                        print(f"✅ [Logic] Xác thực THÀNH CÔNG: Biển số '{normalized_plate}' hợp lệ để vào.")
                        current_time_str = get_vietnam_time_str()
                        timestamp_fn = get_vietnam_time_for_filename()
                        base_fn = f"in_{timestamp_fn}_{sanitize_filename_component(normalized_plate)}"
                        raw_image_filename = f"raw_{base_fn}.jpg"
                        crop_image_filename = f"crop_{base_fn}.jpg"
                        raw_path_viewer = os.path.join(PICTURE_OUTPUT_DIR, raw_image_filename)
                        
                        try:
                            cv2.imwrite(raw_path_viewer, original_frame_to_save)
                            print(f"🖼️  [FS] Đã lưu ảnh VÀO (gốc) cho viewer: {raw_path_viewer}")
                            if cropped_license_plate_img is not None and cropped_license_plate_img.size > 0:
                                crop_path_viewer = os.path.join(PICTURE_OUTPUT_DIR, crop_image_filename)
                                cv2.imwrite(crop_path_viewer, cropped_license_plate_img)
                                print(f"🖼️  [FS] Đã lưu ảnh VÀO (biển số) cho viewer: {crop_path_viewer}")
                        except Exception as e_img:
                            print(f"❌ [FS] Lỗi khi lưu ảnh VÀO cho viewer: {e_img}")
                            log_error(f"Lỗi khi lưu ảnh VÀO cho viewer (Plate: {normalized_plate})", category="FILESYSTEM", exception_obj=e_img) 
                            # raw_image_filename sẽ chỉ là tên file, không phải đường dẫn đầy đủ
                        
                        # Thực hiện INSERT trong CSDL
                        with sqlite3.connect(DB_FILE, timeout=10.0) as conn_insert:
                            cursor_insert = conn_insert.cursor()
                            cursor_insert.execute("INSERT INTO parking_log (plate, rfid_token, time_in, image_path_in, status, synced_to_server) VALUES (?, ?, ?, ?, ?, ?)",
                                                 (normalized_plate, str(rfid_id), current_time_str, raw_image_filename, STATUS_INSIDE, 0))
                            last_id = cursor_insert.lastrowid
                            conn_insert.commit() # Cam kết INSERT thành công
                            print(f"💾 [DB] Sự kiện VÀO đã được lưu cục bộ. ID: {last_id}")
                            # Define image_paths_event dictionary
                            image_paths_in_success = {
                                "raw": raw_image_filename,
                                "crop": crop_image_filename if cropped_license_plate_img is not None and cropped_license_plate_img.size > 0 else ""
                            }
                            log_access("IN", normalized_plate, rfid_id, "SUCCESS", image_paths_in_success, current_time_str, details=f"DB_ID: {last_id}") 
                            SYNC_WORK_AVAILABLE.set()


                # --- NHÁNH 1.2: XE ĐANG RA (Thẻ RFID này đã được ghi nhận là ở trong bãi) ---
                else:
                    print("⬅️  [Logic] Xử lý luồng RA...")
                    plate_in_db = vehicle_inside_record['plate']

                    if normalized_plate != plate_in_db:
                        print(f"🚨 [Logic] Cảnh báo An ninh: Biển số ra '{normalized_plate}' KHÔNG KHỚP biển số vào '{plate_in_db}'. Từ chối cho ra.")
                        log_error(f"Cảnh báo An ninh RA: Biển số ra '{normalized_plate}' (RFID: {rfid_id}) KHÔNG KHỚP biển vào '{plate_in_db}'.", category="LOGIC/SECURITY") 
                        # Define image_paths_event dictionary
                        image_paths_failure_mismatch = {
                            "raw": raw_image_filename_out if 'raw_image_filename_out' in locals() else "",
                            "crop": crop_image_filename_out if 'crop_image_filename_out' in locals() and cropped_license_plate_img is not None and cropped_license_plate_img.size > 0 else ""
                        }
                        log_access("FAIL_OUT", normalized_plate, rfid_id, "PLATE_MISMATCH", image_paths_failure_mismatch, get_vietnam_time_str(), details=f"Expected plate: {plate_in_db}") 
                    else:
                        print("✅ [Logic] Xác thực biển số thành công.")
                        current_time_str = get_vietnam_time_str()
                        timestamp_fn = get_vietnam_time_for_filename()
                        record_id_to_update = vehicle_inside_record['id']
                        base_fn = f"out_{timestamp_fn}_{sanitize_filename_component(normalized_plate)}"
                        raw_image_filename_out = f"raw_{base_fn}.jpg"
                        crop_image_filename_out = f"crop_{base_fn}.jpg"
                        raw_path_viewer_out = os.path.join(PICTURE_OUTPUT_DIR, raw_image_filename_out)

                        try:
                            cv2.imwrite(raw_path_viewer_out, original_frame_to_save)
                            print(f"🖼️  [FS] Đã lưu ảnh RA (gốc) cho viewer: {raw_path_viewer_out}")
                            if cropped_license_plate_img is not None and cropped_license_plate_img.size > 0:
                                crop_path_viewer_out = os.path.join(PICTURE_OUTPUT_DIR, crop_image_filename_out)
                                cv2.imwrite(crop_path_viewer_out, cropped_license_plate_img)
                                print(f"🖼️  [FS] Đã lưu ảnh RA (biển số) cho viewer: {crop_path_viewer_out}")
                        except Exception as e_img:
                            print(f"❌ [FS] Lỗi khi lưu ảnh RA cho viewer: {e_img}")
                            log_error(f"Lỗi khi lưu ảnh RA cho viewer (Plate: {normalized_plate})", category="FILESYSTEM", exception_obj=e_img) 

                        with sqlite3.connect(DB_FILE, timeout=10.0) as conn_update:
                            cursor_update = conn_update.cursor()
                            cursor_update.execute("UPDATE parking_log SET time_out = ?, image_path_out = ?, status = ?, synced_to_server = ? WHERE id = ?",
                                                 (current_time_str, raw_image_filename_out, STATUS_COMPLETED, 0, record_id_to_update))
                            conn_update.commit() # Cam kết UPDATE thành công
                            print(f"💾 [DB] Sự kiện RA đã được cập nhật cục bộ cho ID: {record_id_to_update}")
                            # Define image_paths_event dictionary
                            image_paths_out_success = {
                                "raw": raw_image_filename_out,
                                "crop": crop_image_filename_out if cropped_license_plate_img is not None and cropped_license_plate_img.size > 0 else ""
                            }
                            log_access("OUT", normalized_plate, rfid_id, "SUCCESS", image_paths_out_success, current_time_str, details=f"DB_ID: {record_id_to_update}") 
                            SYNC_WORK_AVAILABLE.set()
            
            except Exception as e_txn:
                print(f"🔥 [Main] Lỗi trong quá trình xử lý (bên trong DB_ACCESS_LOCK): {e_txn}")
                log_error(f"Lỗi trong quá trình xử lý cho RFID {rfid_id}, Plate {normalized_plate}", category="TRANSACTION", exception_obj=e_txn)
            
            finally: # Đảm bảo DB_ACCESS_LOCK luôn được giải phóng
                print("   [Main] Xử lý cục bộ hoàn tất (hoặc đã hủy). Nhả khóa DB_ACCESS_LOCK.")
                # Không cần giải phóng lock ở đây vì `with DB_ACCESS_LOCK:` đã tự làm

        # 3. Hạ cờ VEHICLE_EVENT sau khi đã nhả DB_ACCESS_LOCK
        print("   [Main] Hạ cờ VEHICLE_EVENT, cho phép đồng bộ hoạt động.")
        VEHICLE_EVENT.clear()
        
        time.sleep(1) # Giảm thời gian chờ giữa các lần quét thẻ chính

except KeyboardInterrupt:
    print("\n🛑 [Main] Phát hiện ngắt từ bàn phím. Đang tắt chương trình...")
    log_error("Chương trình bị ngắt bởi người dùng (KeyboardInterrupt).", category="SYSTEM")
except Exception as e_main_loop:
    print(f"🔥 [Main] Một lỗi nghiêm trọng, chưa được xử lý đã xảy ra trong vòng lặp chính: {e_main_loop}")
    log_error("Một lỗi nghiêm trọng, chưa được xử lý đã xảy ra trong vòng lặp chính.", category="FATAL", exception_obj=e_main_loop) 
finally:
    print("🧹 [Main] Dọn dẹp tài nguyên...")
    if 'cap' in locals() and cap.isOpened():
        cap.release()
        print("   [Main] Camera đã được giải phóng.")
    if 'GPIO' in locals() and 'cleanup' in dir(GPIO):
        try: GPIO.cleanup()
        except: pass
        print("   [Main] GPIO đã được dọn dẹp (nếu được sử dụng).")
    print("👋 [Main] Chương trình đã kết thúc.")