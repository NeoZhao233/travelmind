import hashlib
import json
from pathlib import Path

import pytest
from pydantic import ValidationError

from travelmind.evaluation.error_analysis import audit_e2e_report
from travelmind.evaluation.governance import (
    DatasetGovernanceError,
    EvaluationCaseGovernance,
    validate_evaluation_governance,
)

PROJECT_ROOT = Path(__file__).resolve().parents[1]
MANIFEST = Path("evals/datasets/e2e_planning_seed.manifest.json")


def test_seed_manifest_is_frozen_but_not_independent_or_blind() -> None:
    result = validate_evaluation_governance(PROJECT_ROOT, MANIFEST)

    assert result["split_counts"] == {"development": 3, "test": 2}
    assert result["cross_split_leakage_count"] == 0
    assert result["test_is_independently_reviewed"] is False
    assert result["test_is_blind"] is False


def test_independent_review_claim_requires_a_distinct_reviewer() -> None:
    with pytest.raises(ValidationError, match="reviewer who is not an author"):
        EvaluationCaseGovernance(
            case_id="case",
            split="test",
            author_ids=["same-person"],
            reviewer_ids=["same-person"],
            review_status="independently_reviewed",
        )


def test_manifest_hash_mismatch_fails_closed(tmp_path: Path) -> None:
    payload = json.loads((PROJECT_ROOT / MANIFEST).read_text())
    payload["source_sha256"] = "0" * 64
    manifest = tmp_path / "manifest.json"
    manifest.write_text(json.dumps(payload), encoding="utf-8")

    with pytest.raises(DatasetGovernanceError, match="hash does not match"):
        validate_evaluation_governance(PROJECT_ROOT, manifest)


def test_cross_split_duplicate_query_is_rejected(tmp_path: Path) -> None:
    dataset = json.loads((PROJECT_ROOT / "evals/datasets/e2e_planning_seed.json").read_text())
    dataset["cases"][1]["query"] = dataset["cases"][0]["query"]
    dataset_path = tmp_path / "dataset.json"
    raw = json.dumps(dataset, ensure_ascii=False).encode()
    dataset_path.write_bytes(raw)
    manifest_payload = json.loads((PROJECT_ROOT / MANIFEST).read_text())
    manifest_payload["source_dataset"] = "dataset.json"
    manifest_payload["source_sha256"] = hashlib.sha256(raw).hexdigest()
    manifest_path = tmp_path / "manifest.json"
    manifest_path.write_text(json.dumps(manifest_payload), encoding="utf-8")

    with pytest.raises(DatasetGovernanceError, match="cross-split leakage"):
        validate_evaluation_governance(tmp_path, manifest_path)


def test_stage5_report_gets_split_metrics_and_deterministic_issue_codes() -> None:
    audited = audit_e2e_report(
        PROJECT_ROOT,
        report_path=Path("evals/results/e2e_planning_deepseek_ab_v3_final.json"),
        manifest_path=MANIFEST,
    )

    assert audited["split_metrics"]["deterministic"]["development"]["task_success_rate"] == 1
    assert audited["split_metrics"]["deepseek_ranked"]["test"]["task_success_rate"] == 1
    assert audited["issue_counts"]["deterministic"]["unexpected_selection"] == 2
    assert audited["issue_counts"]["deepseek_ranked"]["partial_expected_coverage"] == 1
    assert audited["unobserved_fields"] == ["candidate_count"]
