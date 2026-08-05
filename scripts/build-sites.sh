#!/usr/bin/env bash

set -euo pipefail

SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
ROOT_DIR="$(cd "${SCRIPT_DIR}/.." && pwd)"

cd "${ROOT_DIR}/frontend"
npm run build

rm -rf "${ROOT_DIR}/dist"
mkdir -p "${ROOT_DIR}/dist/server"
cp -R "${ROOT_DIR}/frontend/dist/." "${ROOT_DIR}/dist/"
cp "${ROOT_DIR}/sites/worker/index.js" "${ROOT_DIR}/dist/server/index.js"

echo "[qa-platform] Sites build prepared in ${ROOT_DIR}/dist"
