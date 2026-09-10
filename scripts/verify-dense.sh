#!/usr/bin/env bash
set -euo pipefail

project_dir="$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)"
cd "$project_dir"

travelmind_venv_path="${UV_PROJECT_ENVIRONMENT:-.venv}"
export ORT_DISABLE_TELEMETRY="${ORT_DISABLE_TELEMETRY:-1}"

"$travelmind_venv_path/bin/python" -c 'import fastembed'
"$travelmind_venv_path/bin/travelmind" eval-retrieval \
  --root . \
  --retriever dense \
  --local-files-only >/dev/null
"$travelmind_venv_path/bin/travelmind" eval-retrieval \
  --root . \
  --retriever hybrid \
  --local-files-only >/dev/null
"$travelmind_venv_path/bin/pytest" \
  tests/test_dense.py \
  tests/test_embeddings.py \
  tests/test_hybrid.py

echo "TravelMind dense and hybrid verification passed."
