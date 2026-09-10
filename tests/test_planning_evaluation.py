import json
from pathlib import Path

from typer.testing import CliRunner

from travelmind.cli import app
from travelmind.evaluation.planning_runner import run_planning_constraint_experiment

PROJECT_ROOT = Path(__file__).resolve().parents[1]


def test_stage5a_constraint_scenarios_pass_exact_match_gate() -> None:
    report = run_planning_constraint_experiment(PROJECT_ROOT)

    assert report["metrics"] == {
        "case_count": 10,
        "exact_match_accuracy": 1,
        "safety_case_detection_rate": 1,
        "clean_case_pass_rate": 1,
    }
    assert all(case["exact_match"] for case in report["cases"])


def test_planning_constraint_cli_writes_versioned_report(tmp_path: Path) -> None:
    output = tmp_path / "planning.json"

    result = CliRunner().invoke(
        app,
        [
            "eval-planning-constraints",
            "--root",
            str(PROJECT_ROOT),
            "--output",
            str(output),
        ],
    )

    assert result.exit_code == 0
    report = json.loads(output.read_text(encoding="utf-8"))
    assert report["metrics"]["exact_match_accuracy"] == 1
    assert '"safety_case_detection_rate"' in result.stdout
