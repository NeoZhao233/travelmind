from pathlib import Path

from travelmind.evaluation.harness_runner import run_harness_experiment


def test_harness_experiment_covers_protocol_fallback_cache_and_safe_stop() -> None:
    report = run_harness_experiment(Path("."))
    assert report["metrics"] == {
        "check_pass_rate": 1.0,
        "mcp_protocol_completion_rate": 1.0,
        "transport_fallback_recovery_rate": 1.0,
        "dual_path_safe_stop_rate": 1.0,
        "cache_hit_rate": 0.5,
        "redis_cache_outage_bypass_rate": 1.0,
    }
    assert all(report["checks"].values())
    scenarios = {row["scenario"]: row for row in report["runtime_scenarios"]}
    assert scenarios["remote_business_error_replan"]["replans"] == 1
    assert scenarios["mcp_and_local_safe_stop"]["safe_stop"] is True
