# Parking System Management Scripts

Sau khi sửa lỗi luồng xử lý dữ liệu, hệ thống đã được cải tiến với các script quản lý mới để vận hành dễ dàng hơn.

## 🚀 Scripts Quản Lý

### 1. `manage.sh` - Script Quản Lý Chính
```bash
./manage.sh start    # Khởi động hệ thống
./manage.sh stop     # Dừng hệ thống  
./manage.sh restart  # Khởi động lại
./manage.sh status   # Kiểm tra trạng thái
./manage.sh logs     # Xem logs gần đây
./manage.sh help     # Hiển thị hướng dẫn
```

### 2. `start.sh` - Khởi Động Hệ Thống
- Tự động cleanup các process cũ
- Khởi động Flask web interface trong background
- Chạy LPR.py (main parking system)
- Quản lý PID và cleanup tự động khi dừng

### 3. `stop.sh` - Dừng Hệ Thống An Toàn  
- Dừng tất cả processes liên quan
- Cleanup port 5000
- Force kill nếu cần thiết
- Báo cáo trạng thái cleanup

### 4. `status.sh` - Kiểm Tra Trạng Thái
- Hiển thị trạng thái các services
- Kiểm tra ports và files
- Thống kê database
- Thông tin system resources

### 5. `network_test.sh` - Kiểm Tra Kết Nối Mạng
Kiểm tra toàn diện khả năng truy cập web interface từ các ngữ cảnh mạng khác nhau.

```bash
./network_test.sh
```

**Tính năng:**
- Kiểm tra localhost, 127.0.0.1 và truy cập IP bên ngoài
- Cung cấp hướng dẫn rõ ràng cho truy cập từ xa và cục bộ
- Hiển thị cấu hình mạng và chi tiết giao diện
- Giải thích lý do tại sao localhost không hoạt động từ các thiết bị từ xa

**Ví dụ về đầu ra:**
```
🌐 Kiểm Tra Kết Nối Mạng Hệ Thống Đỗ Xe
===========================================
📍 IP Raspberry Pi: 192.168.1.29
📍 Tên máy: raspberrypi

🧪 Đang Kiểm Tra Truy Cập Cục Bộ...
✅ localhost:5000 - CÓ THỂ TRUY CẬP
✅ 127.0.0.1:5000 - CÓ THỂ TRUY CẬP
✅ 192.168.1.29:5000 - CÓ THỂ TRUY CẬP

📊 Tóm Tắt Truy Cập:
├─ Từ Raspberry Pi này:
│  ├─ ✅ http://localhost:5000
│  ├─ ✅ http://127.0.0.1:5000
│  └─ ✅ http://192.168.1.29:5000
└─ Từ các thiết bị khác:
   └─ ✅ http://192.168.1.29:5000 (CHỈ)

💡 Hướng Dẫn Sử Dụng Mạng:
• Chỉ sử dụng localhost:5000 khi làm việc trực tiếp trên Pi này
• Sử dụng 192.168.1.29:5000 khi truy cập từ điện thoại, laptop, v.v.
• localhost trên các thiết bị từ xa trỏ đến localhost CỦA CHÚNG, không phải Pi này
```

## 🔧 Cách Sử Dụng

### Khởi động hệ thống lần đầu:
```bash
./manage.sh start
```

### Kiểm tra hệ thống đang chạy:
```bash
./manage.sh status
```

### Xem logs khi có vấn đề:
```bash
./manage.sh logs
```

### Dừng hệ thống:
```bash
./manage.sh stop
```

### Khởi động lại khi có lỗi:
```bash
./manage.sh restart
```

## 📁 Files Log

- `flask_app.log` - Logs của web interface
- `error_log.txt` - Logs lỗi hệ thống
- `parking_data.db` - Database chính
- `tmp/live_view.jpg` - Ảnh camera live

## 🌐 Web Interface

- URL: http://localhost:5000
- Camera trực tiếp: http://localhost:5000/
- Lịch sử: http://localhost:5000/log
- Xe trong bãi: http://localhost:5000/vehicles_in_lot
- Thống kê: http://localhost:5000/statistics

## 🛠️ Troubleshooting

### Khi có lỗi "Port 5000 already in use":
```bash
./manage.sh stop
./manage.sh start
```

### Khi database bị lock:
```bash
./manage.sh restart
```

### Khi camera không hoạt động:
- Kiểm tra camera kết nối
- Restart hệ thống
- Xem logs để biết chi tiết

### Khi network không sync được:
- Kiểm tra kết nối internet
- Kiểm tra API endpoint trong `.env`
- Xem error_log.txt

## 📊 Monitoring

### Theo dõi real-time:
```bash
# Theo dõi Flask logs
tail -f flask_app.log

# Theo dõi error logs  
tail -f error_log.txt

# Kiểm tra trạng thái định kỳ
watch -n 5 ./manage.sh status
```

## 🔒 System Security

- Tất cả scripts đều có proper cleanup
- Process management an toàn
- Database locking để tránh corruption
- Error handling toàn diện

## 💡 Tips

1. **Luôn dùng `manage.sh`** thay vì chạy trực tiếp các script khác
2. **Kiểm tra status** trước khi start/stop
3. **Xem logs** khi có vấn đề
4. **Backup database** định kỳ
5. **Monitor system resources** để tránh quá tải

---

*Scripts này được tạo để đi kèm với việc sửa lỗi luồng xử lý dữ liệu, đảm bảo hệ thống hoạt động ổn định và dễ quản lý.*
