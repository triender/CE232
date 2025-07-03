#!/bin/bash

# Dừng script ngay lập tức nếu có lỗi
set -e

# Lấy đường dẫn thư mục chứa file script này
DIR="$( cd "$( dirname "${BASH_SOURCE[0]}" )" &> /dev/null && pwd )"

# Kích hoạt môi trường ảo (virtual environment)
echo "🚀 Kích hoạt môi trường ảo..."
source "$DIR/ai_env/bin/activate"

# Di chuyển đến thư mục của dự án
cd "$DIR"

# MỚI: Tìm và dừng bất kỳ tiến trình nào đang sử dụng port 5000
echo "🔍 Đang kiểm tra và giải phóng Port 5000..."
# Dùng fuser để tìm và kill tiến trình. Thêm `|| true` để script không dừng nếu không có tiến trình nào được tìm thấy.
fuser -k -n tcp 5000 || true
sleep 1 # Chờ một chút để port được giải phóng

# Chạy ứng dụng web để theo dõi (chạy nền)
echo "🌐 Khởi động ứng dụng web theo dõi (chạy nền)..."
python app.py > /dev/null 2>&1 &

# Chờ một chút để app web khởi động
sleep 2

# Chạy ứng dụng Python chính
echo "✅ Môi trường đã sẵn sàng. Bắt đầu chạy ứng dụng chính..."
python LPR.py
