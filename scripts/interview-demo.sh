#!/usr/bin/env bash
set -euo pipefail

project_dir="$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)"
cd "$project_dir"

travelmind_venv_path="${UV_PROJECT_ENVIRONMENT:-.venv}"
demo_tmp="$(mktemp -d /private/tmp/travelmind-interview-demo.XXXXXX)"
trap 'rm -rf "$demo_tmp"' EXIT

printf 'TravelMind v1 interview demo\n'
"$travelmind_venv_path/bin/travelmind" validate-data --root .

"$travelmind_venv_path/bin/travelmind" demo \
  '带父母去北京一天，预算300元，喜欢历史文化' >"$demo_tmp/itinerary.json"
"$travelmind_venv_path/bin/python" - "$demo_tmp/itinerary.json" <<'PY'
import json
import sys

with open(sys.argv[1], encoding="utf-8") as handle:
    result = json.load(handle)
print(
    json.dumps(
        {
            "workflow_status": result["status"],
            "evidence_count": len(result["evidence"]),
            "violation_count": len(result["violations"]),
            "estimated_total_cost": result["itinerary"]["estimated_total_cost"],
        },
        ensure_ascii=False,
        indent=2,
    )
)
PY

"$travelmind_venv_path/bin/travelmind" eval-slo-outages --root .
"$travelmind_venv_path/bin/travelmind" eval-index-publishing --root .
"$travelmind_venv_path/bin/travelmind" eval-incremental-ingestion --root .
"$travelmind_venv_path/bin/travelmind" release-audit --root .
