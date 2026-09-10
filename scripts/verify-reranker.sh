#!/usr/bin/env bash
set -euo pipefail

project_dir="$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)"
cd "$project_dir"

travelmind_venv_path="${UV_PROJECT_ENVIRONMENT:-.venv}"
export ORT_DISABLE_TELEMETRY="${ORT_DISABLE_TELEMETRY:-1}"

"$travelmind_venv_path/bin/travelmind" eval-retrieval \
  --root . \
  --retriever reranked \
  --local-files-only >/dev/null
"$travelmind_venv_path/bin/pytest" tests/test_reranking.py

echo "TravelMind reranker verification passed."
