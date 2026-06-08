#!/usr/bin/env bash
# 查看 dev-up.sh 启动的进程 + 端口 + 健康检查
set -u

ROOT="/Users/linc/Documents/tongyong-agent"
LOG_DIR="$ROOT/data/logs"
BACKEND_PID="$LOG_DIR/backend.pid"
FRONTEND_PID="$LOG_DIR/frontend.pid"

check_one() {
  local name="$1" pidfile="$2" port="$3" path="$4"
  if [[ -f "$pidfile" ]] && kill -0 "$(cat "$pidfile")" 2>/dev/null; then
    local code
    code=$(curl -sS -o /dev/null -w "%{http_code}" --max-time 3 "http://127.0.0.1:$port$path" 2>/dev/null || echo "000")
    printf "  %-9s pid=%-6s port=%-5s http=%s\n" "$name" "$(cat "$pidfile")" "$port" "$code"
  else
    printf "  %-9s DOWN  (no pidfile or dead)\n" "$name"
  fi
}

echo "TongYong Agent status:"
check_one "backend"  "$BACKEND_PID"  8000 "/health"
check_one "frontend" "$FRONTEND_PID" 5173 "/"

echo
echo "URLs:"
echo "  Backend:  http://127.0.0.1:8000  (Swagger: /docs)"
echo "  Frontend: http://127.0.0.1:5173"
