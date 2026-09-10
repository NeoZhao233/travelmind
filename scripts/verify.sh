#!/usr/bin/env bash
set -euo pipefail

project_dir="$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)"
cd "$project_dir"

travelmind_venv_path="${UV_PROJECT_ENVIRONMENT:-.venv}"

"$travelmind_venv_path/bin/python" -c 'import travelmind'
"$travelmind_venv_path/bin/travelmind" demo \
  '带父母去北京三天，预算3000元，喜欢历史文化' >/dev/null
"$travelmind_venv_path/bin/travelmind" validate-data --root . >/dev/null
"$travelmind_venv_path/bin/travelmind" eval-retrieval --root . >/dev/null
"$travelmind_venv_path/bin/pytest"
"$travelmind_venv_path/bin/ruff" check .

echo "TravelMind verification passed."
