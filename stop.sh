#!/bin/bash

# Script to safely stop all parking system services

echo "🛑 Stopping parking system services..."

# Function to kill processes by name
kill_by_name() {
    local process_name="$1"
    local pids=$(pgrep -f "$process_name" 2>/dev/null || true)
    
    if [ ! -z "$pids" ]; then
        echo "🔍 Found $process_name processes: $pids"
        for pid in $pids; do
            if kill -0 "$pid" 2>/dev/null; then
                echo "🛑 Stopping $process_name (PID: $pid)..."
                kill -TERM "$pid" 2>/dev/null || true
                sleep 1
                
                # Force kill if still running
                if kill -0 "$pid" 2>/dev/null; then
                    echo "🔪 Force killing $process_name (PID: $pid)..."
                    kill -KILL "$pid" 2>/dev/null || true
                fi
            fi
        done
    else
        echo "ℹ️  No $process_name processes found"
    fi
}

# Stop LPR.py processes
kill_by_name "LPR.py"

# Stop app.py (Flask) processes
kill_by_name "app.py"

# Kill any remaining processes on port 5000
echo "🔍 Cleaning up processes on port 5000..."
fuser -k -n tcp 5000 2>/dev/null || true

# Clean up any Python processes related to parking system
echo "🔍 Cleaning up related Python processes..."
pkill -f "python.*parking" 2>/dev/null || true
pkill -f "python.*LPR" 2>/dev/null || true
pkill -f "python.*app\.py" 2>/dev/null || true

# Wait a moment for cleanup
sleep 2

# Verify cleanup
remaining_procs=$(pgrep -f "LPR\.py\|app\.py" 2>/dev/null || true)
if [ ! -z "$remaining_procs" ]; then
    echo "⚠️  Warning: Some processes may still be running: $remaining_procs"
    echo "   You may need to manually kill them with: kill -9 $remaining_procs"
else
    echo "✅ All parking system services stopped successfully"
fi

# Clean up log files if they exist
if [ -f "flask_app.log" ]; then
    echo "🧹 Cleaning up flask_app.log"
    > flask_app.log  # Clear the log file instead of deleting it
fi

echo "👋 Parking system shutdown complete"
