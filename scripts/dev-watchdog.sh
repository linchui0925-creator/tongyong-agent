#!/usr/bin/env bash
# 前端 Vite 进程 watchdog — 兜住 "vite 静默退出" 那个 bug
# 每 30s 检查一次：pidfile 存在 + 端口监听中，两个条件都满足才算健康
# 任意一条不满足就杀掉残留、用 dev-up.sh 的脚本重新拉起
#
# 触发场景：node v24 + Vite5.4.21 在多次 HMR update 后会无错误退出，
#           日志最后一行只到 "ready"，pid 没了，端口空了。
#
# 用法：bash scripts/dev-watchdog.sh          # 前台跑，按 Ctrl+C 停
#       bash scripts/dev-watchdog.sh once     # 只跑一轮（调试/手动恢复）
#       bash scripts/dev-watchdog.sh status   # 看当前健康状态
#
# 不修改 dev-up.sh / dev-down.sh / dev-status.sh，纯粹外挂监控。

set -u

ROOT="/Users/linc/Documents/tongyong-agent"
LOG_DIR="$ROOT/data/logs"
FRONTEND_PID="$LOG_DIR/frontend.pid"
FRONTEND_LOG="$LOG_DIR/frontend.log"
WATCHDOG_LOG="$LOG_DIR/watchdog.log"

# W4-5 (2026-06-09): 加后端 watch — Hermes terminal(background=true) ~1.5h 后会
#   给 bg session 发 13s SIGTERM 干掉 uvicorn (无 Traceback, 干净退出),
#   表现为 :8000 ECONNREFUSED。 治法: watchdog 30s 轮询 :8000 端口,
#   掉了直接用 exec form 拉起 uvicorn (不走 dev-up.sh, 那条走 shell-level
#   nohup & 会被 Hermes 沙箱拒)。
BACKEND_PORT=8000
BACKEND_PID="$LOG_DIR/backend.pid"
BACKEND_CMD="cd \"$ROOT/backend\" && \"$ROOT/backend/.venv/bin/python\" -m uvicorn app.main:app --host 127.0.0.1 --port 8000"

MODE="${1:-loop}"

log() {
  local ts
  ts="$(date '+%Y-%m-%d %H:%M:%S')"
  echo "[$ts] $*" | tee -a "$WATCHDOG_LOG"
}

is_port_listening() {
  local port="$1"
  lsof -nP -iTCP:"$port" -sTCP:LISTEN -t >/dev/null 2>&1
}

pid_alive() {
  local pidfile="$1"
  [[ -f "$pidfile" ]] && kill -0 "$(cat "$pidfile")" 2>/dev/null
}

restart_frontend() {
  log "[watchdog] frontend 不健康，开始重启"
  # 清残留：清掉 pidfile、杀掉端口占用方
  rm -f "$FRONTEND_PID"
  pids=$(lsof -nP -iTCP:5173 -sTCP:LISTEN -t 2>/dev/null || true)
  if [[ -n "$pids" ]]; then
    log "[watchdog] 杀掉残留 5173 监听: $pids"
    kill -9 $pids 2>/dev/null || true
    sleep 1
  fi
  # 调 dev-up.sh 拉起（它会自己写新 pidfile）
  if bash "$ROOT/scripts/dev-up.sh" >>"$WATCHDOG_LOG" 2>&1; then
    log "[watchdog] dev-up.sh 退出 0"
  else
    log "[watchdog] dev-up.sh 退出非 0，查看 dev-up 输出见 $WATCHDOG_LOG"
  fi
}

# W4-5: 后端重启。 关键: 用 subshell + nohup + </dev/null 走完全独立 session,
#   摆脱 Hermes 父进程 13s SIGTERM 限制。 (macOS 没 setsid, nohup 是 portable 替代)
restart_backend() {
  log "[watchdog] backend 不健康 (:$BACKEND_PORT 无人监听)，开始重启"
  rm -f "$BACKEND_PID"
  pids=$(lsof -nP -iTCP:"$BACKEND_PORT" -sTCP:LISTEN -t 2>/dev/null || true)
  if [[ -n "$pids" ]]; then
    log "[watchdog] 杀掉残留 $BACKEND_PORT 监听: $pids"
    kill -9 $pids 2>/dev/null || true
    sleep 1
  fi
  # (subshell) 切断变量, nohup 忽略 SIGHUP, </dev/null 切断 stdin
  #   </dev/null 必不可少, 否则 Hermes 父进程 close stdin 会传信号
  ( nohup bash -c "$BACKEND_CMD" >>"$LOG_DIR/backend.log" 2>&1 </dev/null & )
  sleep 4
  # 拉起后新进程不在本 shell 的 job table, 用 lsof 找最新监听 pid
  local new_pid
  new_pid=$(lsof -nP -iTCP:"$BACKEND_PORT" -sTCP:LISTEN -t 2>/dev/null | head -1)
  if [[ -n "$new_pid" ]]; then
    echo "$new_pid" > "$BACKEND_PID"
    log "[watchdog] backend 重启成功 pid=$new_pid (:$BACKEND_PORT 已监听)"
  else
    log "[watchdog] backend 重启失败, 见 $LOG_DIR/backend.log"
  fi
}

check_once() {
  local healthy=true reason=""
  if ! pid_alive "$FRONTEND_PID"; then
    healthy=false
    reason="pidfile 不存在或 PID 已死"
  fi
  if ! is_port_listening 5173; then
    healthy=false
    reason="${reason:+$reason + }5173 端口无人监听"
  fi
  if $healthy; then
    log "[watchdog] frontend healthy (pid=$(cat "$FRONTEND_PID"), 5173 listening)"
  else
    log "[watchdog] frontend UNHEALTHY: $reason"
    restart_frontend
  fi

  # W4-5: 后端健康检查 — Hermes 父进程 13s SIGTERM 干掉 uvicorn 的兜底
  if ! is_port_listening "$BACKEND_PORT"; then
    log "[watchdog] backend UNHEALTHY: :$BACKEND_PORT 无人监听"
    restart_backend
  else
    log "[watchdog] backend healthy (:$BACKEND_PORT listening)"
  fi
}

case "$MODE" in
  status)
    pid_alive "$FRONTEND_PID" && echo "frontend pidfile: $(cat "$FRONTEND_PID") (alive)" || echo "frontend pidfile: down"
    is_port_listening 5173 && echo "frontend port 5173: listening" || echo "frontend port 5173: not listening"
    # W4-5
    pid_alive "$BACKEND_PID" && echo "backend  pidfile: $(cat "$BACKEND_PID") (alive)" || echo "backend  pidfile: down"
    is_port_listening "$BACKEND_PORT" && echo "backend  port $BACKEND_PORT: listening" || echo "backend  port $BACKEND_PORT: not listening"
    ;;
  once)
    check_once
    ;;
  loop|"")
    log "[watchdog] 启动，30s 一轮，Ctrl+C 停"
    while true; do
      check_once
      sleep 30
    done
    ;;
  *)
    echo "用法: $0 [loop|once|status]" >&2
    exit 1
    ;;
esac