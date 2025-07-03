"""
Configuration management for the parking system.
"""
import os
from dotenv import load_dotenv

# Load environment variables
load_dotenv()

class Config:
    # API Configuration
    API_ENDPOINT = os.getenv("API_ENDPOINT", "http://localhost:3000/api/events/submit")
    UID = os.getenv("UID")
    
    # Database Configuration
    DB_FILE = os.getenv("DB_FILE", "parking_data.db")
    
    # Directory Configuration
    IMAGE_DIR = os.getenv("IMAGE_DIR", "offline_images")
    PICTURE_OUTPUT_DIR = os.getenv("PICTURE_OUTPUT_DIR", "picture")
    TMP_DIR = os.path.join(os.path.dirname(os.path.abspath(__file__)), "tmp")
    
    # AI Model Configuration
    YOLOV5_REPO_PATH = os.getenv("YOLOV5_REPO_PATH")
    LP_DETECTOR_MODEL_PATH = os.getenv("LP_DETECTOR_MODEL_PATH")
    LP_OCR_MODEL_PATH = os.getenv("LP_OCR_MODEL_PATH")
    
    # Threading Configuration
    DB_LOCK_TIMEOUT = 15
    CAMERA_TIMEOUT = 5.0
    
    # AI Configuration
    CONFIDENCE_THRESHOLD = 0.60
    DETECTION_SIZE = 640
    
    @classmethod
    def validate(cls) -> bool:
        """Validate that all required configuration is present."""
        required_vars = [
            cls.API_ENDPOINT, cls.DB_FILE, cls.IMAGE_DIR, 
            cls.PICTURE_OUTPUT_DIR, cls.YOLOV5_REPO_PATH,
            cls.LP_DETECTOR_MODEL_PATH, cls.LP_OCR_MODEL_PATH
        ]
        return all(required_vars)
