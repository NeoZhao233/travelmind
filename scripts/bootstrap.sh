#!/usr/bin/env bash
set -euo pipefail

project_dir="$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)"
cd "$project_dir"

export UV_CACHE_DIR="${UV_CACHE_DIR:-/private/tmp/travelmind-uv-cache}"
travelmind_venv_path="${UV_PROJECT_ENVIRONMENT:-.venv}"

uv sync --locked --extra dev --no-editable --reinstall-package travelmind "$@"

"$travelmind_venv_path/bin/python" -c \
  'import travelmind; print(f"TravelMind {travelmind.__version__} is importable from {travelmind.__file__}")'
