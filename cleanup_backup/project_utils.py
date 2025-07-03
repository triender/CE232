"""
Utility functions used across the parking management system.
"""
import os
from datetime import datetime, timezone, timedelta


def get_vietnam_time_object() -> datetime:
    """Lấy thời gian Việt Nam hiện tại."""
    return datetime.now(timezone(timedelta(hours=7)))


def get_vietnam_time_str() -> str:
    """Lấy thời gian Việt Nam hiện tại dưới dạng chuỗi."""
    return get_vietnam_time_object().strftime("%Y-%m-%d %H:%M:%S")


def get_vietnam_time_for_filename() -> str:
    """Lấy thời gian Việt Nam cho tên file."""
    return get_vietnam_time_object().strftime("%d_%m_%Y_%Hh%Mm%S")


def normalize_plate(plate_text: str) -> str:
    """Chuẩn hóa biển số xe."""
    if not plate_text: 
        return ""
    return "".join(filter(str.isalnum, plate_text)).upper()


def sanitize_filename_component(name_part: str) -> str:
    """Làm sạch tên file."""
    return "".join(c if c.isalnum() else "_" for c in str(name_part)).rstrip("_")


def ensure_directories_exist(*directories) -> None:
    """Tạo các thư mục nếu chưa tồn tại."""
    for directory in directories:
        os.makedirs(directory, exist_ok=True)
