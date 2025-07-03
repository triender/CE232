"""
Database management utilities for the parking system.
Handles connection pooling and safe database operations.
"""
import sqlite3
import threading
from contextlib import contextmanager
from typing import Optional, Dict, Any, List
from constants import *
from project_utils import get_vietnam_time_str, ensure_directories_exist


class SafeDatabaseManager:
    """Thread-safe database manager with connection pooling."""
    
    def __init__(self, db_file: str):
        self.db_file = db_file
        self._local = threading.local()
        self._init_lock = threading.Lock()
        self._initialized = False
    
    def _get_connection(self) -> sqlite3.Connection:
        """Get thread-local database connection."""
        if not hasattr(self._local, 'connection') or self._local.connection is None:
            self._local.connection = sqlite3.connect(
                self.db_file, 
                timeout=10.0,
                check_same_thread=False
            )
            self._local.connection.row_factory = sqlite3.Row
            # Enable WAL mode for better concurrency
            self._local.connection.execute("PRAGMA journal_mode=WAL")
            self._local.connection.execute("PRAGMA synchronous=NORMAL")
            self._local.connection.execute("PRAGMA cache_size=10000")
            self._local.connection.execute("PRAGMA temp_store=memory")
        return self._local.connection
    
    @contextmanager
    def get_connection(self):
        """Get a database connection with automatic cleanup."""
        conn = None
        try:
            conn = self._get_connection()
            yield conn
        except Exception as e:
            if conn:
                conn.rollback()
            print(f"🔥 [SafeDB] Database error: {e}")
            raise
        finally:
            if conn:
                try:
                    conn.commit()
                except Exception as e:
                    print(f"🔥 [SafeDB] Commit error: {e}")
                    conn.rollback()
    
    def init_database(self) -> None:
        """Initialize database with proper schema."""
        with self._init_lock:
            if self._initialized:
                return
            
            with self.get_connection() as conn:
                cursor = conn.cursor()
                
                # Create main table with better constraints
                cursor.execute('''
                    CREATE TABLE IF NOT EXISTS parking_log (
                        id INTEGER PRIMARY KEY AUTOINCREMENT, 
                        plate TEXT NOT NULL, 
                        rfid_token TEXT NOT NULL,
                        time_in TEXT NOT NULL, 
                        time_out TEXT NULL, 
                        image_path_in TEXT NULL, 
                        image_path_out TEXT NULL,
                        status INTEGER NOT NULL CHECK (status IN (0, 1, 2, 3, 4, 5)), 
                        synced_to_server INTEGER NOT NULL DEFAULT 0 CHECK (synced_to_server IN (0, 1)),
                        created_at TEXT NOT NULL DEFAULT (datetime('now')),
                        updated_at TEXT NOT NULL DEFAULT (datetime('now'))
                    )
                ''')
                
                # Create indexes for better performance
                cursor.execute("CREATE INDEX IF NOT EXISTS idx_token_status ON parking_log (rfid_token, status)")
                cursor.execute("CREATE INDEX IF NOT EXISTS idx_plate_status ON parking_log (plate, status)")
                cursor.execute("CREATE INDEX IF NOT EXISTS idx_sync_status ON parking_log (synced_to_server)")
                cursor.execute("CREATE INDEX IF NOT EXISTS idx_time_in ON parking_log (time_in)")
                
                # Create trigger to update updated_at
                cursor.execute('''
                    CREATE TRIGGER IF NOT EXISTS update_parking_log_timestamp 
                    AFTER UPDATE ON parking_log
                    FOR EACH ROW
                    BEGIN
                        UPDATE parking_log SET updated_at = datetime('now') WHERE id = NEW.id;
                    END
                ''')
                
                conn.commit()
                print("✅ [SafeDB] Database initialized with enhanced schema")
            
            self._initialized = True
    
    def insert_vehicle_entry(self, plate: str, rfid_token: str, time_in: str, 
                           image_path_in: Optional[str], status: int) -> int:
        """Insert a new vehicle entry and return the ID."""
        with self.get_connection() as conn:
            cursor = conn.cursor()
            cursor.execute("""
                INSERT INTO parking_log 
                (plate, rfid_token, time_in, image_path_in, status, synced_to_server) 
                VALUES (?, ?, ?, ?, ?, ?)
            """, (plate, rfid_token, time_in, image_path_in, status, 0))
            return cursor.lastrowid
    
    def update_vehicle_exit(self, record_id: int, time_out: str, 
                          image_path_out: Optional[str]) -> bool:
        """Update vehicle exit information."""
        with self.get_connection() as conn:
            cursor = conn.cursor()
            cursor.execute("""
                UPDATE parking_log 
                SET time_out = ?, image_path_out = ?, status = ?, synced_to_server = 0
                WHERE id = ? AND status = ?
            """, (time_out, image_path_out, STATUS_COMPLETED, record_id, STATUS_INSIDE))
            return cursor.rowcount > 0
    
    def get_vehicle_inside_by_rfid(self, rfid_token: str) -> Optional[sqlite3.Row]:
        """Get vehicle record that's currently inside by RFID token."""
        with self.get_connection() as conn:
            cursor = conn.cursor()
            cursor.execute("""
                SELECT * FROM parking_log 
                WHERE rfid_token = ? AND status = ? 
                ORDER BY time_in DESC LIMIT 1
            """, (rfid_token, STATUS_INSIDE))
            return cursor.fetchone()
    
    def is_plate_inside(self, plate: str) -> bool:
        """Check if a plate is currently inside the parking lot."""
        with self.get_connection() as conn:
            cursor = conn.cursor()
            cursor.execute("""
                SELECT 1 FROM parking_log 
                WHERE plate = ? AND status = ? 
                LIMIT 1
            """, (plate, STATUS_INSIDE))
            return cursor.fetchone() is not None
    
    def get_unsynced_records(self, limit: int = 1) -> List[sqlite3.Row]:
        """Get unsynced records for server synchronization."""
        with self.get_connection() as conn:
            cursor = conn.cursor()
            cursor.execute("""
                SELECT * FROM parking_log 
                WHERE synced_to_server = 0 
                ORDER BY id ASC 
                LIMIT ?
            """, (limit,))
            return cursor.fetchall()
    
    def mark_as_synced(self, record_id: int) -> bool:
        """Mark a record as synced to server."""
        with self.get_connection() as conn:
            cursor = conn.cursor()
            cursor.execute("""
                UPDATE parking_log 
                SET synced_to_server = 1 
                WHERE id = ?
            """, (record_id,))
            return cursor.rowcount > 0
    
    def mark_as_invalid(self, record_id: int) -> bool:
        """Mark a record as invalid due to permanent sync failure."""
        with self.get_connection() as conn:
            cursor = conn.cursor()
            cursor.execute("""
                UPDATE parking_log 
                SET synced_to_server = 1, status = ? 
                WHERE id = ?
            """, (STATUS_INVALID, record_id))
            return cursor.rowcount > 0
    
    def has_unsynced_data(self) -> bool:
        """Check if there are any unsynced records."""
        with self.get_connection() as conn:
            cursor = conn.cursor()
            cursor.execute("SELECT 1 FROM parking_log WHERE synced_to_server = 0 LIMIT 1")
            return cursor.fetchone() is not None
    
    def get_vehicles_inside(self, search_query: Optional[str] = None) -> List[Dict[str, Any]]:
        """Get all vehicles currently inside with optional search."""
        with self.get_connection() as conn:
            cursor = conn.cursor()
            
            if search_query:
                cursor.execute("""
                    SELECT id, plate, time_in, image_path_in 
                    FROM parking_log 
                    WHERE status = ? AND plate LIKE ? 
                    ORDER BY time_in DESC
                """, (STATUS_INSIDE, f"%{search_query}%"))
            else:
                cursor.execute("""
                    SELECT id, plate, time_in, image_path_in 
                    FROM parking_log 
                    WHERE status = ? 
                    ORDER BY time_in DESC
                """, (STATUS_INSIDE,))
            
            results = []
            for row in cursor.fetchall():
                from datetime import datetime
                dt_obj = datetime.strptime(row["time_in"], "%Y-%m-%d %H:%M:%S")
                results.append({
                    'db_id': row['id'],
                    'plate': row['plate'],
                    'dt': dt_obj,
                    'time_str': dt_obj.strftime('%d-%m-%Y %H:%M:%S'),
                    'type': 'IN',
                    'raw': row['image_path_in'],
                    'crop': None
                })
            return results
    
    def close_connections(self):
        """Close all thread-local connections."""
        if hasattr(self._local, 'connection') and self._local.connection:
            self._local.connection.close()
            self._local.connection = None
