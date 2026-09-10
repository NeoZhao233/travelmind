from pathlib import Path

from travelmind.evaluation.runtime_multistep_runner import run_runtime_multistep_experiment

ROOT = Path(__file__).resolve().parents[1]


def test_multistep_runtime_recovers_without_repeating_retrieval() -> None:
    report = run_runtime_multistep_experiment(ROOT)

    assert report["metrics"] == {
        "case_contract_pass_rate": 1,
        "baseline_intermediate_failure_recovery_rate": 0,
        "agentic_intermediate_failure_recovery_rate": 1,
        "completed_observation_reuse_rate": 1,
        "unrecoverable_safe_stop_rate": 1,
    }
    recovered = next(
        row for row in report["cases"] if row["case_id"] == "multistep-booking-failure"
    )
    assert recovered["agentic"]["plan_revisions"] == [1, 2]
    assert recovered["agentic"]["calls_by_tool"]["candidate_search"] == 1
    assert recovered["agentic"]["final_place"] == "national-museum"


def test_multistep_runtime_stops_when_replanned_path_also_fails() -> None:
    report = run_runtime_multistep_experiment(ROOT)
    exhausted = next(
        row for row in report["cases"] if row["case_id"] == "multistep-fallback-failure"
    )

    assert exhausted["agentic"]["status"] == "failed"
    assert exhausted["agentic"]["safe_stop"] is True
    assert exhausted["agentic"]["calls_by_tool"]["candidate_search"] == 1
    assert exhausted["agentic"]["plan_revisions"] == [1, 2]
