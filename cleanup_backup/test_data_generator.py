import sqlite3
import os
import uuid
from datetime import datetime, timedelta

# Import các hằng số trạng thái từ file constants.py
try:
    from constants import *
except ImportError:
    print("Lỗi: Không thể import constants.py. Hãy chắc chắn file này tồn tại và ở cùng thư mục.")
    # Định nghĩa các hằng số dự phòng nếu import lỗi
    STATUS_INSIDE = 1
    STATUS_COMPLETED = 2
    STATUS_INVALID = 99
    STATUS_FAIL_NO_PLATE = 10
    STATUS_FAIL_PLATE_INSIDE = 11
    STATUS_FAIL_PLATE_MISMATCH = 12

DB_FILE = os.getenv("DB_FILE", "parking_data.db")
PICTURE_DIR = os.getenv("PICTURE_OUTPUT_DIR", "picture")

# --- Helper Functions ---

def get_time_str(offset_minutes=0):
    """Lấy chuỗi thời gian (UTC+7) với độ lệch phút cho trước."""
    # Sử dụng múi giờ cố định để đảm bảo tính nhất quán khi chạy lại
    dt = datetime.utcnow() + timedelta(hours=7) + timedelta(minutes=offset_minutes)
    return dt.strftime('%Y-%m-%d %H:%M:%S')

def generate_rfid():
    """Tạo một ID thẻ RFID dạng số ngẫu nhiên."""
    return str(uuid.uuid4().int & (1<<64)-1)[:10]

def execute_query(conn, query, params=()):
    """Thực thi một câu lệnh SQL trên một kết nối đã có."""
    cursor = conn.cursor()
    cursor.execute(query, params)
    return cursor.lastrowid

def find_real_image():
    """Tìm một file ảnh thật trong thư mục picture để sử dụng cho test."""
    if not os.path.exists(PICTURE_DIR):
        return None
    for filename in os.listdir(PICTURE_DIR):
        if filename.lower().endswith(('.png', '.jpg', '.jpeg')):
            return filename
    return None

# --- Database Operations ---

def clear_database():
    """Xóa tất cả dữ liệu khỏi CSDL và reset ID."""
    try:
        with sqlite3.connect(DB_FILE) as conn:
            print(f"🧹 Đang xóa tất cả dữ liệu khỏi CSDL '{DB_FILE}'...")
            execute_query(conn, "DELETE FROM parking_log")
            execute_query(conn, "DELETE FROM sqlite_sequence WHERE name='parking_log'")
            conn.commit()
            print("✅ Đã xóa dữ liệu cũ thành công.")
    except sqlite3.Error as e:
        print(f"❌ Lỗi CSDL khi đang xóa dữ liệu: {e}")

def create_all_test_cases():
    """Tạo một bộ dữ liệu thử nghiệm toàn diện."""
    
    real_image_in = find_real_image()
    if real_image_in:
        print(f"🖼️  Tìm thấy ảnh thật để kiểm tra tải lên: '{real_image_in}'")
    else:
        print("⚠️  Không tìm thấy ảnh thật trong thư mục 'picture/'. Các kịch bản tải ảnh sẽ dùng ảnh giả lập.")
        real_image_in = "real_image_placeholder_in.jpg"

    real_image_out = "real_image_placeholder_out.jpg"

    # Định nghĩa tất cả các kịch bản
    scenarios = [
        {
            "description": "1. Giao dịch cũ không hợp lệ (hệ thống phải bỏ qua, đã đồng bộ)",
            "records": [
                {"plate": "OLD-INVALID", "rfid": "TOKEN-INVALID", "time_in": get_time_str(offset_minutes=-(3*1440)), "img_in": "placeholder_fail.jpg", "status": STATUS_INVALID, "synced": 1},
            ]
        },
        {
            "description": "2. Giao dịch cũ đã được đồng bộ (hệ thống phải bỏ qua)",
            "records": [
                {"plate": "OLD-SYNCED", "rfid": "TOKEN-SYNCED", "time_in": get_time_str(offset_minutes=-(2*1440)), "time_out": get_time_str(offset_minutes=-(2*1440) + 60), "img_in": "placeholder_in.jpg", "img_out": "placeholder_out.jpg", "status": STATUS_COMPLETED, "synced": 1},
            ]
        },
        {
            "description": "3. Xe vào-ra thành công cách đây 1 ngày (chưa đồng bộ)",
            "records": [
                {"plate": "HN-SUCCESS", "rfid": "TOKEN-SUCCESS", "time_in": get_time_str(offset_minutes=-(1*1440)), "time_out": get_time_str(offset_minutes=-(1*1440) + 30), "img_in": "placeholder_in.jpg", "img_out": "placeholder_out.jpg", "status": STATUS_COMPLETED, "synced": 0},
            ]
        },
        {
            "description": "4. Xe hiện đang ở trong bãi, vào từ 5 giờ trước (chưa đồng bộ)",
            "records": [
                {"plate": "SG-INSIDE", "rfid": "TOKEN-INSIDE", "time_in": get_time_str(offset_minutes=-300), "img_in": "placeholder_in.jpg", "status": STATUS_INSIDE, "synced": 0},
            ]
        },
        {
            "description": "5. Lỗi: Không nhận dạng được biển số khi vào, 4 giờ trước (chưa đồng bộ)",
            "records": [
                {"plate": "UNKNOWN", "rfid": "TOKEN-NO-PLATE", "time_in": get_time_str(offset_minutes=-240), "img_in": "placeholder_fail.jpg", "status": STATUS_FAIL_NO_PLATE, "synced": 0},
            ]
        },
        {
            "description": "6. Lỗi: Xe vào có biển số đã tồn tại trong bãi, 3 giờ trước (chưa đồng bộ)",
            "records": [
                # Sử dụng lại biển số 'SG-INSIDE' từ kịch bản 4
                {"plate": "SG-INSIDE", "rfid": "TOKEN-DUPLICATE", "time_in": get_time_str(offset_minutes=-180), "img_in": "placeholder_fail.jpg", "status": STATUS_FAIL_PLATE_INSIDE, "synced": 0},
            ]
        },
        {
            "description": "7. Lỗi: Xe ra không khớp biển số, 2 giờ trước (chưa đồng bộ)",
            "records": [
                # Đầu tiên là một xe vào bình thường
                {"plate": "DN-FOR-MISMATCH", "rfid": "TOKEN-MISMATCH", "time_in": get_time_str(offset_minutes=-150), "img_in": "placeholder_in.jpg", "status": STATUS_INSIDE, "synced": 0},
                # Sau đó là một sự kiện ra thất bại với cùng token nhưng khác biển số
                {"plate": "DN-WRONG-PLATE", "rfid": "TOKEN-MISMATCH", "time_in": get_time_str(offset_minutes=-120), "img_in": "placeholder_mismatch.jpg", "status": STATUS_FAIL_PLATE_MISMATCH, "synced": 0},
            ]
        },
        {
            "description": "8. Xe vào thành công với ẢNH THẬT, 1 giờ trước (chưa đồng bộ)",
            "records": [
                {"plate": "REAL-IMG-IN", "rfid": "TOKEN-REAL-IMG", "time_in": get_time_str(offset_minutes=-60), "img_in": real_image_in, "status": STATUS_INSIDE, "synced": 0},
            ]
        },
        {
            "description": "9. Xe ra thành công với ẢNH THẬT, 30 phút trước (hoàn thành kịch bản 8)",
            "update": {
                "rfid": "TOKEN-REAL-IMG",
                "updates": {"time_out": get_time_str(offset_minutes=-30), "img_out": real_image_out, "status": STATUS_COMPLETED, "synced": 0}
            }
        },
        {
            "description": "10. Sự kiện với đường dẫn ảnh không tồn tại, 10 phút trước (chưa đồng bộ)",
            "records": [
                {"plate": "IMG-NOT-FOUND", "rfid": "TOKEN-IMG-FAIL", "time_in": get_time_str(offset_minutes=-10), "img_in": "non_existent_image.jpg", "status": STATUS_INSIDE, "synced": 0},
            ]
        }
    ]

    try:
        with sqlite3.connect(DB_FILE) as conn:
            print("\n🌱 Bắt đầu tạo dữ liệu thử nghiệm...")
            for scenario in scenarios:
                print(f"   -> {scenario['description']}")
                
                # Xử lý các bản ghi cần chèn mới
                if "records" in scenario:
                    for record in scenario["records"]:
                        execute_query(conn, """
                            INSERT INTO parking_log (plate, rfid_token, time_in, time_out, image_path_in, image_path_out, status, synced_to_server)
                            VALUES (?, ?, ?, ?, ?, ?, ?, ?)
                        """, (
                            record['plate'], record['rfid'], record['time_in'], record.get('time_out'),
                            record.get('img_in'), record.get('img_out'), record['status'], record['synced']
                        ))

                # Xử lý các bản ghi cần cập nhật
                if "update" in scenario:
                    update_info = scenario["update"]
                    # Sửa lỗi: Tìm bản ghi để cập nhật chỉ bằng RFID token,
                    # vì status của nó có thể không phải là STATUS_INSIDE nếu các kịch bản chạy không theo thứ tự
                    # hoặc nếu có các sự kiện lỗi liên quan.
                    execute_query(conn, """
                        UPDATE parking_log SET time_out = ?, image_path_out = ?, status = ?, synced_to_server = ?
                        WHERE rfid_token = ? AND time_out IS NULL
                    """, (
                        update_info['updates']['time_out'], update_info['updates']['img_out'],
                        update_info['updates']['status'], update_info['updates']['synced'],
                        update_info['rfid']
                    ))

            conn.commit()
            print("\n✅ Đã tạo dữ liệu thử nghiệm toàn diện thành công!")
            print("Bây giờ bạn có thể chạy LPR.py để xem quá trình đồng bộ.")

    except sqlite3.Error as e:
        print(f"❌ Lỗi CSDL khi đang tạo dữ liệu: {e}")

# --- Main Execution ---

def main():
    """Hiển thị menu cho người dùng."""
    print("--- BỘ TẠO DỮ LIỆU THỬ NGHIỆM TOÀN DIỆN CHO HỆ THỐNG LPR ---")
    
    if not os.path.exists(DB_FILE):
        print(f"Cảnh báo: File CSDL '{DB_FILE}' không tồn tại.")
        print("Vui lòng chạy ứng dụng LPR.py ít nhất một lần để tạo file CSDL trước khi chạy kịch bản này.")
        return

    while True:
        print("\nLựa chọn của bạn:")
        print("  1. Xóa CSDL và tạo bộ dữ liệu thử nghiệm mới (Khuyến nghị)")
        print("  2. Chỉ xóa toàn bộ dữ liệu trong CSDL")
        print("  3. Thoát")
        choice = input("Nhập lựa chọn: ").strip()

        if choice == '1':
            clear_database()
            create_all_test_cases()
            break
        elif choice == '2':
            clear_database()
            break
        elif choice == '3':
            print("Đã hủy. Không có thay đổi nào được thực hiện.")
            break
        else:
            print("Lựa chọn không hợp lệ. Vui lòng thử lại.")

if __name__ == "__main__":
    main()
