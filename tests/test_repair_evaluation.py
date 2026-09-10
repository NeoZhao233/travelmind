import json
from pathlib import Path

from typer.testing import CliRunner

from travelmind.cli import app
from travelmind.evaluation.repair_runner import run_repair_experiment

PROJECT_ROOT = Path(__file__).resolve().parents[1]


def test_stage5c_repair_evaluation_passes_controlled_gates() -> None:
    report = run_repair_experiment(PROJECT_ROOT)

    assert report["metrics"] == {
        "case_count": 7,
        "expected_outcome_exact_match": 1,
        "repairable_case_success_rate": 1,
        "safe_failure_accuracy": 1,
        "unaffected_day_preservation_rate": 1,
        "repairer_outage_recovery_rate": 1,
        "mean_repair_attempts": 6 / 7,
    }
    impossible = next(
        item for item in report["cases"] if item["case_id"] == "impossible_required_bounded"
    )
    assert impossible["modified_days"] == []


def test_repair_cli_writes_versioned_report(tmp_path: Path) -> None:
    output = tmp_path / "repair.json"

    result = CliRunner().invoke(
        app,
        [
            "eval-itinerary-repair",
            "--root",
            str(PROJECT_ROOT),
            "--output",
            str(output),
        ],
    )

    assert result.exit_code == 0
    report = json.loads(output.read_text(encoding="utf-8"))
    assert report["metrics"]["repairable_case_success_rate"] == 1
    assert '"unaffected_day_preservation_rate"' in result.stdout
