#!/usr/bin/env bash

set -uo pipefail

SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
BACKEND_PID=""
FRONTEND_PID=""

cleanup() {
  trap - EXIT INT TERM

  if [[ -n "${BACKEND_PID}" ]] && kill -0 "${BACKEND_PID}" 2>/dev/null; then
    kill "${BACKEND_PID}" 2>/dev/null || true
  fi
  if [[ -n "${FRONTEND_PID}" ]] && kill -0 "${FRONTEND_PID}" 2>/dev/null; then
    kill "${FRONTEND_PID}" 2>/dev/null || true
  fi

  [[ -n "${BACKEND_PID}" ]] && wait "${BACKEND_PID}" 2>/dev/null || true
  [[ -n "${FRONTEND_PID}" ]] && wait "${FRONTEND_PID}" 2>/dev/null || true
  echo "[qa-platform] 前后端已停止。"
}

trap cleanup EXIT INT TERM

"${SCRIPT_DIR}/start-backend.sh" &
BACKEND_PID=$!
"${SCRIPT_DIR}/start-frontend.sh" &
FRONTEND_PID=$!

echo "[qa-platform] 开发环境已启动，按 Ctrl+C 同时停止前后端。"
echo "[qa-platform] Web UI: http://${FRONTEND_HOST:-127.0.0.1}:${FRONTEND_PORT:-5173}"
echo "[qa-platform] OpenAPI: http://${BACKEND_HOST:-127.0.0.1}:${BACKEND_PORT:-8000}/docs"

while kill -0 "${BACKEND_PID}" 2>/dev/null && kill -0 "${FRONTEND_PID}" 2>/dev/null; do
  sleep 1
done

if ! kill -0 "${BACKEND_PID}" 2>/dev/null; then
  wait "${BACKEND_PID}"
  STATUS=$?
  echo "[qa-platform] 后端进程已退出（状态码 ${STATUS}）。" >&2
else
  wait "${FRONTEND_PID}"
  STATUS=$?
  echo "[qa-platform] 前端进程已退出（状态码 ${STATUS}）。" >&2
fi

exit "${STATUS}"
