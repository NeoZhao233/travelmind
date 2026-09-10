from __future__ import annotations

import hashlib
import json
import tomllib
from pathlib import Path

from pydantic import BaseModel, Field


class ReleaseManifest(BaseModel):
    schema_version: int = 1
    release_id: str = Field(min_length=1)
    project_version: str = Field(min_length=1)
    evidence_files: dict[str, str] = Field(min_length=1)


def _inside(root: Path, relative: str) -> Path:
    candidate = (root / relative).resolve()
    if not candidate.is_relative_to(root):
        raise ValueError("release evidence path escapes project root")
    return candidate


def _load(root: Path, relative: str) -> dict:
    return json.loads(_inside(root, relative).read_text(encoding="utf-8"))


def run_release_audit(root: Path, manifest_path: Path) -> dict:
    project_root = root.resolve()
    resolved_manifest = (
        manifest_path if manifest_path.is_absolute() else project_root / manifest_path
    ).resolve()
    raw_manifest = resolved_manifest.read_bytes()
    manifest = ReleaseManifest.model_validate_json(raw_manifest)

    hash_checks = {}
    for relative, expected in sorted(manifest.evidence_files.items()):
        if len(expected) != 64 or any(
            character not in "0123456789abcdef" for character in expected
        ):
            raise ValueError("release evidence hash must be a SHA-256 digest")
        path = _inside(project_root, relative)
        hash_checks[relative] = (
            path.is_file() and hashlib.sha256(path.read_bytes()).hexdigest() == expected
        )

    project = tomllib.loads((project_root / "pyproject.toml").read_text())
    hybrid = _load(project_root, "evals/results/hybrid_rrf_seed.json")
    reranked = _load(project_root, "evals/results/hybrid_bge_reranker_base_seed.json")
    policies = _load(project_root, "evals/results/deepseek_policy_status.json")
    context = _load(project_root, "evals/results/stage4_deepseek_answer_ablation_v4_final.json")
    planner = _load(project_root, "evals/results/e2e_planning_deepseek_ab_v3_final.json")
    selected_gate = _load(
        project_root, "evals/results/stage6d_regression_gate_deterministic_v1.json"
    )
    rejected_gate = _load(project_root, "evals/results/stage6d_regression_gate_deepseek_v1.json")
    judge = _load(project_root, "evals/results/stage6c_deepseek_judge_reference_v1.json")
    durable = _load(project_root, "evals/results/stage7c2_durable_checkpoint_v1.json")
    outage = _load(project_root, "evals/results/stage7d_slo_outage_v1.json")
    ingestion = _load(project_root, "evals/results/stage8c_incremental_ingestion_v1.json")
    gitignore = (project_root / ".gitignore").read_text().splitlines()
    semantic_checks = {
        "project_version_matches": project["project"]["version"] == manifest.project_version,
        "local_secret_files_ignored": ".env" in gitignore and ".env.local" in gitignore,
        "hybrid_recall_at_5_meets_claim": hybrid["metrics"]["recall_at_k"]["5"] >= 0.95,
        "reranker_not_better_than_hybrid": reranked["metrics"]["recall_at_k"]["5"]
        < hybrid["metrics"]["recall_at_k"]["5"],
        "mixed_agent_policy_selected": policies["status"] == "evaluated_mixed_stack_selected",
        "llm_router_selected": policies["selected_policies"]["router"].startswith("LLMQueryRouter"),
        "refined_context_selected": context["selection"]["selected_pipeline"] == "refined_coverage",
        "refined_context_gate_passed": context["selection"]["gate_passed"] is True,
        "deterministic_planner_selected": planner["selection"]["selected_planner"]
        == "deterministic",
        "planner_llm_lift_is_zero": planner["selection"]["expected_place_hit_rate_lift"] == 0,
        "selected_release_gate_passed": selected_gate["status"] == "passed",
        "paid_planner_release_gate_rejected": rejected_gate["status"] == "rejected",
        "judge_v1_is_reference_only": judge["selection"]["status"] == "reference_only",
        "judge_v1_not_accepted": judge["selection"]["judge_accepted"] is False,
        "durable_recovery_checks_passed": durable["metrics"]["check_pass_rate"] == 1,
        "composite_outage_checks_passed": outage["metrics"]["check_pass_rate"] == 1,
        "composite_outage_canary_not_leaked": outage["metrics"]["canary_leak_rate"] == 0,
        "incremental_ingestion_checks_passed": ingestion["metrics"]["check_pass_rate"] == 1,
    }
    checks = {
        **{f"hash:{key}": value for key, value in hash_checks.items()},
        **semantic_checks,
    }
    failed = sorted(key for key, passed in checks.items() if not passed)
    return {
        "release_id": manifest.release_id,
        "manifest_sha256": hashlib.sha256(raw_manifest).hexdigest(),
        "status": "passed" if not failed else "failed",
        "checks": checks,
        "summary": {
            "check_count": len(checks),
            "failed_check_count": len(failed),
            "evidence_file_count": len(hash_checks),
        },
        "failed_checks": failed,
        "claim_boundary": (
            "Interview-grade pilot evidence; not a production-scale or statistical claim."
        ),
    }
