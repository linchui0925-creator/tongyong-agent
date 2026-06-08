#!/usr/bin/env bash
# 停止 dev-up.sh 启动的后端 / 前端进程
set -u

ROOT="/Users/linc/Documents/tongyong-agent"
LOG_DIR="$ROOT/data/logs"
BACKEND_PID="$LOG_DIR/backend.pid"
FRONTEND_PID="$LOG_DIR/frontend.pid"

stop_one() {
  local name="$1" pidfile="$2"
  if [[ -f "$pidfile" ]]; then
    local pid
    pid="$(cat "$pidfile")"
    if kill -0 "$pid" 2>/dev/null; then
      echo "[$name] stopping pid $pid"
      kill "$pid" 2>/dev/null || true
      # 等 3 秒，没退就强杀
      for _ in 1 2 3 4 5 6; do
        kill -0 "$pid" 2>/dev/null || break
        sleep 0.5
      done
      if kill -0 "$pid" 2>/dev/null; then
        echo "[$name] force kill"
        kill -9 "$pid" 2>/dev/null || true
      fi
    fi
    rm -f "$pidfile"
  else
    echo "[$name] no pidfile, nothing to stop"
  fi
}

stop_one "backend"  "$BACKEND_PID"
stop_one "frontend" "$FRONTEND_PID"

# 兜底：清掉残留端口
for port in 8000 5173; do
  pids=$(lsof -nP -iTCP:"$port" -sTCP:LISTEN -t 2>/dev/null || true)
  if [[ -n "$pids" ]]; then
    echo "port $port: killing leftover $pids"
    kill -9 $pids 2>/dev/null || true
  fi
done

echo "stopped."
