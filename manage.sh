#!/bin/bash

# Main management script for the parking system

# Colors for output
RED='\033[0;31m'
GREEN='\033[0;32m'
YELLOW='\033[1;33m'
BLUE='\033[0;34m'
NC='\033[0m' # No Color

# Function to print colored output
print_color() {
    local color=$1
    local message=$2
    echo -e "${color}${message}${NC}"
}

# Function to show usage
show_usage() {
    echo "🚗 Parking System Management Tool"
    echo "================================="
    echo ""
    echo "Usage: $0 {start|stop|restart|status|logs|help}"
    echo ""
    echo "Commands:"
    echo "  start    - Start the parking system services"
    echo "  stop     - Stop all parking system services"
    echo "  restart  - Restart the parking system"
    echo "  status   - Show system status"
    echo "  logs     - Show recent logs"
    echo "  help     - Show this help message"
    echo ""
    echo "Examples:"
    echo "  $0 start          # Start the system"
    echo "  $0 status         # Check what's running"
    echo "  $0 logs           # View recent activity"
    echo ""
}

# Function to start services
start_services() {
    print_color $BLUE "🚀 Starting parking system..."
    
    # Check if already running
    if pgrep -f "LPR\.py\|app\.py" > /dev/null; then
        print_color $YELLOW "⚠️  Some services are already running. Use 'restart' to restart them."
        ./status.sh
        return 1
    fi
    
    # Start the system
    print_color $GREEN "🔧 Launching services..."
    ./start.sh
}

# Function to stop services
stop_services() {
    print_color $BLUE "🛑 Stopping parking system..."
    ./stop.sh
    print_color $GREEN "✅ Services stopped"
}

# Function to restart services
restart_services() {
    print_color $BLUE "🔄 Restarting parking system..."
    stop_services
    sleep 2
    start_services
}

# Function to show status
show_status() {
    ./status.sh
}

# Function to show logs
show_logs() {
    print_color $BLUE "📋 Recent System Logs"
    echo "===================="
    
    # Show Flask logs if available
    if [ -f "flask_app.log" ]; then
        print_color $GREEN "🌐 Flask App Logs (last 20 lines):"
        echo "-----------------------------------"
        tail -20 flask_app.log
        echo ""
    fi
    
    # Show error logs if available
    if [ -f "error_log.txt" ]; then
        print_color $YELLOW "🔥 Error Logs (last 10 lines):"
        echo "------------------------------"
        tail -10 error_log.txt
        echo ""
    fi
    
    # Show system status
    print_color $BLUE "📊 Current Status:"
    echo "------------------"
    ./status.sh | grep -E "(RUNNING|NOT RUNNING|OPEN|CLOSED)"
}

# Main script logic
case "${1:-help}" in
    start)
        start_services
        ;;
    stop)
        stop_services
        ;;
    restart)
        restart_services
        ;;
    status)
        show_status
        ;;
    logs)
        show_logs
        ;;
    help|--help|-h)
        show_usage
        ;;
    *)
        print_color $RED "❌ Unknown command: $1"
        echo ""
        show_usage
        exit 1
        ;;
esac
