#!/bin/bash

# Tổng hợp tất cả các chức năng quản lý hệ thống

show_help() {
    echo "🚗 Parking System Control"
    echo "========================"
    echo "Usage: $0 [command]"
    echo ""
    echo "Commands:"
    echo "  start     - Start the parking system"
    echo "  stop      - Stop the parking system"
    echo "  status    - Show system status"
    echo "  url       - Get web interface URLs"
    echo "  test      - Test network connectivity"
    echo "  help      - Show this help"
    echo ""
}

case "$1" in
    start)
        ./start.sh
        ;;
    stop)
        ./stop.sh
        ;;
    status)
        ./status.sh
        ;;
    url)
        ./get_url.sh
        ;;
    test)
        ./network_test.sh
        ;;
    help|--help|-h|"")
        show_help
        ;;
    *)
        echo "❌ Unknown command: $1"
        show_help
        exit 1
        ;;
esac
