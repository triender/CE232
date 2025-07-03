#!/usr/bin/env python3
"""
Database Migration Script
Migrates existing parking_data.db to new schema with updated_at column
"""

import sqlite3
import os
import shutil
from datetime import datetime

def backup_database(db_path):
    """Create backup of existing database"""
    backup_path = f"{db_path}.backup_{datetime.now().strftime('%Y%m%d_%H%M%S')}"
    try:
        shutil.copy2(db_path, backup_path)
        print(f"✓ Database backed up to: {backup_path}")
        return backup_path
    except Exception as e:
        print(f"✗ Failed to backup database: {e}")
        return None

def check_column_exists(cursor, table_name, column_name):
    """Check if column exists in table"""
    cursor.execute(f"PRAGMA table_info({table_name})")
    columns = [row[1] for row in cursor.fetchall()]
    return column_name in columns

def migrate_database(db_path):
    """Migrate database to new schema"""
    if not os.path.exists(db_path):
        print(f"✗ Database file not found: {db_path}")
        return False
    
    # Backup database first
    backup_path = backup_database(db_path)
    if not backup_path:
        return False
    
    try:
        conn = sqlite3.connect(db_path)
        cursor = conn.cursor()
        
        # Check if updated_at column already exists
        if check_column_exists(cursor, 'parking_log', 'updated_at'):
            print("✓ Column 'updated_at' already exists")
            conn.close()
            return True
        
        print("📝 Adding 'updated_at' column to parking_log table...")
        
        # Add updated_at column with default value
        cursor.execute("""
            ALTER TABLE parking_log 
            ADD COLUMN updated_at TEXT DEFAULT (datetime('now'))
        """)
        
        # Update existing records to have updated_at = time_in initially
        cursor.execute("""
            UPDATE parking_log 
            SET updated_at = time_in 
            WHERE updated_at IS NULL
        """)
        
        # Drop existing trigger if it exists
        cursor.execute("DROP TRIGGER IF EXISTS update_parking_log_timestamp")
        
        # Create new trigger
        cursor.execute("""
            CREATE TRIGGER update_parking_log_timestamp 
            AFTER UPDATE ON parking_log
            FOR EACH ROW
            BEGIN
                UPDATE parking_log SET updated_at = datetime('now') WHERE id = NEW.id;
            END
        """)
        
        # Verify the migration
        cursor.execute("PRAGMA table_info(parking_log)")
        columns = [row[1] for row in cursor.fetchall()]
        
        if 'updated_at' in columns:
            print("✓ Migration completed successfully!")
            print(f"✓ Table columns: {', '.join(columns)}")
            
            # Test the trigger
            cursor.execute("SELECT COUNT(*) FROM parking_log")
            count = cursor.fetchone()[0]
            if count > 0:
                print(f"✓ Updated {count} existing records with updated_at timestamps")
            
            conn.commit()
            conn.close()
            return True
        else:
            print("✗ Migration failed - column not added")
            conn.rollback()
            conn.close()
            return False
            
    except Exception as e:
        print(f"✗ Migration failed: {e}")
        try:
            conn.rollback()
            conn.close()
        except:
            pass
        
        # Restore backup
        if backup_path and os.path.exists(backup_path):
            print(f"🔄 Restoring backup from {backup_path}")
            shutil.copy2(backup_path, db_path)
        
        return False

def verify_schema(db_path):
    """Verify the database schema after migration"""
    try:
        conn = sqlite3.connect(db_path)
        cursor = conn.cursor()
        
        print("\n📋 Current database schema:")
        cursor.execute("SELECT sql FROM sqlite_master WHERE type='table' AND name='parking_log'")
        table_schema = cursor.fetchone()
        if table_schema:
            print("Table schema:")
            print(table_schema[0])
        
        print("\nTriggers:")
        cursor.execute("SELECT sql FROM sqlite_master WHERE type='trigger' AND tbl_name='parking_log'")
        triggers = cursor.fetchall()
        for trigger in triggers:
            print(trigger[0])
        
        print("\nIndexes:")
        cursor.execute("SELECT sql FROM sqlite_master WHERE type='index' AND tbl_name='parking_log'")
        indexes = cursor.fetchall()
        for index in indexes:
            if index[0]:  # Skip auto-created indexes
                print(index[0])
        
        conn.close()
        return True
        
    except Exception as e:
        print(f"✗ Failed to verify schema: {e}")
        return False

def main():
    """Main migration function"""
    db_path = "parking_data.db"
    
    print("🔄 Starting database migration...")
    print(f"Database: {os.path.abspath(db_path)}")
    
    if migrate_database(db_path):
        print("\n✅ Migration completed successfully!")
        verify_schema(db_path)
        
        print("\n📝 Migration Summary:")
        print("- Added 'updated_at' column to parking_log table")
        print("- Updated existing records with timestamps")
        print("- Created trigger for automatic timestamp updates")
        print("- Database backup created")
        
    else:
        print("\n❌ Migration failed!")
        print("Please check the error messages above and try again.")
        return 1
    
    return 0

if __name__ == "__main__":
    exit(main())
