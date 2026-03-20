#!/usr/bin/env bash
ROOT="$(cd "$(dirname "$0")" && pwd)"
PIDFILE="$ROOT/.backend-dev.pid"
if [[ -f "$PIDFILE" ]]; then
  kill "$(cat "$PIDFILE")" 2>/dev/null || true
  rm -f "$PIDFILE"
  echo "已停止由 start-dev 记录的后端进程。"
fi
# 清掉仍占 8002 的 uvicorn（含 reload 子进程）
if command -v lsof >/dev/null 2>&1; then
  PIDS=$(lsof -ti :8002 2>/dev/null || true)
  if [[ -n "$PIDS" ]]; then
    kill -9 $PIDS 2>/dev/null || true
    echo "已释放端口 8002。"
  fi
else
  echo "未安装 lsof 时请手动结束占用 8002 的进程。"
fi
