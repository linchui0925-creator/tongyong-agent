#!/usr/bin/env bash
# 启动 TongYong Agent 后端 (FastAPI @ 8000) + 前端 (Vite @ 5173)
# 双服务后台 daemon 化，不受当前 shell 退出影响
# 用法：bash scripts/dev-up.sh   /   bash scripts/dev-down.sh   /   bash scripts/dev-status.sh

set -euo pipefail

ROOT="/Users/linc/Documents/tongyong-agent"
LOG_DIR="$ROOT/data/logs"
BACKEND_LOG="$LOG_DIR/backend.log"
FRONTEND_LOG="$LOG_DIR/frontend.log"
BACKEND_PID="$LOG_DIR/backend.pid"
FRONTEND_PID="$LOG_DIR/frontend.pid"

mkdir -p "$LOG_DIR"

is_running() {
  local pidfile="$1"
  [[ -f "$pidfile" ]] && kill -0 "$(cat "$pidfile")" 2>/dev/null
}

start_one() {
  local name="$1" workdir="$2" cmd="$3" logfile="$4" pidfile="$5"
  if is_running "$pidfile"; then
    echo "[$name] already running (pid $(cat "$pidfile"))"
    return
  fi
  echo "[$name] starting in $workdir"
  ( cd "$workdir" && nohup bash -c "$cmd" >"$logfile" 2>&1 </dev/null & echo $! >"$pidfile" ) >/dev/null
  sleep 2
  if is_running "$pidfile"; then
    echo "[$name] started (pid $(cat "$pidfile"), log $logfile)"
  else
    echo "[$name] FAILED to start, see $logfile"
    tail -20 "$logfile" || true
    return 1
  fi
}

start_one "backend"  "$ROOT/backend"  "/Users/linc/Documents/tongyong-agent/backend/.venv/bin/python -m uvicorn app.main:app --host 127.0.0.1 --port 8000" "$BACKEND_LOG"  "$BACKEND_PID"
start_one "frontend" "$ROOT/frontend" "/Users/linc/Documents/tongyong-agent/frontend/node_modules/.bin/vite --host 127.0.0.1 --port 5173" "$FRONTEND_LOG" "$FRONTEND_PID"

echo
echo "Backend:  http://127.0.0.1:8000   (logs: $BACKEND_LOG)"
echo "Frontend: http://127.0.0.1:5173   (logs: $FRONTEND_LOG)"
