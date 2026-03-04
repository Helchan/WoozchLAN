#!/bin/bash
set -euo pipefail

ROOT_DIR="$(cd "$(dirname "$0")" && pwd)"
cd "$ROOT_DIR"

PROFILE="${1-}"
if [[ -n "$PROFILE" ]]; then
  export GOMOKU_LAN_DATA_DIR="$HOME/.gomoku_lan_profiles/$PROFILE"
  mkdir -p "$GOMOKU_LAN_DATA_DIR"
fi

PY=""
if command -v python3.12 >/dev/null 2>&1; then
  PY="python3.12"
elif command -v python3 >/dev/null 2>&1; then
  PY="python3"
elif command -v python >/dev/null 2>&1; then
  PY="python"
else
  echo "找不到 Python。请安装 Python 3.12 并确保命令行可用。"
  read -r
  exit 1
fi

if ! "$PY" -c "import tkinter" >/dev/null 2>&1; then
  echo "你的 Python 缺少 Tk 支持（_tkinter）。请安装带 Tk 的 Python。"
  read -r
  exit 1
fi

exec "$PY" main.py

