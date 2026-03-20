#!/usr/bin/env bash
# 后端后台常驻 8002；只以前台跑前端。Ctrl+C 只停前端，不会关掉后端。
set -e
ROOT="$(cd "$(dirname "$0")" && pwd)"
PIDFILE="$ROOT/.backend-dev.pid"
LOG="$ROOT/.backend-dev.log"

if curl -sf "http://127.0.0.1:8002/" >/dev/null 2>&1; then
  echo "✓ 后端已在 http://127.0.0.1:8002"
else
  echo "→ 后台启动后端（日志: $LOG）"
  cd "$ROOT/backend"
  nohup python -m uvicorn main:app --reload --host 127.0.0.1 --port 8002 >>"$LOG" 2>&1 &
  echo $! >"$PIDFILE"
  sleep 2
  if curl -sf "http://127.0.0.1:8002/" >/dev/null 2>&1; then
    echo "✓ 后端就绪 PID $(cat "$PIDFILE")"
  else
    echo "✗ 启动失败，执行: tail -80 \"$LOG\""
    exit 1
  fi
fi

echo ""
echo "→ 前端（Ctrl+C 只关页面服务，后端 8002 继续跑）"
echo "  停后端: npm run stop:api"
echo ""
cd "$ROOT/frontend"
exec npm run dev
