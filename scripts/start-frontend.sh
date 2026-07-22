#!/usr/bin/env bash

set -euo pipefail

SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
ROOT_DIR="$(cd "${SCRIPT_DIR}/.." && pwd)"
FRONTEND_DIR="${ROOT_DIR}/frontend"

if ! command -v npm >/dev/null 2>&1; then
  echo "[qa-platform] 未找到 npm，请先安装 Node.js 20+。" >&2
  exit 1
fi

if [[ ! -d "${FRONTEND_DIR}/node_modules" ]]; then
  echo "[qa-platform] 前端依赖尚未安装。" >&2
  echo "请先执行：cd ${FRONTEND_DIR} && npm install" >&2
  exit 1
fi

FRONTEND_HOST="${FRONTEND_HOST:-127.0.0.1}"
FRONTEND_PORT="${FRONTEND_PORT:-7173}"

echo "[qa-platform] 启动前端：http://${FRONTEND_HOST}:${FRONTEND_PORT}"
cd "${FRONTEND_DIR}"
exec npm run dev -- \
  --host "${FRONTEND_HOST}" \
  --port "${FRONTEND_PORT}" \
  --strictPort \
  "$@"
