from pathlib import Path

from travelmind.evaluation.agentic_runner import (
    run_deterministic_agentic_policy_experiment,
)

PROJECT_ROOT = Path(__file__).resolve().parents[1]


def test_agentic_policy_report_is_fingerprinted_and_split() -> None:
    report = run_deterministic_agentic_policy_experiment(PROJECT_ROOT)

    assert len(report["dataset_fingerprint_sha256"]) == 64
    assert report["configuration"]["routing_cases"] == 15
    assert report["configuration"]["grading_cases"] == 11
    assert report["configuration"]["reviewed_routing_cases"] == 0
    assert set(report["routing_metrics"]) == {"all", "development", "test"}
    assert set(report["grading_metrics"]) == {"all", "development", "test"}
    for metrics in report["routing_metrics"].values():
        assert 0 <= metrics["accuracy"] <= 1
    for metrics in report["grading_metrics"].values():
        for name in (
            "accuracy",
            "precision",
            "recall",
            "f1",
            "required_aspects_exact_match",
            "missing_aspects_exact_match",
        ):
            assert 0 <= metrics[name] <= 1
