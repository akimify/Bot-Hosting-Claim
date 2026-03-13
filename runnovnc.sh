#!/bin/bash

set -eu

# --- 1. 参数处理 ---
ACTION="${1:-start}" # 默认为 start

# 定义进程特征关键词用于清理
PROC_KEYWORDS="Xvnc|websockify|openbox|chromium"

if [ "$ACTION" == "stop" ]; then
    echo "🛑 正在停止所有相关服务..."
    # 查找并杀死包含关键词的进程
    PIDS=$(pgrep -f -d ' ' "$PROC_KEYWORDS") || true
    if [ -n "$PIDS" ]; then
        kill $PIDS && echo "✅ 已杀死进程: $PIDS"
    else
        echo " ℹ️ 没有发现正在运行的相关服务。"
    fi
    # 清理 VNC 锁文件，防止下次启动失败
    rm -f /tmp/.X*-lock /tmp/.X11-unix/X*
    exit 0
fi

# --- 2. 变量配置 ---
PORT="${CM_PORT:-${SERVER_PORT:-8080}}"
DISPLAY_NUM="${DISPLAY_NUM:-1}"  # 如果没有就取1
VNC_PORT=$((5900 + DISPLAY_NUM))
export DISPLAY=:${DISPLAY_NUM}

echo "🚀 启动远程桌面服务..."
echo "   访问地址: http://你的IP:${PORT}/"

# --- 3. 环境安装 ---
if ! command -v Xvnc &> /dev/null; then
    echo "📦 安装依赖..."
    apt update ; apt install -y \
        tigervnc-standalone-server openbox \
        websockify novnc wget net-tools
fi

# 清理旧锁
rm -f /tmp/.X${DISPLAY_NUM}-lock /tmp/.X11-unix/X${DISPLAY_NUM} || true

# --- 4. 启动 VNC ---
echo "启动 TigerVNC ${DISPLAY}..."
Xvnc ${DISPLAY} -geometry 1280x720 -depth 24 -SecurityTypes None -localhost no &

# 等待端口就绪
for i in {1..10}; do
    if netstat -tuln | grep -q ":${VNC_PORT} "; then break; fi
    sleep 1
done

# --- 5. 启动 桌面环境与浏览器 ---
echo "启动 Openbox 与 Chromium..."
openbox &
# 注意：在容器中运行 Chromium 必须加 --no-sandbox
chromium --no-sandbox --disable-dev-shm-usage --start-maximized --test-type &

# --- 6. 准备 noVNC (修复下载逻辑) ---
if [ -d "/usr/share/novnc" ]; then
    NOVNC_WEB_DIR="/usr/share/novnc"
else
    NOVNC_WEB_DIR="$(pwd)/novnc"
    if [ ! -f "${NOVNC_WEB_DIR}/vnc.html" ]; then
        echo "🌐 下载 noVNC 静态文件..."
        mkdir -p "${NOVNC_WEB_DIR}"
        wget -qO- https://github.com/novnc/noVNC/archive/refs/tags/v1.4.0.tar.gz | tar -xz -C "${NOVNC_WEB_DIR}" --strip-components=1
    fi
fi

# 确保 index.html 存在
if [ ! -f "${NOVNC_WEB_DIR}/index.html" ]; then
    ln -sf vnc.html "${NOVNC_WEB_DIR}/index.html"
fi

# --- 7. 启动 Websockify ---
echo "启动 websockify 监听端口 ${PORT}..."
nohup websockify --web "${NOVNC_WEB_DIR}" ${PORT} localhost:${VNC_PORT} > /dev/null 2>&1 &

echo "🎉 服务已全部启动！"
echo "使用说明: "
echo "  运行脚本: ./script.sh"
echo "  停止服务: ./script.sh stop"