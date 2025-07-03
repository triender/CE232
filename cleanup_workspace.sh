#!/bin/bash

# Script để dọn dẹp và tối ưu hóa workspace

echo "🧹 Dọn dẹp Workspace - Parking Management System"
echo "=============================================="

# Tạo thư mục lưu trữ file backup
mkdir -p cleanup_backup

echo "📁 Tạo backup cho các file quan trọng..."

# Backup các file quan trọng trước khi dọn dẹp
cp -r templates/ cleanup_backup/ 2>/dev/null || true
cp *.py cleanup_backup/ 2>/dev/null || true
cp *.sh cleanup_backup/ 2>/dev/null || true
cp *.md cleanup_backup/ 2>/dev/null || true

echo "🗂️ Gộp các file documentation..."

# Gộp các file MD thành một file duy nhất
cat > COMPLETE_DOCUMENTATION.md << 'EOF'
# Complete Parking System Documentation

## Table of Contents
1. [README](#readme)
2. [User Manual](#user-manual)
3. [Scripts Documentation](#scripts-documentation)
4. [Network Access Guide](#network-access-guide)
5. [Network Fix Summary](#network-fix-summary)

---

EOF

# Thêm nội dung từ các file MD
echo "## README" >> COMPLETE_DOCUMENTATION.md
cat README.md >> COMPLETE_DOCUMENTATION.md
echo -e "\n---\n" >> COMPLETE_DOCUMENTATION.md

echo "## User Manual" >> COMPLETE_DOCUMENTATION.md
cat USER_MANUAL.md >> COMPLETE_DOCUMENTATION.md
echo -e "\n---\n" >> COMPLETE_DOCUMENTATION.md

echo "## Scripts Documentation" >> COMPLETE_DOCUMENTATION.md
cat SCRIPTS_README.md >> COMPLETE_DOCUMENTATION.md
echo -e "\n---\n" >> COMPLETE_DOCUMENTATION.md

echo "## Network Access Guide" >> COMPLETE_DOCUMENTATION.md
cat NETWORK_ACCESS_GUIDE.md >> COMPLETE_DOCUMENTATION.md
echo -e "\n---\n" >> COMPLETE_DOCUMENTATION.md

echo "## Network Fix Summary" >> COMPLETE_DOCUMENTATION.md
cat NETWORK_FIX_SUMMARY.md >> COMPLETE_DOCUMENTATION.md

echo "🗑️ Xóa các file test và backup cũ..."

# Xóa các file test không cần thiết
rm -f test_*.py
rm -f quick_test.py
rm -f migrate_database.py
rm -f parking_data.db.backup_*

echo "📝 Xóa các file documentation riêng lẻ..."

# Xóa các file MD riêng lẻ (đã gộp vào COMPLETE_DOCUMENTATION.md)
rm -f NETWORK_ACCESS_GUIDE.md
rm -f NETWORK_FIX_SUMMARY.md
rm -f SCRIPTS_README.md
rm -f USER_MANUAL.md

echo "🔧 Gộp các script utility..."

# Tạo một script tổng hợp
cat > system_control.sh << 'EOF'
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
EOF

chmod +x system_control.sh

echo "✅ Dọn dẹp hoàn tất!"
echo ""
echo "📊 Tóm tắt thay đổi:"
echo "  ✅ Tạo backup trong cleanup_backup/"
echo "  ✅ Gộp tất cả documentation vào COMPLETE_DOCUMENTATION.md"
echo "  ✅ Tạo system_control.sh - script tổng hợp"
echo "  ✅ Xóa các file test và backup cũ"
echo "  ✅ Xóa các file documentation riêng lẻ"
echo ""
echo "🚀 Sử dụng: ./system_control.sh [start|stop|status|url|test|help]"
