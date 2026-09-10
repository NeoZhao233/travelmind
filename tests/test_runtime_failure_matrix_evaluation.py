from pathlib import Path

from travelmind.evaluation.runtime_failure_matrix_runner import (
    run_runtime_failure_matrix_experiment,
)

ROOT = Path(__file__).resolve().parents[1]


def test_expanded_runtime_matrix_covers_retry_replan_and_safe_stop() -> None:
    report = run_runtime_failure_matrix_experiment(ROOT)

    assert report["configuration"]["cases"] == 34
    assert set(report["configuration"]["failure_mode_counts"]) == {
        "timeout",
        "connection",
        "permission",
        "runtime",
        "invalid_output",
        "insufficient_evidence",
    }
    assert report["metrics"] == {
        "case_contract_pass_rate": 1,
        "baseline_replan_required_recovery_rate": 0,
        "agentic_replan_required_recovery_rate": 1,
        "transient_retry_recovery_rate": 1,
        "completed_observation_reuse_rate": 1,
        "unrecoverable_safe_stop_rate": 1,
    }


def test_fault_matrix_report_does_not_leak_injected_exception_messages() -> None:
    report = run_runtime_failure_matrix_experiment(ROOT)

    assert "injected secret" not in str(report)
    stopped = [row for row in report["cases"] if not row["recoverable"]]
    assert stopped
    assert all(row["agentic"]["safe_stop"] for row in stopped)
