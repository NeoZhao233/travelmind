from travelmind.evaluation.source_fetch_runner import run_source_fetch_drill


def test_conditional_fetch_and_freshness_drill_passes_all_contracts() -> None:
    report = run_source_fetch_drill()

    assert report["metrics"] == {
        "check_pass_rate": 1,
        "conditional_revalidation_rate": 1,
        "transient_recovery_rate": 1,
        "dynamic_stale_rejection_rate": 1,
        "bounded_static_availability_rate": 1,
        "unsafe_transport_call_rate": 0,
    }
    assert all(report["checks"].values())
