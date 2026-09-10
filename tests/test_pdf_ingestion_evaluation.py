from pathlib import Path

from travelmind.evaluation.pdf_ingestion_runner import run_pdf_ingestion_drill

PROJECT_ROOT = Path(__file__).resolve().parents[1]


def test_pdf_ingestion_drill_passes_all_admission_and_snapshot_checks() -> None:
    report = run_pdf_ingestion_drill(PROJECT_ROOT)

    assert report["status"] == "passed"
    assert report["metrics"] == {
        "checks": 10,
        "check_pass_rate": 1.0,
        "rejected_payload_admission_rate": 0.0,
        "snapshot_deduplication_rate": 1.0,
    }
    assert all(case["passed"] for case in report["cases"])
