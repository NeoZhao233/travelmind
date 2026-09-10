from __future__ import annotations

import hashlib
import json
from pathlib import Path
from typing import Any

from pydantic import BaseModel, Field


class RegressionGateProfile(BaseModel):
    schema_version: int = 1
    profile_id: str
    baseline_audit: str
    baseline_audit_sha256: str = Field(pattern=r"^[0-9a-f]{64}$")
    baseline_variant: str
    required_splits: list[str] = Field(min_length=1)
    non_decreasing_metrics: list[str] = Field(min_length=1)
    maximum_fallback_rate: float = Field(ge=0, le=1)
    maximum_provider_tokens_per_case: float = Field(ge=0)
    maximum_mean_provider_latency_ms: float = Field(ge=0)
    paid_candidate_minimum_expected_hit_lift: float = Field(ge=0)
    forbidden_issue_codes: list[str] = Field(default_factory=list)


def _check(
    checks: list[dict[str, Any]],
    *,
    name: str,
    passed: bool,
    actual: Any,
    expected: Any,
) -> None:
    checks.append(
        {
            "name": name,
            "passed": passed,
            "actual": actual,
            "expected": expected,
        }
    )


def _load_json(path: Path) -> tuple[dict[str, Any], bytes]:
    raw = path.read_bytes()
    return json.loads(raw), raw


def run_regression_gate(
    root: Path,
    *,
    profile_path: Path,
    candidate_audit_path: Path,
    candidate_variant: str,
) -> dict[str, Any]:
    root = root.resolve()
    resolved_profile = (
        profile_path if profile_path.is_absolute() else root / profile_path
    ).resolve()
    profile = RegressionGateProfile.model_validate_json(resolved_profile.read_bytes())
    baseline_path = (root / profile.baseline_audit).resolve()
    baseline, baseline_raw = _load_json(baseline_path)
    baseline_sha = hashlib.sha256(baseline_raw).hexdigest()
    if baseline_sha != profile.baseline_audit_sha256:
        raise ValueError("baseline audit hash does not match the frozen gate profile")
    candidate_path = (
        candidate_audit_path if candidate_audit_path.is_absolute() else root / candidate_audit_path
    ).resolve()
    candidate, candidate_raw = _load_json(candidate_path)

    baseline_governance = baseline["governance"]
    candidate_governance = candidate["governance"]
    checks: list[dict[str, Any]] = []
    for fingerprint in ("dataset_sha256", "manifest_sha256"):
        actual = candidate_governance[fingerprint]
        expected = baseline_governance[fingerprint]
        _check(
            checks,
            name=f"same_{fingerprint}",
            passed=actual == expected,
            actual=actual,
            expected=expected,
        )

    if profile.baseline_variant not in baseline["split_metrics"]:
        raise ValueError(f"baseline variant is absent: {profile.baseline_variant}")
    if candidate_variant not in candidate["split_metrics"]:
        raise ValueError(f"candidate variant is absent: {candidate_variant}")
    baseline_splits = baseline["split_metrics"][profile.baseline_variant]
    candidate_splits = candidate["split_metrics"][candidate_variant]
    for split in profile.required_splits:
        if split not in baseline_splits or split not in candidate_splits:
            raise ValueError(f"required split is absent: {split}")
        for metric in profile.non_decreasing_metrics:
            actual = candidate_splits[split][metric]
            expected = baseline_splits[split][metric]
            _check(
                checks,
                name=f"{split}.{metric}.non_decreasing",
                passed=actual >= expected,
                actual=actual,
                expected=f">={expected}",
            )

    candidate_rows = [row for row in candidate["cases"] if row["variant"] == candidate_variant]
    if not candidate_rows:
        raise ValueError("candidate audit contains no matching case rows")
    calls = [row["planner_call"] for row in candidate_rows if row.get("planner_call")]
    successful_calls = [call for call in calls if call.get("success")]
    fallback_rate = (
        sum(bool(call.get("fallback_used")) for call in calls) / len(calls) if calls else 0.0
    )
    total_tokens = sum(call.get("total_tokens", 0) for call in calls)
    tokens_per_case = total_tokens / len(candidate_rows)
    mean_latency = (
        sum(call.get("latency_ms", 0) for call in successful_calls) / len(successful_calls)
        if successful_calls
        else 0.0
    )
    _check(
        checks,
        name="maximum_fallback_rate",
        passed=fallback_rate <= profile.maximum_fallback_rate,
        actual=fallback_rate,
        expected=f"<={profile.maximum_fallback_rate}",
    )
    _check(
        checks,
        name="maximum_provider_tokens_per_case",
        passed=tokens_per_case <= profile.maximum_provider_tokens_per_case,
        actual=tokens_per_case,
        expected=f"<={profile.maximum_provider_tokens_per_case}",
    )
    _check(
        checks,
        name="maximum_mean_provider_latency_ms",
        passed=mean_latency <= profile.maximum_mean_provider_latency_ms,
        actual=mean_latency,
        expected=f"<={profile.maximum_mean_provider_latency_ms}",
    )

    issue_counts = candidate["issue_counts"][candidate_variant]
    forbidden_found = {
        code: issue_counts.get(code, 0)
        for code in profile.forbidden_issue_codes
        if issue_counts.get(code, 0) > 0
    }
    _check(
        checks,
        name="no_forbidden_issue_codes",
        passed=not forbidden_found,
        actual=forbidden_found,
        expected={},
    )

    baseline_rows = [row for row in baseline["cases"] if row["variant"] == profile.baseline_variant]
    baseline_hit = sum(row["expected_hit_rate"] for row in baseline_rows) / len(baseline_rows)
    candidate_hit = sum(row["expected_hit_rate"] for row in candidate_rows) / len(candidate_rows)
    paid_candidate = total_tokens > 0
    lift = candidate_hit - baseline_hit
    _check(
        checks,
        name="paid_candidate_expected_hit_lift",
        passed=(not paid_candidate or lift >= profile.paid_candidate_minimum_expected_hit_lift),
        actual={"paid_candidate": paid_candidate, "lift": lift},
        expected=(
            "not_applicable_when_zero_provider_tokens"
            if not paid_candidate
            else f">={profile.paid_candidate_minimum_expected_hit_lift}"
        ),
    )
    passed = all(item["passed"] for item in checks)
    return {
        "experiment": "stage6d-frozen-regression-gate",
        "profile_id": profile.profile_id,
        "profile": str(resolved_profile.relative_to(root)),
        "profile_sha256": hashlib.sha256(resolved_profile.read_bytes()).hexdigest(),
        "baseline_audit": profile.baseline_audit,
        "baseline_audit_sha256": baseline_sha,
        "candidate_audit": str(candidate_path.relative_to(root)),
        "candidate_audit_sha256": hashlib.sha256(candidate_raw).hexdigest(),
        "baseline_variant": profile.baseline_variant,
        "candidate_variant": candidate_variant,
        "status": "passed" if passed else "rejected",
        "gate_passed": passed,
        "checks": checks,
        "summary": {
            "check_count": len(checks),
            "failed_check_count": sum(not item["passed"] for item in checks),
            "provider_tokens_per_case": tokens_per_case,
            "mean_provider_latency_ms": mean_latency,
            "expected_place_hit_rate_lift": lift,
        },
        "limitations": [
            "The frozen pilot has five project-authored non-blind cases.",
            "Passing prevents measured regressions; it does not establish production quality.",
            "Subjective Judge metrics remain excluded until Stage 6C calibration passes.",
        ],
    }
