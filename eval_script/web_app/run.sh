#!/bin/bash
# Repo Reconstruction Evaluation V2 - 启动脚本

set -e

SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
cd "$SCRIPT_DIR"

# 颜色定义
RED='\033[0;31m'
GREEN='\033[0;32m'
YELLOW='\033[1;33m'
BLUE='\033[0;34m'
NC='\033[0m' # No Color

echo -e "${BLUE}"
echo "╔══════════════════════════════════════════════════════════════╗"
echo "║     Repo Reconstruction Evaluation V2                        ║"
echo "╚══════════════════════════════════════════════════════════════╝"
echo -e "${NC}"

# 显示帮助信息
show_help() {
    echo "用法: $0 [命令]"
    echo ""
    echo "可用命令:"
    echo "  web         启动 Flask Web 服务 (默认)"
    echo "  demo        在浏览器中打开独立演示页面"
    echo "  users       列出所有用户"
    echo "  snapshots   列出指定用户的快照 (需要 --user-id 参数)"
    echo "  compare     执行版本对比 (需要多个参数)"
    echo "  help        显示此帮助信息"
    echo ""
    echo "示例:"
    echo "  $0 web                                    # 启动 Web 服务"
    echo "  $0 demo                                   # 打开演示页面"
    echo "  $0 users                                  # 列出用户"
    echo "  $0 snapshots --user-id <uuid>            # 列出快照"
    echo ""
}

# 检查 Python 环境
check_python() {
    if ! command -v python3 &> /dev/null; then
        echo -e "${RED}错误: 未找到 python3${NC}"
        exit 1
    fi
    echo -e "${GREEN}✓${NC} Python3: $(python3 --version)"
}

# 检查依赖
check_deps() {
    echo -e "${YELLOW}检查依赖...${NC}"
    python3 -c "import flask" 2>/dev/null || {
        echo -e "${YELLOW}正在安装依赖...${NC}"
        pip install -r requirements.txt
    }
    echo -e "${GREEN}✓${NC} 依赖已就绪"
}

# 启动 Web 服务
start_web() {
    check_python
    check_deps
    echo ""
    echo -e "${GREEN}启动 Web 服务...${NC}"
    echo -e "访问地址: ${BLUE}http://localhost:5000${NC}"
    echo ""
    python3 app.py
}

# 打开演示页面
open_demo() {
    DEMO_FILE="$SCRIPT_DIR/standalone.html"
    if [ ! -f "$DEMO_FILE" ]; then
        echo -e "${RED}错误: 演示文件不存在: $DEMO_FILE${NC}"
        exit 1
    fi
    
    echo -e "${GREEN}打开演示页面...${NC}"
    echo -e "文件路径: ${BLUE}$DEMO_FILE${NC}"
    
    # 尝试不同的浏览器
    if command -v xdg-open &> /dev/null; then
        xdg-open "$DEMO_FILE"
    elif command -v firefox &> /dev/null; then
        firefox "$DEMO_FILE" &
    elif command -v google-chrome &> /dev/null; then
        google-chrome "$DEMO_FILE" &
    else
        echo -e "${YELLOW}请手动在浏览器中打开: $DEMO_FILE${NC}"
    fi
}

# 列出用户
list_users() {
    check_python
    python3 data_manager.py list-users
}

# 列出快照
list_snapshots() {
    check_python
    shift
    python3 data_manager.py list-snapshots "$@"
}

# 执行对比
run_compare() {
    check_python
    shift
    python3 data_manager.py compare "$@"
}

# 主入口
case "${1:-web}" in
    web)
        start_web
        ;;
    demo)
        open_demo
        ;;
    users)
        list_users
        ;;
    snapshots)
        list_snapshots "$@"
        ;;
    compare)
        run_compare "$@"
        ;;
    help|--help|-h)
        show_help
        ;;
    *)
        echo -e "${RED}未知命令: $1${NC}"
        echo ""
        show_help
        exit 1
        ;;
esac
