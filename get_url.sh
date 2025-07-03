#!/bin/bash

# Quick script to get the correct web interface URL

PI_IP=$(hostname -I | awk '{print $1}')

echo "🌐 Parking System Web Interface URLs"
echo "===================================="
echo ""
echo "📱 For Remote Access (phones, laptops, other computers):"
echo "   http://$PI_IP:5000"
echo ""
echo "💻 For Local Access (on this Raspberry Pi only):"
echo "   http://localhost:5000"
echo ""
echo "📋 Quick Copy Commands:"
echo "   echo 'http://$PI_IP:5000' | xclip -selection clipboard"
echo "   # Or manually copy: http://$PI_IP:5000"
echo ""

# Check if system is running
if pgrep -f "app\.py" > /dev/null; then
    echo "✅ System Status: RUNNING"
    echo "🚀 Ready to access the web interface!"
else
    echo "❌ System Status: NOT RUNNING"
    echo "💡 Run './start.sh' to start the system first"
fi
