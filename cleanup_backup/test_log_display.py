#!/usr/bin/env python3

import sqlite3
import sys
from datetime import datetime

def test_log_display():
    """Test the new log display logic with actual database data"""
    
    print("🧪 Testing Log Display Logic")
    print("=" * 40)
    
    try:
        conn = sqlite3.connect('parking_data.db', timeout=5.0)
        conn.row_factory = sqlite3.Row
        cursor = conn.cursor()
        
        # Get all records
        cursor.execute("SELECT * FROM parking_log ORDER BY id DESC LIMIT 10")
        rows = cursor.fetchall()
        
        print(f"📊 Found {len(rows)} database records")
        print()
        
        # Process each record like the web interface does
        all_events = []
        for row in rows:
            print(f"Processing Record ID {row['id']}:")
            print(f"  Plate: {row['plate']}")
            print(f"  Time In: {row['time_in']}")
            print(f"  Time Out: {row['time_out']}")
            print(f"  Status: {row['status']}")
            
            # Apply the same logic as the web interface
            if row['time_out'] and row['status'] == 1:  # STATUS_COMPLETED = 1
                # Add OUT event
                out_dt = datetime.strptime(row['time_out'], "%Y-%m-%d %H:%M:%S")
                all_events.append({
                    'dt': out_dt,
                    'time_str': out_dt.strftime('%d-%m-%Y %H:%M:%S'),
                    'plate': row['plate'],
                    'type': "OUT",
                    'db_id': row['id']
                })
                print(f"  ✅ Created OUT event: {out_dt.strftime('%d-%m-%Y %H:%M:%S')}")
                
                # Add IN event
                in_dt = datetime.strptime(row['time_in'], "%Y-%m-%d %H:%M:%S")
                all_events.append({
                    'dt': in_dt,
                    'time_str': in_dt.strftime('%d-%m-%Y %H:%M:%S'),
                    'plate': row['plate'],
                    'type': "IN",
                    'db_id': row['id']
                })
                print(f"  ✅ Created IN event: {in_dt.strftime('%d-%m-%Y %H:%M:%S')}")
            else:
                # Only IN event
                time_str = row['time_in']
                dt_obj = datetime.strptime(time_str, "%Y-%m-%d %H:%M:%S")
                
                event_type = "IN"
                if row['status'] == 2:  # STATUS_INVALID = 2
                    event_type = "INVALID"
                
                all_events.append({
                    'dt': dt_obj,
                    'time_str': dt_obj.strftime('%d-%m-%Y %H:%M:%S'),
                    'plate': row['plate'],
                    'type': event_type,
                    'db_id': row['id']
                })
                print(f"  ✅ Created {event_type} event: {dt_obj.strftime('%d-%m-%Y %H:%M:%S')}")
            
            print()
        
        # Sort events by time (newest first)
        all_events.sort(key=lambda x: x['dt'], reverse=True)
        
        print("📋 Final Event List (sorted by time):")
        print("-" * 60)
        for i, event in enumerate(all_events, 1):
            print(f"{i:2d}. {event['time_str']} | {event['plate']:15} | {event['type']:7} | DB ID: {event['db_id']}")
        
        print()
        print(f"📊 Summary:")
        print(f"  Total events to display: {len(all_events)}")
        print(f"  IN events: {len([e for e in all_events if e['type'] == 'IN'])}")
        print(f"  OUT events: {len([e for e in all_events if e['type'] == 'OUT'])}")
        print(f"  INVALID events: {len([e for e in all_events if e['type'] == 'INVALID'])}")
        
        conn.close()
        
    except Exception as e:
        print(f"❌ Error: {e}")
        sys.exit(1)

if __name__ == "__main__":
    test_log_display()
