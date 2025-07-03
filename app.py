import threading
from flask import Flask, render_template, send_from_directory, jsonify, request, redirect, url_for
import os
import time
from datetime import datetime, timezone, timedelta, date
import json
import sqlite3
from filelock import FileLock, Timeout
from constants import STATUS_INSIDE, STATUS_COMPLETED, STATUS_INVALID
from utils import get_vietnam_time_str

# Constants
PICTURE_FOLDER = os.getenv("PICTURE_OUTPUT_DIR", "picture")
TMP_FOLDER = os.path.join(os.path.dirname(os.path.abspath(__file__)), "tmp")
DB_FILE = os.getenv("DB_FILE", "parking_data.db")
DB_LOCK_FILE = DB_FILE + ".lock"

app = Flask(__name__)


def get_db_connection():
    """Helper function to get a DB connection with row_factory."""
    conn = sqlite3.connect(DB_FILE, timeout=5.0)
    conn.row_factory = sqlite3.Row
    return conn

@app.route('/log')
def index():
    """
    Trang lịch sử, giờ đây truy vấn trực tiếp từ CSDL với phân trang và tìm kiếm.
    """
    page = request.args.get('page', 1, type=int)
    per_page = 5 # Giữ lại số sự kiện mỗi trang là 5
    search_query = request.args.get('search', '').strip()
    
    events = []
    total_events = 0
    total_pages = 0
    error_message = None

    try:
        # Sử dụng lock cục bộ trong khối with để đảm bảo an toàn
        with FileLock(DB_LOCK_FILE, timeout=5.0):
            with get_db_connection() as conn:
                cursor = conn.cursor()

                # Xây dựng câu lệnh query
                base_query = "FROM parking_log"
                count_query = "SELECT COUNT(id) " + base_query
                select_query = "SELECT * " + base_query
                
                params = []
                if search_query:
                    where_clause = " WHERE plate LIKE ?"
                    count_query += where_clause
                    select_query += where_clause
                    params.append(f"%{search_query}%")

                # Lấy tổng số bản ghi
                total_events = cursor.execute(count_query, tuple(params)).fetchone()[0]
                total_pages = (total_events + per_page - 1) // per_page

                # Lấy bản ghi cho trang hiện tại
                select_query += " ORDER BY id DESC LIMIT ? OFFSET ?"
                params.extend([per_page, (page - 1) * per_page])
                
                rows = cursor.execute(select_query, tuple(params)).fetchall()
                
                # Chuyển đổi dữ liệu để tương thích với template
                for row in rows:
                    # Ưu tiên hiển thị time_out nếu có, nếu không thì time_in
                    time_str = row['time_out'] or row['time_in']
                    dt_obj = datetime.strptime(time_str, "%Y-%m-%d %H:%M:%S")
                    
                    event_type = "UNKNOWN"
                    if row['status'] == STATUS_INSIDE:
                        event_type = "IN"
                    elif row['status'] == STATUS_COMPLETED:
                        event_type = "OUT"
                    elif row['status'] == STATUS_INVALID:
                        event_type = "INVALID"

                    events.append({
                        'dt': dt_obj,
                        'time_str': dt_obj.strftime('%d-%m-%Y %H:%M:%S'),
                        'plate': row['plate'],
                        'type': event_type,
                        'raw': row['image_path_out'] or row['image_path_in'],
                        'crop': None, # Không có ảnh crop trong DB
                        'db_id': row['id']
                    })

    except Timeout:
        error_message = "Không thể truy cập cơ sở dữ liệu do đang bị khóa. Vui lòng thử lại sau."
        print(f"🔥 [DB_LOCK] Timeout khi truy cập trang lịch sử.")
    except sqlite3.Error as e:
        error_message = "Lỗi truy vấn cơ sở dữ liệu."
        print(f"🔥 [DB_ERROR] Lỗi ở trang lịch sử: {e}")

    return render_template(
        'index.html', 
        events=events,
        page=page,
        total_pages=total_pages,
        search_query=search_query,
        error_message=error_message,
        per_page=per_page # Thêm lại biến per_page để template sử dụng
    )

def get_vehicles_inside_from_db() -> list:
    """
    Lấy danh sách các xe đang ở trong bãi trực tiếp từ CSDL.
    Đây là phương pháp hiệu quả hơn nhiều so với việc phân tích toàn bộ file log.
    """
    vehicles = []
    with FileLock(DB_LOCK_FILE, timeout=5.0):
        with get_db_connection() as conn:
            cursor = conn.cursor()
            cursor.execute(
                "SELECT id, plate, time_in, image_path_in FROM parking_log WHERE status = ? ORDER BY time_in DESC",
                (STATUS_INSIDE,)
            )
            rows = cursor.fetchall()
            for row in rows:
                dt_obj = datetime.strptime(row["time_in"], "%Y-%m-%d %H:%M:%S")
                vehicles.append({
                    'db_id': row['id'],
                    'plate': row['plate'],
                    'dt': dt_obj,
                    'time_str': dt_obj.strftime('%d-%m-%Y %H:%M:%S'),
                    'type': 'IN',
                    'raw': row['image_path_in'],
                    'crop': None
                })
    return vehicles


@app.route('/vehicles_in_lot')
def vehicles_in_lot():
    search_query = request.args.get('search', '').strip()
    vehicles = []
    error_message = None
    try:
        vehicles = get_vehicles_inside_from_db()
        if search_query:
            vehicles = [v for v in vehicles if search_query.lower() in v['plate'].lower()]
    except Timeout:
        error_message = "Không thể tải danh sách xe do cơ sở dữ liệu đang bận. Vui lòng thử lại."
        print("🔥 [DB_LOCK] Timeout khi lấy danh sách xe trong bãi.")
    except sqlite3.Error as e:
        error_message = "Lỗi truy vấn cơ sở dữ liệu."
        print(f"🔥 [DB_ERROR] Lỗi ở trang xe trong bãi: {e}")

    return render_template('vehicles_in_lot.html', vehicles=vehicles, count=len(vehicles), search_query=search_query, error=error_message)


@app.route('/')
def cameras():
    """Trang xem camera trực tiếp."""
    return render_template('cameras.html')


@app.route('/video_feed')
def video_feed():
    """Endpoint để cung cấp hình ảnh camera trực tiếp."""
    response = send_from_directory(TMP_FOLDER, 'live_view.jpg')
    response.headers['Cache-Control'] = 'no-cache, no-store, must-revalidate'
    response.headers['Pragma'] = 'no-cache'
    response.headers['Expires'] = '0'
    return response


@app.route('/statistics')
def statistics():
    """
    Trang thống kê, giờ đây truy vấn trực tiếp từ CSDL.
    """
    period = request.args.get('period', 'daily')
    today = date.today()
    
    if period == 'weekly':
        start_of_period = today - timedelta(days=today.weekday())
        period_title = "tuần này"
    elif period == 'monthly':
        start_of_period = today.replace(day=1)
        period_title = "tháng này"
    else: # daily
        start_of_period = today
        period_title = "hôm nay"

    start_dt_str = datetime.combine(start_of_period, datetime.min.time()).strftime("%Y-%m-%d %H:%M:%S")

    stats = { 'total_in': 0, 'total_out': 0, 'total_fail': 0 } # Giữ total_fail để không lỗi template
    error_message = None

    try:
        with FileLock(DB_LOCK_FILE, timeout=5.0):
            with get_db_connection() as conn:
                cursor = conn.cursor()
                
                # Đếm tổng lượt vào trong kỳ
                cursor.execute(
                    "SELECT COUNT(id) FROM parking_log WHERE time_in >= ?", (start_dt_str,)
                )
                stats['total_in'] = cursor.fetchone()[0]

                # Đếm tổng lượt ra trong kỳ
                cursor.execute(
                    "SELECT COUNT(id) FROM parking_log WHERE status = ? AND time_out >= ?", (STATUS_COMPLETED, start_dt_str)
                )
                stats['total_out'] = cursor.fetchone()[0]
                
                # Lưu ý: Không thể đếm 'total_fail' vì nó không được lưu trong CSDL.
                # Để giá trị là 0.

    except Timeout:
        error_message = "Không thể tải thống kê do cơ sở dữ liệu đang bận. Vui lòng thử lại."
        print("🔥 [DB_LOCK] Timeout khi lấy dữ liệu thống kê.")
    except sqlite3.Error as e:
        error_message = "Lỗi truy vấn cơ sở dữ liệu."
        print(f"🔥 [DB_ERROR] Lỗi ở trang thống kê: {e}")


    return render_template('statistics.html', stats=stats, period=period, period_title=period_title, error_message=error_message)

@app.route('/force_out', methods=['POST'])
def force_out():
    """Endpoint để xử lý việc cho xe ra khỏi bãi bằng tay."""
    db_id = request.form.get('db_id')
    
    if not db_id:
        print("⚠️ [ForceOut] Thiếu thông tin db_id.")
        # TODO: Thêm thông báo lỗi cho người dùng trên giao diện
        return redirect(url_for('vehicles_in_lot'))

    try:
        with FileLock(DB_LOCK_FILE, timeout=10.0):
            with get_db_connection() as conn:
                # Cập nhật trạng thái và thời gian ra, đồng thời đánh dấu cần đồng bộ lại
                cursor = conn.cursor()
                cursor.execute(
                    "UPDATE parking_log SET status = ?, time_out = ?, synced_to_server = 0 WHERE id = ?",
                    (STATUS_COMPLETED, get_vietnam_time_str(), db_id)
                )
                conn.commit()
                print(f"✅ [DB] Đã cập nhật trạng thái cho xe (DB_ID: {db_id}) thành COMPLETED.")
            

    except Timeout:
        print(f"🔥 [DB_LOCK] Không thể lấy khóa CSDL cho force_out (DB_ID: {db_id}).")
    except sqlite3.Error as e:
        print(f"🔥 [DB] Lỗi khi cập nhật CSDL cho force_out: {e}")
    
    return redirect(url_for('vehicles_in_lot'))

@app.route('/image/<filename>')
def get_image(filename):
    return send_from_directory(PICTURE_FOLDER, filename)

if __name__ == '__main__':
    if not os.path.exists(PICTURE_FOLDER):
        os.makedirs(PICTURE_FOLDER)
    if not os.path.exists(TMP_FOLDER):
        os.makedirs(TMP_FOLDER)

    print("✅ CSDL là nguồn dữ liệu duy nhất. Bỏ qua việc tải file log.")
    
    app.run(host='0.0.0.0', port=5000, debug=False)