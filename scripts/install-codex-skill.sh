#!/usr/bin/env bash
set -euo pipefail

usage() {
  cat <<'EOF'
Usage: ./scripts/install-codex-skill.sh [--target <directory>] [--force]

Install qa-platform's bundled Codex Skill into the user-level Skill directory.
Existing targets are preserved as a timestamped backup; replacing one requires --force.
EOF
}

repo_root=$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)
source_dir="$repo_root/integrations/codex/qa-platform-skill"
target_dir="${CODEX_HOME:-$HOME/.codex}/skills/qa-platform-skill"
force=false

while (($#)); do
  case "$1" in
    --target)
      (($# >= 2)) || { echo "--target requires a directory" >&2; exit 2; }
      target_dir="$2"
      shift 2
      ;;
    --force)
      force=true
      shift
      ;;
    -h|--help)
      usage
      exit 0
      ;;
    *)
      echo "Unknown option: $1" >&2
      usage >&2
      exit 2
      ;;
  esac
done

if [[ ! -f "$source_dir/SKILL.md" ]]; then
  echo "Bundled Skill is missing: $source_dir/SKILL.md" >&2
  exit 1
fi
if ! command -v rsync >/dev/null 2>&1; then
  echo "rsync is required to install the bundled Skill" >&2
  exit 1
fi

target_parent=$(dirname "$target_dir")
mkdir -p "$target_parent"
staging_dir=$(mktemp -d "$target_parent/.qa-platform-skill.XXXXXX")
cleanup() {
  if [[ -d "$staging_dir" ]]; then
    rm -rf "$staging_dir"
  fi
}
trap cleanup EXIT

rsync -a --delete \
  --exclude '.git' \
  --exclude '.ruff_cache' \
  --exclude '__pycache__' \
  --exclude '*.pyc' \
  "$source_dir/" "$staging_dir/"

if [[ -e "$target_dir" ]]; then
  if [[ "$force" != true ]]; then
    echo "Target already exists: $target_dir" >&2
    echo "Re-run with --force to preserve it as a timestamped backup before replacement." >&2
    exit 1
  fi
  backup_dir="${target_dir}.backup-$(date +%Y%m%d%H%M%S)"
  mv "$target_dir" "$backup_dir"
  echo "Existing Skill backed up to: $backup_dir"
fi

mv "$staging_dir" "$target_dir"
echo "Installed qa-platform-skill to: $target_dir"
