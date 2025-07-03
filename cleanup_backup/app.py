import threading
from flask import Flask, render_template, send_from_directory, jsonify, request, redirect, url_for
import os
from datetime import datetime, date, timedelta
import sqlite3
from filelock import FileLock, Timeout
from constants import STATUS_INSIDE, STATUS_COMPLETED, STATUS_INVALID
from project_utils import get_vietnam_time_str
from database_manager import SafeDatabaseManager
from thread_safe_utils import SafeErrorLogger

# Configuration
PICTURE_FOLDER = os.getenv("PICTURE_OUTPUT_DIR", "picture")
TMP_FOLDER = os.path.join(os.path.dirname(os.path.abspath(__file__)), "tmp")
DB_FILE = os.getenv("DB_FILE", "parking_data.db")
DB_LOCK_FILE = DB_FILE + ".lock"

# Initialize services
db_manager = SafeDatabaseManager(DB_FILE)
error_logger = SafeErrorLogger("app_error.log")
app = Flask(__name__)

def get_db_connection():
    """Get database connection with row factory."""
    conn = sqlite3.connect(DB_FILE, timeout=5.0)
    conn.row_factory = sqlite3.Row
    return conn

def handle_db_error(operation, error):
    """Centralized database error handling."""
    error_logger.log_error(f"Error in {operation}: {error}", "WEB_APP", error)
    return "Lỗi cơ sở dữ liệu. Vui lòng thử lại sau."

def create_event(row, event_type, time_field):
    """Helper function to create event object."""
    time_str = row[time_field]
    dt_obj = datetime.strptime(time_str, "%Y-%m-%d %H:%M:%S")
    image_path = row['image_path_out'] if event_type == "OUT" else row['image_path_in']
    
    return {
        'dt': dt_obj,
        'time_str': dt_obj.strftime('%d-%m-%Y %H:%M:%S'),
        'plate': row['plate'],
        'type': event_type,
        'raw': image_path,
        'crop': None,
        'db_id': row['id']
    }

@app.route('/log')
def index():
    """Trang lịch sử với sự kiện IN/OUT riêng biệt."""
    page = request.args.get('page', 1, type=int)
    per_page = 10
    search_query = request.args.get('search', '').strip()
    
    events = []
    error_message = None

    try:
        with FileLock(DB_LOCK_FILE, timeout=5.0):
            with get_db_connection() as conn:
                cursor = conn.cursor()
                
                # Build query
                query = "SELECT * FROM parking_log"
                params = []
                if search_query:
                    query += " WHERE plate LIKE ?"
                    params.append(f"%{search_query}%")
                query += " ORDER BY id DESC"
                
                rows = cursor.execute(query, params).fetchall()
                
                # Process records into events
                all_events = []
                for row in rows:
                    if row['time_out'] and row['status'] == STATUS_COMPLETED:
                        # Add both OUT and IN events for completed trips
                        all_events.append(create_event(row, "OUT", 'time_out'))
                        all_events.append(create_event(row, "IN", 'time_in'))
                    else:
                        # Add single event for ongoing or invalid entries
                        event_type = "INVALID" if row['status'] == STATUS_INVALID else "IN"
                        all_events.append(create_event(row, event_type, 'time_in'))
                
                # Sort and paginate
                all_events.sort(key=lambda x: x['dt'], reverse=True)
                total_events = len(all_events)
                total_pages = (total_events + per_page - 1) // per_page
                
                start_idx = (page - 1) * per_page
                events = all_events[start_idx:start_idx + per_page]

    except Timeout:
        error_message = "Không thể truy cập cơ sở dữ liệu do đang bị khóa. Vui lòng thử lại sau."
    except sqlite3.Error as e:
        error_message = handle_db_error("log page", e)

    return render_template('index.html', 
                         events=events,
                         page=page,
                         total_pages=total_pages or 1,
                         search_query=search_query,
                         error_message=error_message,
                         per_page=per_page)

def get_vehicles_inside_from_db() -> list:
    """
    Get list of vehicles currently inside using SafeDatabaseManager.
    """
    try:
        return db_manager.get_vehicles_inside()
    except Exception as e:
        error_logger.log_error(f"Error getting vehicles inside: {e}", "WEB_APP", e)
        return []


@app.route('/vehicles_in_lot')
def vehicles_in_lot():
    search_query = request.args.get('search', '').strip()
    vehicles = []
    error_message = None
    try:
        vehicles = db_manager.get_vehicles_inside(search_query if search_query else None)
    except Exception as e:
        error_message = "Không thể tải danh sách xe do lỗi cơ sở dữ liệu. Vui lòng thử lại."
        error_logger.log_error(f"Error in vehicles_in_lot: {e}", "WEB_APP", e)

    return render_template('vehicles_in_lot.html', vehicles=vehicles, count=len(vehicles), search_query=search_query, error_message=error_message)


@app.route('/force_out/<int:db_id>', methods=['POST'])
def force_out(db_id):
    """
    Endpoint to handle forced vehicle exit from web interface.
    Now using SafeDatabaseManager for better error handling.
    """
    error = None
    try:
        current_time = get_vietnam_time_str()
        success = db_manager.update_vehicle_exit(db_id, current_time, None)
        
        if success:
            print(f"✅ [WEB_UI] Successfully forced exit for DB ID: {db_id}")
        else:
            error = "Không tìm thấy xe hoặc xe đã ra khỏi bãi."
            print(f"⚠️ [WEB_UI] Warning: Invalid force exit attempt. ID: {db_id}")

    except Exception as e:
        error = "Lỗi CSDL khi cập nhật trạng thái."
        error_logger.log_error(f"Error in force_out for ID {db_id}: {e}", "WEB_APP", e)

    # Redirect user back to vehicles in lot page
    return redirect(url_for('vehicles_in_lot', error=error))


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