#!/usr/bin/env bash

set -euo pipefail

SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
ROOT_DIR="$(cd "${SCRIPT_DIR}/.." && pwd)"
BACKEND_DIR="${ROOT_DIR}/backend"
UVICORN="${BACKEND_DIR}/.venv/bin/uvicorn"

if [[ ! -x "${UVICORN}" ]]; then
  echo "[qa-platform] 未找到后端虚拟环境或 uvicorn。" >&2
  echo "请先执行：" >&2
  echo "  cd ${BACKEND_DIR}" >&2
  echo "  python3 -m venv .venv" >&2
  echo "  .venv/bin/pip install -e '.[dev]'" >&2
  exit 1
fi

BACKEND_HOST="${BACKEND_HOST:-127.0.0.1}"
BACKEND_PORT="${BACKEND_PORT:-8000}"

echo "[qa-platform] 启动后端：http://${BACKEND_HOST}:${BACKEND_PORT}"
cd "${BACKEND_DIR}"
exec "${UVICORN}" app.main:app \
  --reload \
  --host "${BACKEND_HOST}" \
  --port "${BACKEND_PORT}" \
  "$@"
