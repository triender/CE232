"""
Constants used across the parking management system.
"""

# Database status constants
STATUS_INSIDE = 0       # Xe đã vào bãi, chưa ra
STATUS_COMPLETED = 1    # Giao dịch hoàn tất (xe đã ra)
STATUS_INVALID = 2      # Bản ghi không hợp lệ (lỗi dữ liệu, không thể đồng bộ)

# Trạng thái lỗi chi tiết để ghi vào DB và đồng bộ lên server
STATUS_FAIL_NO_PLATE = 3        # Lỗi: AI không nhận dạng được biển số khi quẹt thẻ
STATUS_FAIL_PLATE_INSIDE = 4    # Lỗi: Biển số đã được ghi nhận ở trong bãi với thẻ khác
STATUS_FAIL_PLATE_MISMATCH = 5  # Lỗi: An ninh - Biển số lúc ra không khớp với lúc vào

# File paths
ERROR_LOG_FILE = "error_log.txt"

# GPIO pins
GREEN_LED_PIN = 23

# Event types
EVENT_TYPE_IN = "IN"
EVENT_TYPE_OUT = "OUT"
EVENT_TYPE_FAIL_IN = "FAIL_IN"
EVENT_TYPE_FAIL_OUT = "FAIL_OUT"
EVENT_TYPE_MANUAL_OUT = "MANUAL_OUT"

# Status events
STATUS_SUCCESS = "SUCCESS"
STATUS_NO_PLATE_DETECTED = "NO_PLATE_DETECTED"
STATUS_PLATE_MISMATCH = "PLATE_MISMATCH"
STATUS_ALREADY_INSIDE_DIFF_RFID = "ALREADY_INSIDE_DIFF_RFID"
