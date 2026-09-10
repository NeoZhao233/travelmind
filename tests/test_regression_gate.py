import json
from pathlib import Path

import pytest

from travelmind.evaluation.regression_gate import run_regression_gate

PROJECT_ROOT = Path(__file__).resolve().parents[1]
PROFILE = Path("evals/baselines/e2e_planning_release_v1.json")
AUDIT = Path("evals/results/stage6ab_evaluation_audit_v1.json")


def test_frozen_deterministic_baseline_passes_its_own_gate() -> None:
    report = run_regression_gate(
        PROJECT_ROOT,
        profile_path=PROFILE,
        candidate_audit_path=AUDIT,
        candidate_variant="deterministic",
    )

    assert report["gate_passed"] is True
    assert report["summary"]["failed_check_count"] == 0
    assert report["summary"]["provider_tokens_per_case"] == 0


def test_paid_deepseek_candidate_is_rejected_without_quality_lift() -> None:
    report = run_regression_gate(
        PROJECT_ROOT,
        profile_path=PROFILE,
        candidate_audit_path=AUDIT,
        candidate_variant="deepseek_ranked",
    )

    assert report["gate_passed"] is False
    failed = {item["name"] for item in report["checks"] if not item["passed"]}
    assert failed == {"paid_candidate_expected_hit_lift"}
    assert report["summary"]["expected_place_hit_rate_lift"] == 0


def test_modified_baseline_fingerprint_fails_closed(tmp_path: Path) -> None:
    profile = json.loads((PROJECT_ROOT / PROFILE).read_text())
    profile["baseline_audit_sha256"] = "0" * 64
    path = tmp_path / "profile.json"
    path.write_text(json.dumps(profile), encoding="utf-8")

    with pytest.raises(ValueError, match="baseline audit hash"):
        run_regression_gate(
            PROJECT_ROOT,
            profile_path=path,
            candidate_audit_path=AUDIT,
            candidate_variant="deterministic",
        )
