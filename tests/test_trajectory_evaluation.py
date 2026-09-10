from pathlib import Path

from travelmind.evaluation.trajectory_runner import run_trajectory_experiment

ROOT = Path(__file__).resolve().parents[1]


def test_trajectory_report_compares_direct_and_agentic_paths() -> None:
    report = run_trajectory_experiment(ROOT)

    assert report["configuration"]["cases"] == 7
    assert report["configuration"]["reviewed_cases"] == 0
    assert report["direct_metrics"]["average_retrieval_calls"] == 1.0
    assert report["agentic_metrics"]["average_retrieval_calls"] > 1.0
    assert 0 <= report["agentic_metrics"]["rewrite_recovery_rate"] <= 1
    assert {item["split"] for item in report["cases"]} == {"development", "test"}


def test_trajectory_report_exposes_unsafe_generation_case() -> None:
    report = run_trajectory_experiment(ROOT)
    row = next(
        item for item in report["cases"] if item["case_id"] == "trajectory-lexical-blind-spot"
    )

    assert row["agentic"]["completed"] is True
    assert row["agentic_oracle_at_used_step"] is False
    assert report["agentic_metrics"]["unsupported_generation_rate"] > 0
