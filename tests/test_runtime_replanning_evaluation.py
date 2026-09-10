from pathlib import Path

from travelmind.evaluation.runtime_replanning_runner import run_runtime_replanning_experiment

ROOT = Path(__file__).resolve().parents[1]


def test_runtime_replanning_report_measures_recovery_and_safe_stop() -> None:
    report = run_runtime_replanning_experiment(ROOT)

    assert report["configuration"] == {
        "cases": 4,
        "reviewed_cases": 0,
        "max_replans": 1,
        "max_tool_attempts": 2,
    }
    assert report["baseline_metrics"]["recoverable_completion_rate"] == 1 / 3
    assert report["agentic_metrics"] == {
        "recoverable_completion_rate": 1,
        "expected_replan_rate": 1,
        "failure_attribution_accuracy": 1,
        "unrecoverable_safe_stop_rate": 1,
        "mean_tool_calls": 2,
    }


def test_permanent_failure_has_a_real_second_plan_revision() -> None:
    report = run_runtime_replanning_experiment(ROOT)
    row = next(
        item
        for item in report["cases"]
        if item["case_id"] == "runtime-booking-permission"
    )

    assert row["baseline"]["plan_revisions"] == [1]
    assert row["agentic"]["plan_revisions"] == [1, 2]
    assert row["agentic"]["status"] == "completed"
