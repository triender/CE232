import cv2
import torch
import os
import time
from datetime import datetime, timezone, timedelta
import RPi.GPIO as GPIO
from mfrc522 import SimpleMFRC522
import requests
import sqlite3
import function.utils_rotate as utils_rotate
import function.helper as helper
import threading

API_ENDPOINT = "http://192.168.137.206:3000/parking/add"

DB_FILE = "parking_data.db"

def init_db():
    """Khởi tạo cơ sở dữ liệu và bảng nếu chưa tồn tại"""
    conn = sqlite3.connect(DB_FILE)
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
    conn.close()
    print(f"✅ Đã khởi tạo hoặc kết nối tới CSDL: {DB_FILE}")

def sync_data_to_server():
    """Hàm chạy nền để đồng bộ dữ liệu"""
    while True:
        print("🔄 [Sync Thread] Bắt đầu kiểm tra dữ liệu cần đồng bộ...")
        conn = None
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
                    # Cập nhật thứ tự giải nén tuple cho phù hợp
                    record_id, plate, token, timestamp, image_path, _ = record # Bỏ in_out
                    
                    print(f"  -> Đang thử đồng bộ bản ghi ID: {record_id}, Biển số: {plate}")
                    
                    # Chuẩn bị payload (không có in_or_out)
                    payload = {
                        'plate': plate,
                        'token': token,
                        'time': timestamp
                    }
                    
                    if not os.path.exists(image_path):
                        print(f"  Lỗi: Không tìm thấy file ảnh {image_path}. Đánh dấu là đã đồng bộ để bỏ qua.")
                        cursor.execute("UPDATE transactions SET synced = 1 WHERE id = ?", (record_id,))
                        conn.commit()
                        continue

                    with open(image_path, 'rb') as img_file:
                        files_payload = {
                            'image': (os.path.basename(image_path), img_file, 'image/jpeg')
                        }
                        
                        try:
                            response = requests.post(API_ENDPOINT, data=payload, files=files_payload, timeout=15)
                            
                            if response.status_code == 200:
                                print(f"  ✅ Đồng bộ thành công ID: {record_id}")
                                cursor.execute("UPDATE transactions SET synced = 1 WHERE id = ?", (record_id,))
                                conn.commit()
                                # (Tùy chọn) Xóa file ảnh đã đồng bộ
                                # try:
                                #    os.remove(image_path)
                                #    print(f"    Đã xóa file ảnh: {image_path}")
                                # except OSError as e_remove:
                                #    print(f"    Lỗi khi xóa file ảnh {image_path}: {e_remove}")
                            else:
                                print(f"  ❌ Lỗi server khi đồng bộ ID: {record_id}. Mã: {response.status_code}. Sẽ thử lại sau.")
                        
                        except requests.exceptions.RequestException as e_req:
                            print(f"  ❌ Mất kết nối mạng hoặc lỗi yêu cầu. Không thể đồng bộ ID: {record_id}. Lỗi: {e_req}. Sẽ thử lại sau.")
                            break 
        
        except Exception as e_sync:
            print(f"🚨 [Sync Thread] Gặp lỗi nghiêm trọng: {e_sync}")
        
        finally:
            if conn:
                conn.close()

        time.sleep(30)

def save_record_to_local_db(plate, token_id, image_frame_to_save, reason=""):
    """Lưu bản ghi vào CSDL cục bộ khi gửi trực tiếp thất bại."""
    print(f"💽 Đang lưu vào CSDL cục bộ. Lý do: {reason}")
    
    # 1. Lưu file ảnh vào một thư mục cục bộ
    safe_lp_for_filename = "".join(c if c.isalnum() else "_" for c in plate).rstrip("_")
    timestamp_filename_str = datetime.now().strftime("%Y%m%d_%H%M%S_%f")
    image_filename = f"{timestamp_filename_str}_{safe_lp_for_filename}.jpg"
    image_path_tosave = os.path.join(IMAGE_DIR, image_filename) # IMAGE_DIR được định nghĩa toàn cục
    
    try:
        cv2.imwrite(image_path_tosave, image_frame_to_save)
        print(f"📸 Đã lưu ảnh cục bộ tại: {image_path_tosave}")
    except Exception as e_imwrite:
        print(f"❌ Lỗi khi lưu ảnh cục bộ: {e_imwrite}")
        return # Không lưu vào DB nếu không lưu được ảnh

    # 2. Chuẩn bị dữ liệu để lưu vào CSDL
    vietnam_tz = timezone(timedelta(hours=7)) # Đảm bảo timezone, timedelta đã import
    current_time = datetime.now(vietnam_tz)
    formatted_time_str = current_time.strftime("%Y-%m-%d %H:%M:%S")

    # 3. Chèn dữ liệu vào CSDL SQLite
    try:
        conn = sqlite3.connect(DB_FILE) # DB_FILE được định nghĩa toàn cục
        cursor = conn.cursor()
        cursor.execute('''
            INSERT INTO transactions (plate, token, timestamp, image_path, synced)
            VALUES (?, ?, ?, ?, ?)
        ''', (plate, str(token_id), formatted_time_str, image_path_tosave, 0))
        conn.commit()
        conn.close()
        print("💾 Dữ liệu đã được lưu vào hàng đợi cục bộ.")
    except Exception as e_db:
        print(f"❌ Lỗi khi lưu vào CSDL cục bộ: {e_db}")

def sanitize_filename(name):
    return "".join(c if c.isalnum() else "_" for c in name).rstrip("_")

def get_timestamp_str():
    now = datetime.now()
    return now.strftime("%d_%m_%Y_%Hh%M")

# --- KHỞI TẠO CÁC THÀNH PHẦN ---
print("🚀 Bắt đầu khởi tạo hệ thống...")
output_dir = "picture"
os.makedirs(output_dir, exist_ok=True)
print(f"✅ Thư mục lưu ảnh: '{output_dir}'")

init_db()

sync_thread = threading.Thread(target=sync_data_to_server, daemon=True)
sync_thread.start()
print("🚀 Đã khởi động tiến trình đồng bộ nền.")

try:
    yolov5_repo = '/home/minhtest/yolov5'
    yolo_LP_detect = torch.hub.load(yolov5_repo, 'custom', path='model/LP_detector_nano_61.pt', source='local')
    yolo_license_plate = torch.hub.load(yolov5_repo, 'custom', path='model/LP_ocr_nano_62.pt', source='local')
    yolo_license_plate.conf = 0.60
    print("✅ Tải model YOLO thành công!")
except Exception as e:
    print(f"❌ Lỗi khi tải model YOLO: {e}")
    exit()
cap = cv2.VideoCapture(0)
if not cap.isOpened():
    print("❌ Lỗi: Không thể mở webcam.")
    exit()
else:
    print("✅ Mở webcam thành công!")
reader = SimpleMFRC522()
print("✅ Khởi tạo đầu đọc RFID thành công!")

# --- VÒNG LẶP CHÍNH ---
try:
    while True:
        print("\n-----------------------------------------")
        print("💡 Vui lòng đưa thẻ vào đầu đọc...")

        id, text = reader.read()
        print(f"✅ Đã nhận thẻ! ID: {id}, Text: {text}")
        print("📸 Bắt đầu chụp ảnh và nhận dạng biển số...")

        for _ in range(5):
            cap.read()

        ret, frame = cap.read()
        if not ret:
            print("❌ Không thể lấy khung hình từ camera.")
            continue

        # (Logic nhận dạng biển số giữ nguyên...)
        process_frame = frame.copy()
        results = yolo_LP_detect(process_frame, size=640)
        list_plates = results.pandas().xyxy[0].values.tolist()

        found_plate_text = None
        if not list_plates:
            lp = helper.read_plate(yolo_license_plate, process_frame)
            if lp != "unknown" and lp != "":
                found_plate_text = lp
        else:
            for i, plate in enumerate(list_plates):
                x1, y1, x2, y2 = map(int, plate[:4])
                crop_img = process_frame[y1:y2, x1:x2]
                lp_text = "unknown"
                for cc in range(2):
                    for ct in range(2):
                        rotated_img = utils_rotate.deskew(crop_img, cc, ct)
                        lp = helper.read_plate(yolo_license_plate, rotated_img)
                        if lp != "unknown" and lp != "":
                            lp_text = lp
                            break
                    if lp_text != "unknown":
                        break
                if lp_text != "unknown":
                    found_plate_text = lp_text
                    break

        if found_plate_text:
            print(f"🎉 Phát hiện thành công biển số: {found_plate_text}")

            # --- LƯU DỮ LIỆU CỤC BỘ ---
            
            # 1. Lưu file ảnh vào một thư mục cục bộ
            # Sử dụng found_plate_text đã được sanitize (nếu cần)
            safe_lp_for_filename = "".join(c if c.isalnum() else "_" for c in found_plate_text).rstrip("_")
            timestamp_filename = datetime.now().strftime("%Y%m%d_%H%M%S")
            image_filename = f"{timestamp_filename}_{safe_lp_for_filename}.jpg"
            image_dir = "offline_images" # Thư mục lưu ảnh
            os.makedirs(image_dir, exist_ok=True) # Đảm bảo thư mục tồn tại
            image_path = os.path.join(image_dir, image_filename)
            
            cv2.imwrite(image_path, frame) # Lưu ảnh gốc
            print(f"📸 Đã lưu ảnh cục bộ tại: {image_path}")

            # 2. Chuẩn bị dữ liệu để lưu vào CSDL
            vietnam_tz = timezone(timedelta(hours=7))
            current_time = datetime.now(vietnam_tz)
            formatted_time_str = current_time.strftime("%Y-%m-%d %H:%M:%S")

            # 3. Chèn dữ liệu vào CSDL SQLite (không có in_or_out)
            try:
                conn = sqlite3.connect(DB_FILE)
                cursor = conn.cursor()
                cursor.execute('''
                    INSERT INTO transactions (plate, token, timestamp, image_path, synced)
                    VALUES (?, ?, ?, ?, ?)
                ''', (found_plate_text, str(id), formatted_time_str, image_path, 0)) # Loại bỏ giá trị '1'
                conn.commit()
                conn.close()
                print("💾 Dữ liệu đã được lưu vào hàng đợi cục bộ.")
            except Exception as e:
                print(f"❌ Lỗi khi lưu vào CSDL cục bộ: {e}")

        else:
            print("😔 Không nhận dạng được biển số nào.")

except KeyboardInterrupt:
    print("\n🛑 Chương trình đã dừng bởi người dùng.")

finally:
    print("🧹 Dọn dẹp tài nguyên...")
    cap.release()
    GPIO.cleanup()
    print("👋 Kết thúc chương trình!")
