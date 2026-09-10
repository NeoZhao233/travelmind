from travelmind.evaluation.checkpoint_runner import run_checkpoint_idempotency_drill


def test_checkpoint_and_idempotency_drill_passes_all_contracts() -> None:
    report = run_checkpoint_idempotency_drill()

    assert report["metrics"] == {
        "check_pass_rate": 1,
        "logical_resume_success_rate": 1,
        "duplicate_side_effect_prevention_rate": 1,
        "checkpoint_outage_safe_failure_rate": 1,
    }
    assert report["diagnostics"]["planner_calls_across_resume"] == 1
    assert all(report["checks"].values())
