import cv2
import torch
import os
import time
from datetime import datetime, timezone, timedelta
import RPi.GPIO as GPIO
from mfrc522 import SimpleMFRC522
import requests
import sqlite3
import threading # Make sure threading is imported
from dotenv import load_dotenv

# --- TẢI BIẾN MÔI TRƯỜNG TỪ FILE .ENV ---
load_dotenv()

# --- LẤY CÁC BIẾN CẤU HÌNH TỪ MÔI TRƯỜNG ---
API_ENDPOINT = os.getenv("API_ENDPOINT", "http://localhost:3000/parking/add")
DB_FILE = os.getenv("DB_FILE", "parking_data.db")
IMAGE_DIR = os.getenv("IMAGE_DIR", "offline_images")
YOLOV5_REPO_PATH = os.getenv("YOLOV5_REPO_PATH")
LP_DETECTOR_MODEL_PATH = os.getenv("LP_DETECTOR_MODEL_PATH")
LP_OCR_MODEL_PATH = os.getenv("LP_OCR_MODEL_PATH")

# Kiểm tra các biến quan trọng
if not all([API_ENDPOINT, DB_FILE, IMAGE_DIR, YOLOV5_REPO_PATH, LP_DETECTOR_MODEL_PATH, LP_OCR_MODEL_PATH]):
    print("❌ Lỗi: Một hoặc nhiều biến môi trường quan trọng chưa được thiết lập trong file .env.")
    print("Vui lòng kiểm tra các biến: API_ENDPOINT, DB_FILE, IMAGE_DIR, YOLOV5_REPO_PATH, LP_DETECTOR_MODEL_PATH, LP_OCR_MODEL_PATH")
    exit()

# --- MODULES CỦA BẠN (Đảm bảo chúng tồn tại và đúng đường dẫn) ---
# Giả sử chúng được đặt trong thư mục 'function' cùng cấp với file script này
try:
    import function.utils_rotate as utils_rotate
    import function.helper as helper
    print("✅ Tải module utils_rotate và helper thành công.")
except ImportError:
    print("❌ Lỗi: Không thể tải module utils_rotate hoặc helper. Vui lòng kiểm tra đường dẫn và sự tồn tại của file.")
    # Định nghĩa hàm mock nếu không có module để code vẫn chạy được phần nào
    class MockHelper:
        @staticmethod
        def read_plate(model, image):
            print("⚠️ Sử dụng MockHelper.read_plate")
            if time.time() % 10 > 3: return f"MOCK{int(time.time())%1000:03d}LP"
            return "unknown"
    class MockUtilsRotate:
        @staticmethod
        def deskew(image, cc, ct):
            print("⚠️ Sử dụng MockUtilsRotate.deskew")
            return image
    helper = MockHelper()
    utils_rotate = MockUtilsRotate()


# --- CÁC HÀM TIỆN ÍCH ---
def get_vietnam_time_str():
    """Lấy thời gian hiện tại ở Việt Nam, định dạng YYYY-MM-DD HH:MM:SS"""
    vietnam_tz = timezone(timedelta(hours=7))
    return datetime.now(vietnam_tz).strftime("%Y-%m-%d %H:%M:%S")

def sanitize_filename_component(name_part):
    """Làm sạch một phần của tên file."""
    return "".join(c if c.isalnum() else "_" for c in str(name_part)).rstrip("_")

# --- CÁC HÀM LIÊN QUAN ĐẾN DATABASE VÀ SERVER ---
def init_db():
    """Khởi tạo cơ sở dữ liệu và bảng nếu chưa tồn tại."""
    with sqlite3.connect(DB_FILE) as conn:
        cursor = conn.cursor()
        cursor.execute('''
            CREATE TABLE IF NOT EXISTS transactions (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                plate TEXT NOT NULL,
                token TEXT NOT NULL,
                timestamp TEXT NOT NULL,
                image_path TEXT NOT NULL,
                synced INTEGER NOT NULL DEFAULT 0
            )
        ''')
        conn.commit()
    print(f"✅ Đã khởi tạo hoặc kết nối tới CSDL: {DB_FILE}")
    os.makedirs(IMAGE_DIR, exist_ok=True)

def send_data_to_server(plate_text, token_id, timestamp_str, image_data_bytes) -> bool:
    """
    Gửi dữ liệu (bao gồm ảnh) lên server.
    Trả về True nếu thành công, False nếu thất bại.
    """
    print(f"📡 Đang thử gửi dữ liệu tới server: {API_ENDPOINT} cho biển số {plate_text}")
    payload = {
        'plate': plate_text,
        'token': str(token_id),
        'time': timestamp_str
    }
    files_payload = {
        'image': ('image.jpg', image_data_bytes, 'image/jpeg')
    }
    try:
        response = requests.post(API_ENDPOINT, data=payload, files=files_payload, timeout=5) # Ngắn hơn cho gửi trực tiếp
        if response.status_code == 200:
            print("✅ Gửi dữ liệu lên server thành công!")
            try:
                print("   => Phản hồi từ server:", response.json())
            except requests.exceptions.JSONDecodeError:
                print("   => Phản hồi từ server (không phải JSON):", response.text)
            return True
        else:
            print(f"❌ Server trả về lỗi! Mã: {response.status_code} - {response.text}")
            return False
    except requests.exceptions.Timeout:
        print("❌ Timeout khi gửi dữ liệu.")
        return False
    except requests.exceptions.ConnectionError:
        print("❌ Lỗi kết nối mạng khi gửi dữ liệu.")
        return False
    except requests.exceptions.RequestException as e_req:
        print(f"❌ Lỗi Request không xác định khi gửi dữ liệu: {e_req}")
        return False
    except Exception as e_send: # Bắt các lỗi khác có thể xảy ra
        print(f"❌ Lỗi không xác định trong quá trình gửi dữ liệu: {e_send}")
        return False

def save_record_to_local_db(plate, token_id, image_frame_to_save, timestamp_to_save, reason=""):
    """Lưu bản ghi vào CSDL cục bộ khi gửi trực tiếp thất bại."""
    print(f"💽 Đang lưu vào CSDL cục bộ. Lý do: {reason}")
    plate_fn_safe = sanitize_filename_component(plate)
    time_fn_safe = sanitize_filename_component(datetime.now().strftime("%Y%m%d_%H%M%S_%f"))
    image_filename = f"{time_fn_safe}_{plate_fn_safe}.jpg"
    image_path_tosave = os.path.join(IMAGE_DIR, image_filename)
    try:
        cv2.imwrite(image_path_tosave, image_frame_to_save)
        print(f"📸 Đã lưu ảnh cục bộ tại: {image_path_tosave}")
    except Exception as e_imwrite:
        print(f"❌ Lỗi khi lưu ảnh cục bộ: {e_imwrite}")
        return
    try:
        with sqlite3.connect(DB_FILE) as conn:
            cursor = conn.cursor()
            cursor.execute('''
                INSERT INTO transactions (plate, token, timestamp, image_path, synced)
                VALUES (?, ?, ?, ?, ?)
            ''', (plate, str(token_id), timestamp_to_save, image_path_tosave, 0))
            conn.commit()
        print("💾 Dữ liệu đã được lưu vào hàng đợi cục bộ.")
    except sqlite3.Error as e_db:
        print(f"❌ Lỗi SQLite khi lưu vào CSDL cục bộ: {e_db}")
    except Exception as e_save:
        print(f"❌ Lỗi không xác định khi lưu vào CSDL cục bộ: {e_save}")


def sync_offline_data_to_server():
    """Hàm chạy nền để đồng bộ dữ liệu đã lưu cục bộ."""
    while True:
        print("\n🔄 [Sync Thread] Bắt đầu kiểm tra dữ liệu cần đồng bộ...")
        conn = None
        records_processed_in_batch = 0
        try:
            conn = sqlite3.connect(DB_FILE)
            cursor = conn.cursor()
            cursor.execute("SELECT * FROM transactions WHERE synced = 0 LIMIT 5")
            records_to_sync = cursor.fetchall()

            if not records_to_sync:
                print("👍 [Sync Thread] Không có dữ liệu mới. Hàng đợi sạch.")
            else:
                print(f"⏳ [Sync Thread] Tìm thấy {len(records_to_sync)} bản ghi cần đồng bộ.")
                for record in records_to_sync:
                    records_processed_in_batch += 1
                    record_id, plate, token, timestamp, image_path, _ = record
                    print(f"  -> Đang thử đồng bộ bản ghi ID: {record_id}, Biển số: {plate}")
                    
                    if not os.path.exists(image_path):
                        print(f"  Lỗi: Không tìm thấy file ảnh {image_path} cho ID {record_id}. Đánh dấu là đã đồng bộ để bỏ qua.")
                        cursor.execute("UPDATE transactions SET synced = 1 WHERE id = ?", (record_id,))
                        conn.commit()
                        continue

                    try:
                        with open(image_path, 'rb') as img_file:
                            image_bytes = img_file.read()
                        
                        if send_data_to_server(plate, token, timestamp, image_bytes):
                            print(f"  ✅ Đồng bộ thành công ID: {record_id} từ hàng đợi.")
                            cursor.execute("UPDATE transactions SET synced = 1 WHERE id = ?", (record_id,))
                            conn.commit()
                            # Tùy chọn xóa ảnh sau khi đồng bộ thành công từ hàng đợi
                            # try:
                            #     os.remove(image_path)
                            #     print(f"    Đã xóa file ảnh offline: {image_path}")
                            # except OSError as e_remove:
                            #     print(f"    Lỗi khi xóa file ảnh offline {image_path}: {e_remove}")
                        else:
                            print(f"  ❌ Gửi dữ liệu từ hàng đợi thất bại cho ID: {record_id}. Sẽ thử lại sau.")
                            # Nếu send_data_to_server trả về False do lỗi mạng/server,
                            # nó sẽ được thử lại trong lần lặp tiếp theo của sync thread.
                            # Nếu lỗi là do dữ liệu (vd: ảnh hỏng mà send_data_to_server không bắt được),
                            # cần cơ chế khác để đánh dấu là "không thể gửi".
                    except IOError as e_io:
                        print(f"  Lỗi IO khi đọc file ảnh {image_path} cho ID {record_id}: {e_io}. Đánh dấu lỗi.")
                        # Cân nhắc đánh dấu bản ghi này là có lỗi vĩnh viễn nếu không đọc được ảnh
                        # cursor.execute("UPDATE transactions SET synced = 2 WHERE id = ?", (record_id,)) # synced = 2 là lỗi
                        # conn.commit()
                    except Exception as e_inner_sync:
                         print(f"  Lỗi không xác định trong quá trình xử lý bản ghi ID {record_id}: {e_inner_sync}")

        except sqlite3.Error as e_sql:
            print(f"🚨 [Sync Thread] Lỗi SQLite: {e_sql}")
        except Exception as e_sync_outer:
            print(f"🚨 [Sync Thread] Gặp lỗi không xác định bên ngoài vòng lặp bản ghi: {e_sync_outer}")
        finally:
            if conn:
                conn.close()
        
        sleep_duration = 10 if records_processed_in_batch > 0 else 30 # Chờ ít hơn nếu có hoạt động
        print(f"🔄 [Sync Thread] Kết thúc lượt kiểm tra. Chờ {sleep_duration} giây.")
        time.sleep(sleep_duration)

# --- KHỞI TẠO HỆ THỐNG ---
print("🚀 Bắt đầu khởi tạo hệ thống...")
init_db()
try:
    yolo_LP_detect = torch.hub.load(YOLOV5_REPO_PATH, 'custom', path=LP_DETECTOR_MODEL_PATH, source='local', _verbose=False)
    yolo_license_plate = torch.hub.load(YOLOV5_REPO_PATH, 'custom', path=LP_OCR_MODEL_PATH, source='local', _verbose=False)
    yolo_license_plate.conf = 0.60
    
    cap = cv2.VideoCapture(0)
    if not cap.isOpened():
        raise IOError("Không thể mở webcam")
    reader = SimpleMFRC522()
    print("✅ Khởi tạo model, camera và RFID thành công!")
except Exception as e:
    print(f"❌ Lỗi khởi tạo hệ thống: {e}")
    exit()

sync_thread = threading.Thread(target=sync_offline_data_to_server, daemon=True) # Đổi tên hàm target
sync_thread.start()
print("🚀 Đã khởi động tiến trình đồng bộ nền.")

# --- VÒNG LẶP CHÍNH ---
try:
    while True:
        print("\n-----------------------------------------")
        print("💡 Vui lòng đưa thẻ vào đầu đọc...")
        rfid_id, rfid_text = (None, None)
        try:
            # Cân nhắc dùng reader.read_id_no_block() nếu thư viện hỗ trợ và phù hợp với luồng
            rfid_id, rfid_text = reader.read() 
            print(f"✅ Đã nhận thẻ! ID: {rfid_id}, Text: {rfid_text}")
        except Exception as e_rfid:
            print(f"Lỗi đọc thẻ RFID: {e_rfid}. Đang thử lại...")
            time.sleep(0.5) 
            continue

        print("📸 Bắt đầu chụp ảnh và nhận dạng biển số...")
        for _ in range(5): cap.read() # Xả buffer
        ret, frame = cap.read()
        if not ret or frame is None:
            print("❌ Không thể lấy khung hình từ camera.")
            continue
        
        process_frame = frame.copy()
        plate_detection_results = yolo_LP_detect(process_frame, size=640)
        detected_plates_coords = plate_detection_results.pandas().xyxy[0].values.tolist()
        
        found_license_plate_text = None
        
        if not detected_plates_coords:
            # Thử đọc trên toàn khung hình nếu không có bounding box
            lp_candidate = helper.read_plate(yolo_license_plate, process_frame)
            if lp_candidate != "unknown" and lp_candidate != "":
                found_license_plate_text = lp_candidate
        else:
            for plate_coords in detected_plates_coords:
                x1, y1, x2, y2 = map(int, plate_coords[:4])
                cropped_plate_img = process_frame[y1:y2, x1:x2]
                
                if cropped_plate_img.size == 0: continue # Bỏ qua nếu crop rỗng

                lp_text_from_crop = "unknown"
                # Cân nhắc giảm vòng lặp deskew nếu không cần thiết hoặc tốn thời gian
                for cc_angle_index in range(1): # Giảm thử nghiệm xoay để nhanh hơn
                    for ct_tilt_index in range(1):
                        # deskewed_img = utils_rotate.deskew(cropped_plate_img, cc_angle_index, ct_tilt_index)
                        deskewed_img = cropped_plate_img # Bỏ qua deskew nếu dùng mock
                        
                        lp_candidate = helper.read_plate(yolo_license_plate, deskewed_img)
                        if lp_candidate != "unknown" and lp_candidate != "":
                            lp_text_from_crop = lp_candidate
                            break 
                    if lp_text_from_crop != "unknown":
                        break 
                
                if lp_text_from_crop != "unknown":
                    found_license_plate_text = lp_text_from_crop
                    break # Dừng lại khi tìm thấy biển số đầu tiên

        if found_license_plate_text:
            print(f"🎉 Phát hiện thành công biển số: {found_license_plate_text}")
            
            current_timestamp_str = get_vietnam_time_str()
            
            # Encode ảnh thành bytes để gửi
            is_encode_success, image_buffer_array = cv2.imencode(".jpg", frame)
            if not is_encode_success:
                print("❌ Lỗi khi encode ảnh!")
                # Nếu lỗi encode, chỉ lưu text vào DB, không có ảnh
                save_record_to_local_db(found_license_plate_text, rfid_id, frame, current_timestamp_str, "Lỗi encode ảnh khi gửi trực tiếp")
            else:
                image_bytes_to_send = image_buffer_array.tobytes()
                
                # Ưu tiên gửi trực tiếp lên server
                if send_data_to_server(found_license_plate_text, rfid_id, current_timestamp_str, image_bytes_to_send):
                    print("✨ Hoàn tất xử lý (gửi trực tiếp thành công).")
                else:
                    # Nếu gửi trực tiếp thất bại, lưu vào CSDL cục bộ
                    save_record_to_local_db(found_license_plate_text, rfid_id, frame, current_timestamp_str, "Gửi trực tiếp thất bại")
        else:
            print("😔 Không nhận dạng được biển số nào.")
        
        time.sleep(0.1) # Chờ một chút giữa các lần quét

except KeyboardInterrupt:
    print("\n🛑 Chương trình đã dừng bởi người dùng.")
except Exception as e_main_loop:
    print(f"🚨 Lỗi nghiêm trọng trong vòng lặp chính: {e_main_loop}")
finally:
    print("🧹 Dọn dẹp tài nguyên...")
    if 'cap' in locals() and cap.isOpened():
        cap.release()
    if 'GPIO' in locals() : # Chỉ cleanup nếu GPIO đã được sử dụng
        GPIO.cleanup()
    print("👋 Kết thúc chương trình!")