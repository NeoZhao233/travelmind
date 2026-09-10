from pathlib import Path

from travelmind.evaluation.slo_runner import run_slo_outage_drill

PROJECT_ROOT = Path(__file__).resolve().parents[1]


def test_pre_release_slo_and_composite_outage_contracts() -> None:
    report = run_slo_outage_drill(PROJECT_ROOT)

    assert report["objective_type"] == "synthetic_pre_release_gate"
    assert report["metrics"]["check_pass_rate"] == 1
    assert report["metrics"]["recoverable_composite_completion_rate"] == 1
    assert report["metrics"]["unrecoverable_safe_failure_rate"] == 1
    assert report["metrics"]["degradation_visibility_rate"] == 1
    assert report["metrics"]["canary_leak_rate"] == 0
    assert all(report["checks"].values())
