from travelmind.evaluation.memory_runner import run_memory_isolation_experiment


def test_memory_isolation_experiment_passes_all_safety_gates() -> None:
    report = run_memory_isolation_experiment()

    assert report["metrics"] == {
        "probes": 14,
        "cross_scope_leakage_rate": 0,
        "lifecycle_probe_accuracy": 1,
        "privacy_probe_accuracy": 1,
        "outage_probe_accuracy": 1,
    }
    assert report["selection"]["gate_passed"] is True
    assert all(probe["passed"] for probe in report["probes"])
