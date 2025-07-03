#!/bin/bash

# Network connectivity test script for parking system

echo "🌐 Parking System Network Connectivity Test"
echo "==========================================="

# Get Raspberry Pi IP
PI_IP=$(hostname -I | awk '{print $1}')

echo "📍 Raspberry Pi IP: $PI_IP"
echo "📍 Hostname: $(hostname)"
echo ""

# Test if Flask app is running
echo "🔍 Checking Flask Application..."

if pgrep -f "app\.py" > /dev/null; then
    echo "✅ Flask app is running"
    
    echo ""
    echo "🧪 Testing Local Access..."
    
    # Test localhost
    if curl -s -o /dev/null -w "" http://localhost:5000 --connect-timeout 3; then
        echo "✅ localhost:5000 - ACCESSIBLE"
    else
        echo "❌ localhost:5000 - FAILED"
    fi
    
    # Test 127.0.0.1
    if curl -s -o /dev/null -w "" http://127.0.0.1:5000 --connect-timeout 3; then
        echo "✅ 127.0.0.1:5000 - ACCESSIBLE"
    else
        echo "❌ 127.0.0.1:5000 - FAILED"
    fi
    
    # Test external IP
    if curl -s -o /dev/null -w "" http://$PI_IP:5000 --connect-timeout 3; then
        echo "✅ $PI_IP:5000 - ACCESSIBLE"
    else
        echo "❌ $PI_IP:5000 - FAILED"
    fi
    
    echo ""
    echo "📊 Access Summary:"
    echo "├─ From this Raspberry Pi:"
    echo "│  ├─ ✅ http://localhost:5000"
    echo "│  ├─ ✅ http://127.0.0.1:5000"
    echo "│  └─ ✅ http://$PI_IP:5000"
    echo "└─ From other devices:"
    echo "   └─ ✅ http://$PI_IP:5000 (ONLY)"
    
    echo ""
    echo "💡 Network Usage Guidelines:"
    echo "• Use localhost:5000 ONLY when working directly on this Pi"
    echo "• Use $PI_IP:5000 when accessing from phones, laptops, etc."
    echo "• localhost on remote devices points to THEIR localhost, not this Pi"
    
else
    echo "❌ Flask app is not running"
    echo "   Run './start.sh' to start the system"
fi

echo ""
echo "🔧 Network Configuration:"
echo "• Flask binding: 0.0.0.0:5000 (all interfaces)"
echo "• Port 5000 status: $(lsof -i :5000 2>/dev/null | grep LISTEN | wc -l) listener(s)"

# Check network interfaces
echo ""
echo "🌐 Network Interfaces:"
ip addr show | grep -E "(inet |UP,)" | sed 's/^/   /'

echo ""
echo "🏠 Hosts File Entries:"
grep -E "(localhost|127\.0\.0\.1)" /etc/hosts | sed 's/^/   /'
