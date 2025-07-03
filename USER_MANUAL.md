# User Manual

## Tổng quan hệ thống

Hệ thống này là một giải pháp quản lý bãi đỗ xe tự động, sử dụng công nghệ nhận dạng biển số xe (LPR) và RFID để kiểm soát ra vào. Hệ thống được thiết kế để hoạt động độc lập, ưu tiên xử lý ngoại tuyến (offline-first), đảm bảo hoạt động liên tục ngay cả khi không có kết nối mạng ổn định.

## Giao diện Web

Giao diện web cung cấp khả năng giám sát và quản lý hệ thống theo thời gian thực.

### Các tính năng chính

#### 1. Chế độ xem Camera trực tiếp (/)
- **Mục đích**: Giám sát hình ảnh trực tiếp từ camera.
- **Tính năng**:
    - Luồng video trực tiếp.
    - Cập nhật hình ảnh theo thời gian thực.
    - Chỉ báo trạng thái camera.

#### 2. Lịch sử truy cập (/log)
- **Mục đích**: Xem lại tất cả các sự kiện xe ra vào.
- **Tính năng**:
    - Danh sách sự kiện có thể tìm kiếm.
    - Phân trang.
    - Lọc theo loại sự kiện (VÀO, RA, LỖI).
    - Hình ảnh thu nhỏ cho mỗi sự kiện.
    - Dấu thời gian và chi tiết sự kiện.

#### 3. Xe trong bãi (/vehicles_in_lot)
- **Mục đích**: Quản lý các phương tiện hiện đang ở trong bãi.
- **Tính năng**:
    - Danh sách các xe hiện có trong bãi.
    - Thời gian vào của mỗi xe.
    - Khả năng cho xe ra theo cách thủ công.
    - Tìm kiếm theo biển số xe.

#### 4. Thống kê (/statistics)
- **Mục đích**: Xem phân tích sử dụng.
- **Tính năng**:
    - Báo cáo hàng ngày, hàng tuần, hàng tháng.
    - Số lượng xe vào và ra.
    - Các chỉ số hiệu suất hệ thống.

## Hoạt động của hệ thống

### Quy trình hoạt động

#### Quy trình xe vào
1.  **Quét RFID**: Người dùng đưa thẻ RFID vào đầu đọc.
2.  **Chụp ảnh**: Hệ thống tự động chụp ảnh.
3.  **Nhận dạng biển số**: AI xử lý ảnh để phát hiện biển số.
4.  **Xác thực**: Hệ thống kiểm tra tính hợp lệ của biển số để vào.
5.  **Cập nhật cơ sở dữ liệu**: Tạo bản ghi vào với trạng thái "INSIDE".
6.  **Phản hồi**: Đèn LED xanh lục nhấp nháy để báo hiệu vào thành công.

#### Quy trình xe ra
1.  **Quét RFID**: Người dùng đưa cùng một thẻ RFID vào đầu đọc.
2.  **Chụp ảnh**: Hệ thống chụp ảnh lúc ra.
3.  **Nhận dạng biển số**: AI phát hiện biển số.
4.  **Xác thực**: Hệ thống xác minh biển số khớp với bản ghi lúc vào.
5.  **Cập nhật cơ sở dữ liệu**: Cập nhật bản ghi với thời gian ra và trạng thái "COMPLETED".
6.  **Phản hồi**: Đèn LED xanh lục nhấp nháy để báo hiệu ra thành công.

### Các loại sự kiện

#### Sự kiện thành công
-   **IN**: Xe vào thành công.
-   **OUT**: Xe ra thành công.

#### Sự kiện thất bại
-   **FAIL_IN**: Vào không thành công do lỗi xác thực.
-   **FAIL_OUT**: Ra không thành công do lỗi xác thực.

#### Sự kiện thủ công
-   **MANUAL_OUT**: Xe được cho ra theo cách thủ công qua giao diện web.

### Các kịch bản lỗi

#### Các lý do thất bại phổ biến
1.  **NO_PLATE_DETECTED**: Camera không thể phát hiện biển số xe.
2.  **PLATE_MISMATCH**: Biển số lúc ra không khớp với biển số lúc vào.
3.  **ALREADY_INSIDE_DIFF_RFID**: Biển số đã ở trong bãi với một thẻ RFID khác.

## Quản lý dữ liệu

#### Tệp nhật ký
-   **access_log.jsonl**: Dữ liệu sự kiện có cấu trúc.
-   **error_log.txt**: Lỗi hệ thống và chẩn đoán.
-   **parking_data.db**: Cơ sở dữ liệu SQLite với tất cả các bản ghi.

#### Lưu trữ hình ảnh
-   **picture/**: Tất cả các hình ảnh đã chụp (vào/ra).
-   **tmp/**: Các tệp tạm thời (luồng camera trực tiếp).
-   **offline_images/**: Lưu trữ hình ảnh dự phòng.

## Quản lý cấu hình

### Biến môi trường (.env)

#### Cài đặt bắt buộc
```bash
API_ENDPOINT="http://server:3000/api/parking/events/submit"
UID="device-001"
YOLOV5_REPO_PATH="/home/minhtest/yolov5"
LP_DETECTOR_MODEL_PATH="model/LP_detector_nano_61.pt"
LP_OCR_MODEL_PATH="model/LP_ocr_nano_62.pt"
```

#### Cài đặt tùy chọn
```bash
DB_FILE="parking_data.db"
IMAGE_DIR="offline_images"
PICTURE_OUTPUT_DIR="picture"
```

### Cấu hình mô hình

#### Tệp mô hình AI
-   **LP_detector_nano_61.pt**: Mô hình phát hiện biển số xe.
-   **LP_ocr_nano_62.pt**: Mô hình nhận dạng ký tự
