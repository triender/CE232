#!/bin/bash

# Script to check status of parking system services

echo "📊 Parking System Service Status"
echo "================================"

# Function to check if process is running
check_process() {
    local process_name="$1"
    local friendly_name="$2"
    local pids=$(pgrep -f "$process_name" 2>/dev/null || true)
    
    if [ ! -z "$pids" ]; then
        echo "✅ $friendly_name: RUNNING (PIDs: $pids)"
        for pid in $pids; do
            local start_time=$(ps -o lstart= -p "$pid" 2>/dev/null || echo "Unknown")
            local mem_usage=$(ps -o rss= -p "$pid" 2>/dev/null || echo "Unknown")
            echo "   └─ PID $pid: Started $start_time, Memory: ${mem_usage}KB"
        done
    else
        echo "❌ $friendly_name: NOT RUNNING"
    fi
}

# Function to check port
check_port() {
    local port="$1"
    local service_name="$2"
    
    if netstat -ln 2>/dev/null | grep -q ":$port "; then
        echo "✅ Port $port ($service_name): OPEN"
    else
        echo "❌ Port $port ($service_name): CLOSED"
    fi
}

# Check main services
check_process "LPR\.py" "Main Parking System (LPR.py)"
check_process "app\.py" "Web Interface (Flask)"

echo ""
echo "🌐 Network Status"
echo "----------------"
check_port "5000" "Flask Web Interface"

echo ""
echo "📁 File Status"
echo "-------------"

# Check important files
files_to_check=(
    "parking_data.db:Database"
    "flask_app.log:Flask Logs"
    "error_log.txt:Error Logs"
    "tmp/live_view.jpg:Live Camera Feed"
)

for file_info in "${files_to_check[@]}"; do
    IFS=':' read -r file_path file_desc <<< "$file_info"
    if [ -f "$file_path" ]; then
        file_size=$(du -h "$file_path" 2>/dev/null | cut -f1)
        file_mtime=$(stat -c %y "$file_path" 2>/dev/null | cut -d'.' -f1)
        echo "✅ $file_desc: EXISTS ($file_size, modified: $file_mtime)"
    else
        echo "❌ $file_desc: NOT FOUND ($file_path)"
    fi
done

echo ""
echo "💾 Database Status"
echo "-----------------"

if [ -f "parking_data.db" ]; then
    # Try to connect to database and get basic stats
    python3 -c "
import sqlite3
try:
    conn = sqlite3.connect('parking_data.db', timeout=5.0)
    cursor = conn.cursor()
    
    # Get total records
    cursor.execute('SELECT COUNT(*) FROM parking_log')
    total_records = cursor.fetchone()[0]
    
    # Get vehicles inside
    cursor.execute('SELECT COUNT(*) FROM parking_log WHERE status = 0')
    vehicles_inside = cursor.fetchone()[0]
    
    # Get unsynced records
    cursor.execute('SELECT COUNT(*) FROM parking_log WHERE synced_to_server = 0')
    unsynced = cursor.fetchone()[0]
    
    print(f'✅ Database accessible')
    print(f'   └─ Total records: {total_records}')
    print(f'   └─ Vehicles inside: {vehicles_inside}')
    print(f'   └─ Unsynced records: {unsynced}')
    
    conn.close()
except Exception as e:
    print(f'❌ Database error: {e}')
" 2>/dev/null || echo "❌ Cannot access database"
else
    echo "❌ Database file not found"
fi

echo ""
echo "🔧 System Resources"
echo "------------------"

# Memory usage
total_mem=$(free -h | awk '/^Mem:/ {print $2}')
used_mem=$(free -h | awk '/^Mem:/ {print $3}')
echo "💾 Memory: $used_mem / $total_mem used"

# Disk usage for current directory
disk_usage=$(df -h . | awk 'NR==2 {print $3 " / " $2 " used (" $5 ")"}')
echo "💿 Disk: $disk_usage"

# System uptime
uptime_info=$(uptime | awk -F'up ' '{print $2}' | awk -F',' '{print $1}')
echo "⏰ System uptime: $uptime_info"

# Get IP for remote access display
PI_IP=$(hostname -I | awk '{print $1}')

echo ""
echo "📋 Quick Actions"
echo "---------------"
echo "• Start system: ./start.sh"
echo "• Stop system:  ./stop.sh"
echo "• View logs:    tail -f flask_app.log"
echo "• Web interface (local):  http://localhost:5000"
echo "• Web interface (remote): http://$PI_IP:5000"
