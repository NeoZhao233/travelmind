from __future__ import annotations

import hashlib
import json
from collections import Counter
from pathlib import Path
from typing import Any

from travelmind.evaluation.e2e_planning_runner import E2EPlanningDataset
from travelmind.evaluation.governance import validate_evaluation_governance


def _issue_codes(row: dict[str, Any], minimum_expected_hits: int) -> list[str]:
    issues: list[str] = []
    planner_call = row.get("planner_call") or {}
    if row.get("failure_reason"):
        issues.append("pipeline_failure")
    if row.get("retrieved_evidence_count") == 0:
        issues.append("retrieval_empty")
    elif row.get("packed_evidence_count") == 0:
        issues.append("context_empty_after_retrieval")
    if row.get("candidate_count") == 0:
        issues.append("candidate_empty")
    if not row.get("constraint_satisfied", False):
        issues.append("hard_constraint_violation")
    if row.get("required_coverage", 0) < 1:
        issues.append("required_place_miss")
    expected_hit_rate = row.get("expected_hit_rate", 0)
    inferred_hits = round(expected_hit_rate * max(1, row.get("expected_place_count", 1)))
    if not row.get("task_success", False) and inferred_hits < minimum_expected_hits:
        issues.append("minimum_preference_miss")
    elif expected_hit_rate < 1:
        issues.append("partial_expected_coverage")
    if row.get("expected_place_precision", 1) < 1:
        issues.append("unexpected_selection")
    if planner_call.get("fallback_used"):
        issues.append("planner_fallback")
    reason = str(planner_call.get("error_reason_code") or "")
    error_type = str(planner_call.get("error_type") or "")
    if error_type and "validation" not in error_type.casefold():
        issues.append("provider_failure")
    if reason or "validation" in error_type.casefold():
        issues.append("structured_output_failure")
    if not row.get("valid_plan", False) and row.get("repair_attempts", 0) > 0:
        issues.append("repair_exhausted")
    if not issues:
        issues.append("none")
    return issues


def _metrics(rows: list[dict[str, Any]]) -> dict[str, float | int]:
    if not rows:
        return {"case_count": 0}
    planner_calls = [row["planner_call"] for row in rows if row.get("planner_call")]
    successful_calls = [call for call in planner_calls if call.get("success")]
    return {
        "case_count": len(rows),
        "task_success_rate": sum(bool(row["task_success"]) for row in rows) / len(rows),
        "valid_plan_rate": sum(bool(row["valid_plan"]) for row in rows) / len(rows),
        "constraint_satisfaction_rate": sum(bool(row["constraint_satisfied"]) for row in rows)
        / len(rows),
        "required_place_coverage": sum(row["required_coverage"] for row in rows) / len(rows),
        "expected_place_hit_rate": sum(row["expected_hit_rate"] for row in rows) / len(rows),
        "expected_place_precision": sum(row["expected_place_precision"] for row in rows)
        / len(rows),
        "fallback_rate": sum(
            bool((row.get("planner_call") or {}).get("fallback_used")) for row in rows
        )
        / len(rows),
        "repair_activation_rate": sum(row.get("repair_attempts", 0) > 0 for row in rows)
        / len(rows),
        "total_provider_tokens": sum(call.get("total_tokens", 0) for call in planner_calls),
        "mean_provider_latency_ms": (
            sum(call.get("latency_ms", 0) for call in successful_calls) / len(successful_calls)
            if successful_calls
            else None
        ),
    }


def audit_e2e_report(
    root: Path,
    *,
    report_path: Path,
    manifest_path: Path,
) -> dict[str, Any]:
    root = root.resolve()
    governance = validate_evaluation_governance(root, manifest_path)
    resolved_report = (report_path if report_path.is_absolute() else root / report_path).resolve()
    report_raw = resolved_report.read_bytes()
    report = json.loads(report_raw)
    if report.get("dataset_sha256") != governance["dataset_sha256"]:
        raise ValueError("report and governed dataset fingerprints do not match")

    dataset = E2EPlanningDataset.model_validate_json((root / governance["dataset"]).read_bytes())
    labels = {case.case_id: case for case in dataset.cases}
    audited_rows: list[dict[str, Any]] = []
    unobserved_fields: set[str] = set()
    for row in report["cases"]:
        case_id = row["case_id"]
        if case_id not in labels:
            raise ValueError(f"report contains unknown case ID: {case_id}")
        if "candidate_count" not in row:
            unobserved_fields.add("candidate_count")
        enriched = dict(row)
        enriched["split"] = governance["case_splits"][case_id]
        enriched["expected_place_count"] = len(labels[case_id].expected_place_ids)
        enriched["issue_codes"] = _issue_codes(enriched, labels[case_id].minimum_expected_hits)
        audited_rows.append(enriched)

    variants = sorted({row["variant"] for row in audited_rows})
    split_metrics = {
        variant: {
            split: _metrics(
                [row for row in audited_rows if row["variant"] == variant and row["split"] == split]
            )
            for split in ("development", "test", "challenge")
            if any(row["variant"] == variant and row["split"] == split for row in audited_rows)
        }
        for variant in variants
    }
    issue_counts = {
        variant: dict(
            sorted(
                Counter(
                    issue
                    for row in audited_rows
                    if row["variant"] == variant
                    for issue in row["issue_codes"]
                ).items()
            )
        )
        for variant in variants
    }
    return {
        "experiment": "stage6ab-evaluation-governance-and-error-audit",
        "source_report": str(resolved_report.relative_to(root)),
        "source_report_sha256": hashlib.sha256(report_raw).hexdigest(),
        "governance": governance,
        "split_metrics": split_metrics,
        "issue_counts": issue_counts,
        "cases": audited_rows,
        "unobserved_fields": sorted(unobserved_fields),
        "taxonomy_notes": {
            "unexpected_selection": (
                "A diagnostic against the incomplete expected-place set, not proof that the "
                "extra place is objectively wrong."
            ),
            "partial_expected_coverage": (
                "The minimum task threshold passed, but not every labeled preference was selected."
            ),
        },
        "limitations": [
            governance["claim_boundary"],
            "Five cases are too small for statistically stable quality claims.",
            (
                "Error codes are deterministic symptoms; causal attribution still requires "
                "trace review."
            ),
            "The frozen Stage 5 report predates candidate_count telemetry in each case row.",
        ],
    }
