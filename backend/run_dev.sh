#!/usr/bin/env bash
# 勿用裸「uvicorn main:app --reload」→ 默认 8000 易 Address already in use。
# 本脚本默认 8002，与 frontend Vite 代理一致。
cd "$(dirname "$0")"
export PORT="${PORT:-8002}"
echo "Backend → http://127.0.0.1:${PORT}  （另开终端占 8000 时请用本脚本或 --port 8002）"
exec python -m uvicorn main:app --reload --host 127.0.0.1 --port "${PORT}"
