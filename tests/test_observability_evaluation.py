from pathlib import Path

from travelmind.evaluation.observability_runner import run_observability_drill

PROJECT_ROOT = Path(__file__).resolve().parents[1]


def test_observability_drill_passes_redaction_and_outage_contracts() -> None:
    report = run_observability_drill(PROJECT_ROOT)

    assert report["metrics"] == {
        "business_completion_rate": 1,
        "canary_leak_rate": 0,
        "trace_integrity_rate_when_sink_available": 1,
        "telemetry_outage_survival_rate": 1,
        "retrieval_fallback_visibility_rate": 1,
    }
    fallback = next(row for row in report["cases"] if row["scenario"] == "retrieval_fallback")
    assert fallback["safe_error_types"] == ["TimeoutError"]
