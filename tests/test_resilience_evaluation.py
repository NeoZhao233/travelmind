from travelmind.evaluation.resilience_runner import run_retrieval_resilience_drill


def test_retrieval_resilience_drill_passes_all_state_and_freshness_checks() -> None:
    report = run_retrieval_resilience_drill()

    assert report["metrics"] == {
        "check_pass_rate": 1,
        "fast_fail_provider_call_avoidance": 1,
        "dynamic_stale_rejection_rate": 1,
        "half_open_recovery_rate": 1,
        "bounded_static_stale_availability_rate": 1,
    }
    assert all(report["checks"].values())
