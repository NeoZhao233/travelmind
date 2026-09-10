import json
from pathlib import Path

from typer.testing import CliRunner

from travelmind.cli import app
from travelmind.evaluation.candidate_planning_runner import (
    run_candidate_planning_experiment,
)

PROJECT_ROOT = Path(__file__).resolve().parents[1]


def test_candidate_planning_experiment_passes_controlled_gates() -> None:
    report = run_candidate_planning_experiment(PROJECT_ROOT)

    assert report["metrics"] == {
        "case_count": 5,
        "expected_outcome_exact_match": 1,
        "unsafe_activity_admission_free_rate": 1,
        "candidate_decision_trace_coverage": 1,
    }
    assert all(case["exact_match"] for case in report["cases"])


def test_candidate_planning_cli_writes_report(tmp_path: Path) -> None:
    output = tmp_path / "candidate-planning.json"

    result = CliRunner().invoke(
        app,
        [
            "eval-candidate-planning",
            "--root",
            str(PROJECT_ROOT),
            "--output",
            str(output),
        ],
    )

    assert result.exit_code == 0
    report = json.loads(output.read_text(encoding="utf-8"))
    assert report["algorithm"] == "explainable-greedy-v1"
    assert '"candidate_decision_trace_coverage"' in result.stdout
