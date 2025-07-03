#!/bin/bash

# Dừng script ngay lập tức nếu có lỗi
set -e

# Lấy đường dẫn thư mục chứa file script này
DIR="$( cd "$( dirname "${BASH_SOURCE[0]}" )" &> /dev/null && pwd )"

# Function to cleanup processes
cleanup() {
    echo "🧹 Cleaning up processes..."
    
    # Kill Flask app if running
    if [ ! -z "$FLASK_PID" ] && kill -0 "$FLASK_PID" 2>/dev/null; then
        echo "🛑 Stopping Flask app (PID: $FLASK_PID)..."
        kill -TERM "$FLASK_PID" 2>/dev/null || true
        sleep 2
        # Force kill if still running
        if kill -0 "$FLASK_PID" 2>/dev/null; then
            kill -KILL "$FLASK_PID" 2>/dev/null || true
        fi
    fi
    
    # Kill any remaining processes on port 5000
    echo "🔍 Cleaning up any remaining processes on port 5000..."
    fuser -k -n tcp 5000 2>/dev/null || true
    
    echo "✅ Cleanup completed"
}

# Set trap to cleanup on script exit
trap cleanup EXIT INT TERM

# Kích hoạt môi trường ảo (virtual environment)
echo "🚀 Kích hoạt môi trường ảo..."
source "$DIR/ai_env/bin/activate"

# Di chuyển đến thư mục của dự án
cd "$DIR"

# Tìm và dừng bất kỳ tiến trình nào đang sử dụng port 5000
echo "🔍 Đang kiểm tra và giải phóng Port 5000..."
fuser -k -n tcp 5000 2>/dev/null || true
sleep 1 # Chờ một chút để port được giải phóng

# Chạy ứng dụng web trong background và lưu PID
echo "🌐 Khởi động ứng dụng web theo dõi..."
python3 app.py > flask_app.log 2>&1 &
FLASK_PID=$!

# Kiểm tra xem Flask app có khởi động thành công không
sleep 3
if ! kill -0 "$FLASK_PID" 2>/dev/null; then
    echo "❌ Lỗi: Không thể khởi động ứng dụng web. Kiểm tra flask_app.log để biết chi tiết."
    exit 1
fi

# Get the Raspberry Pi's IP address for remote access
PI_IP=$(hostname -I | awk '{print $1}')

echo "✅ Ứng dụng web đã khởi động thành công (PID: $FLASK_PID)"
echo "🌐 Web interface (local):  http://localhost:5000"
echo "🌐 Web interface (remote): http://$PI_IP:5000"
echo "📝 Flask logs: flask_app.log"
echo ""
echo "💡 Sử dụng localhost:5000 chỉ từ Raspberry Pi này"
echo "💡 Sử dụng $PI_IP:5000 từ các thiết bị khác"

# Chạy ứng dụng Python chính
echo "✅ Môi trường đã sẵn sàng. Bắt đầu chạy ứng dụng chính..."
echo "ℹ️  Press Ctrl+C to stop both applications"

# Run main application - this will block until Ctrl+C
python3 LPR.py

# Cleanup will be handled by the trap
