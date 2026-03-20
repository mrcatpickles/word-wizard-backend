#!/usr/bin/env bash
# 根目录入口：全栈开发（不依赖 start-dev.sh 的可执行位）
# 只跑后端: cd backend && ./run_dev.sh
set -e
ROOT="$(cd "$(dirname "$0")" && pwd)"
exec bash "$ROOT/start-dev.sh" "$@"
