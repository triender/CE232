"""
Network utilities for safe server communication.
Handles retries, timeouts, and proper error handling.
"""
import requests
import time
import json
from typing import Dict, Any, Optional, Tuple, Union
from enum import Enum
from thread_safe_utils import SafeErrorLogger


class SyncResult(Enum):
    """Enumeration for sync operation results."""
    SUCCESS = "success"
    TEMPORARY_FAILURE = "temporary_failure"
    PERMANENT_FAILURE = "permanent_failure"
    NETWORK_ERROR = "network_error"


class NetworkManager:
    """Manages network operations with proper error handling and retries."""
    
    def __init__(self, api_endpoint: str, error_logger: SafeErrorLogger):
        self.api_endpoint = api_endpoint
        self.error_logger = error_logger
        
        # Network configuration
        self.connect_timeout = 10.0    # Connection timeout
        self.read_timeout = 30.0       # Read timeout  
        self.max_retries = 3           # Max retry attempts
        self.retry_delay = 2.0         # Delay between retries
        
        # Session for connection reuse
        self.session = requests.Session()
        self.session.headers.update({
            'User-Agent': 'ParkingSystem/1.0',
            'Accept': 'application/json'
        })
    
    def _make_request(self, method: str, url: str, **kwargs) -> requests.Response:
        """Make HTTP request with proper timeout and error handling."""
        # Set default timeout if not provided
        if 'timeout' not in kwargs:
            kwargs['timeout'] = (self.connect_timeout, self.read_timeout)
        
        return self.session.request(method, url, **kwargs)
    
    def _is_retryable_error(self, e: Exception) -> bool:
        """Determine if an error is retryable."""
        if isinstance(e, requests.exceptions.Timeout):
            return True
        elif isinstance(e, requests.exceptions.ConnectionError):
            return True
        elif isinstance(e, requests.exceptions.RequestException):
            if hasattr(e, 'response') and e.response is not None:
                # Retry on 5xx server errors
                return 500 <= e.response.status_code < 600
            return True
        return False
    
    def send_event_to_server(self, event_payload: Dict[str, Any], 
                           image_data_bytes: Optional[bytes] = None) -> SyncResult:
        """
        Send event to server with retries and proper error handling.
        
        Args:
            event_payload: Event data to send
            image_data_bytes: Optional image data
            
        Returns:
            SyncResult indicating the outcome
        """
        log_identifier = event_payload.get('device_db_id') or event_payload.get('timestamp')
        print(f"📡 [Network] Preparing to send event: ID/Time {log_identifier}, Type: {event_payload.get('event_type')}")

        # Server expects 'token' instead of 'rfid_token'
        if 'rfid_token' in event_payload:
            event_payload = event_payload.copy()  # Don't modify original
            event_payload['token'] = event_payload.pop('rfid_token')

        # Prepare request
        files_payload = {}
        if image_data_bytes:
            files_payload['image'] = (f"img_{log_identifier}.jpg", image_data_bytes, 'image/jpeg')

        # Retry loop
        for attempt in range(self.max_retries):
            try:
                if image_data_bytes:
                    # Send as multipart/form-data
                    response = self._make_request(
                        'POST', 
                        self.api_endpoint, 
                        data=event_payload, 
                        files=files_payload
                    )
                else:
                    # Send as application/json
                    response = self._make_request(
                        'POST', 
                        self.api_endpoint, 
                        json=event_payload
                    )

                # Handle response
                if 200 <= response.status_code < 300:
                    print(f"✅ [Network] Server accepted event {log_identifier}")
                    return SyncResult.SUCCESS
                    
                elif 400 <= response.status_code < 500:
                    # Client error - don't retry
                    error_msg = f"Server rejected event {log_identifier} (Client Error: {response.status_code}): {response.text[:200]}"
                    print(f"❌ [Network] {error_msg}")
                    self.error_logger.log_error(error_msg, category="SERVER_RESPONSE")
                    return SyncResult.PERMANENT_FAILURE
                    
                else:
                    # Server error - might be retryable
                    error_msg = f"Server error for event {log_identifier} (Code: {response.status_code})"
                    print(f"❌ [Network] {error_msg}")
                    self.error_logger.log_error(f"{error_msg}: {response.text[:200]}", category="SERVER_RESPONSE")
                    
                    if attempt < self.max_retries - 1:
                        print(f"🔄 [Network] Retrying in {self.retry_delay} seconds... (attempt {attempt + 2}/{self.max_retries})")
                        time.sleep(self.retry_delay)
                        continue
                    return SyncResult.TEMPORARY_FAILURE

            except requests.exceptions.RequestException as e:
                error_msg = f"Network error for event {log_identifier}: {str(e)[:200]}"
                print(f"❌ [Network] {error_msg}")
                self.error_logger.log_error(error_msg, category="NETWORK", exception_obj=e)
                
                if self._is_retryable_error(e) and attempt < self.max_retries - 1:
                    print(f"🔄 [Network] Retrying in {self.retry_delay} seconds... (attempt {attempt + 2}/{self.max_retries})")
                    time.sleep(self.retry_delay)
                    continue
                    
                return SyncResult.NETWORK_ERROR
            
            except Exception as e:
                error_msg = f"Unexpected error sending event {log_identifier}: {str(e)[:200]}"
                print(f"🔥 [Network] {error_msg}")
                self.error_logger.log_error(error_msg, category="NETWORK", exception_obj=e)
                return SyncResult.NETWORK_ERROR

        return SyncResult.TEMPORARY_FAILURE
    
    def test_connection(self) -> bool:
        """Test connection to the server."""
        try:
            # Try a simple GET request to test connectivity
            response = self._make_request('GET', self.api_endpoint.replace('/submit', '/health'), timeout=(5, 10))
            return True
        except Exception as e:
            print(f"🔌 [Network] Connection test failed: {e}")
            return False
    
    def close(self):
        """Close the session."""
        if self.session:
            self.session.close()


def create_event_payload(uid: str, plate: str, rfid_token: str, timestamp: str, 
                        event_type: str, details: str, device_db_id: int) -> Dict[str, Any]:
    """Create a properly formatted event payload for the server."""
    return {
        "uid": uid,
        "plate": plate,
        "rfid_token": rfid_token,  # Will be renamed to 'token' in NetworkManager
        "timestamp": timestamp,
        "event_type": event_type,
        "details": details,
        "device_db_id": device_db_id
    }
