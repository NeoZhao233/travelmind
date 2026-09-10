import json
from pathlib import Path

from typer.testing import CliRunner

from travelmind.cli import app

PROJECT_ROOT = Path(__file__).resolve().parents[1]


def test_demo_cli_completes_without_external_dependencies() -> None:
    result = CliRunner().invoke(app, ["demo", "Plan a history trip to Beijing"])

    assert result.exit_code == 0
    assert '"status": "completed"' in result.stdout
    assert '"retrieval_attempts": 1' in result.stdout


def test_agentic_demo_exposes_route_grade_and_trajectory() -> None:
    result = CliRunner().invoke(
        app,
        ["agentic-demo", "周一带父母去故宫，需要门票和预约信息"],
    )

    assert result.exit_code == 0
    payload = json.loads(result.stdout)
    assert payload["status"] == "completed"
    assert payload["routing_decision"]["intent"] == "multi_constraint"
    assert payload["evidence_assessment"]["sufficient"] is True
    assert [event["node"] for event in payload["trajectory"]] == [
        "initialize",
        "route_query",
        "retrieve",
        "grade_evidence",
        "generate",
        "validate",
    ]


def test_eval_retrieval_cli_writes_report(tmp_path: Path) -> None:
    output = tmp_path / "bm25.json"
    result = CliRunner().invoke(
        app,
        [
            "eval-retrieval",
            "--root",
            str(PROJECT_ROOT),
            "--output",
            str(output),
        ],
    )

    assert result.exit_code == 0
    report = json.loads(output.read_text(encoding="utf-8"))
    assert report["experiment"] == "bm25-char-unigram-bigram-lexical"
    assert '"recall_at_k"' in result.stdout


def test_eval_agentic_cli_writes_draft_policy_report(tmp_path: Path) -> None:
    output = tmp_path / "agentic.json"
    result = CliRunner().invoke(
        app,
        [
            "eval-agentic",
            "--root",
            str(PROJECT_ROOT),
            "--output",
            str(output),
        ],
    )

    assert result.exit_code == 0
    report = json.loads(output.read_text(encoding="utf-8"))
    assert report["configuration"]["reviewed_routing_cases"] == 0
    assert '"grading_metrics"' in result.stdout


def test_eval_trajectory_cli_writes_comparison_report(tmp_path: Path) -> None:
    output = tmp_path / "trajectory.json"
    result = CliRunner().invoke(
        app,
        [
            "eval-trajectory",
            "--root",
            str(PROJECT_ROOT),
            "--output",
            str(output),
        ],
    )

    assert result.exit_code == 0
    report = json.loads(output.read_text(encoding="utf-8"))
    assert report["configuration"]["cases"] == 7
    assert '"retrieval_call_amplification"' in result.stdout


def test_dense_cli_rejects_unimplemented_prefilters_before_model_loading() -> None:
    result = CliRunner().invoke(
        app,
        [
            "eval-retrieval",
            "--root",
            str(PROJECT_ROOT),
            "--retriever",
            "dense",
            "--apply-filters",
        ],
    )

    assert result.exit_code != 0
    assert "does not implement metadata" in result.output
    assert "filters" in result.output


def test_reranked_cli_rejects_candidate_limit_below_output_before_model_loading() -> None:
    result = CliRunner().invoke(
        app,
        [
            "eval-retrieval",
            "--root",
            str(PROJECT_ROOT),
            "--retriever",
            "reranked",
            "--limit",
            "5",
            "--rerank-candidate-limit",
            "3",
        ],
    )

    assert result.exit_code != 0
    assert "must be at least" in result.output


def test_deepseek_cli_refuses_to_claim_results_without_key(monkeypatch) -> None:
    monkeypatch.delenv("DEEPSEEK_API_KEY", raising=False)

    result = CliRunner().invoke(app, ["eval-deepseek", "--root", str(PROJECT_ROOT)])

    assert result.exit_code != 0
    assert "DEEPSEEK_API_KEY is missing" in result.output


def test_e2e_planning_cli_writes_offline_baseline(tmp_path: Path) -> None:
    output = tmp_path / "e2e-planning.json"

    result = CliRunner().invoke(
        app,
        [
            "eval-e2e-planning",
            "--root",
            str(PROJECT_ROOT),
            "--offline",
            "--output",
            str(output),
        ],
    )

    assert result.exit_code == 0
    report = json.loads(output.read_text(encoding="utf-8"))
    assert report["metrics"]["deterministic"]["task_success_rate"] == 1
    assert report["selection"]["status"] == "candidate_not_run"


def test_regression_gate_cli_passes_selected_baseline(tmp_path: Path) -> None:
    output = tmp_path / "gate.json"
    result = CliRunner().invoke(
        app,
        [
            "check-regression-gate",
            "--root",
            str(PROJECT_ROOT),
            "--candidate-variant",
            "deterministic",
            "--output",
            str(output),
        ],
    )

    assert result.exit_code == 0
    assert json.loads(output.read_text())["gate_passed"] is True


def test_regression_gate_cli_writes_diagnostics_then_rejects_paid_no_lift(
    tmp_path: Path,
) -> None:
    output = tmp_path / "gate.json"
    result = CliRunner().invoke(
        app,
        [
            "check-regression-gate",
            "--root",
            str(PROJECT_ROOT),
            "--candidate-variant",
            "deepseek_ranked",
            "--output",
            str(output),
        ],
    )

    assert result.exit_code == 1
    report = json.loads(output.read_text())
    assert report["gate_passed"] is False
    assert report["summary"]["failed_check_count"] == 1


def test_policy_selection_cli_retains_baseline_without_candidate() -> None:
    result = CliRunner().invoke(app, ["select-agentic-policies", "--root", str(PROJECT_ROOT)])

    assert result.exit_code == 0
    payload = json.loads(result.output)
    assert payload["status"] == "baseline_retained"


def test_context_evaluation_cli_writes_trace_report(tmp_path: Path) -> None:
    output = tmp_path / "context.json"
    result = CliRunner().invoke(
        app,
        [
            "eval-context",
            "--root",
            str(PROJECT_ROOT),
            "--output",
            str(output),
        ],
    )

    assert result.exit_code == 0
    report = json.loads(output.read_text(encoding="utf-8"))
    assert report["metrics"]["cases"] == 15
    assert '"estimated_token_reduction_rate"' in result.stdout


def test_context_coverage_cli_writes_ablation_report(tmp_path: Path) -> None:
    output = tmp_path / "coverage.json"
    result = CliRunner().invoke(
        app,
        [
            "eval-context-coverage",
            "--root",
            str(PROJECT_ROOT),
            "--output",
            str(output),
        ],
    )

    assert result.exit_code == 0
    report = json.loads(output.read_text(encoding="utf-8"))
    assert report["experiment"] == "context-priority-vs-coverage-v1"
    assert '"mean_coverage_expected_aspect_coverage"' in result.stdout


def test_context_refinement_cli_writes_controlled_report(tmp_path: Path) -> None:
    output = tmp_path / "refinement.json"
    result = CliRunner().invoke(
        app,
        [
            "eval-context-refinement",
            "--root",
            str(PROJECT_ROOT),
            "--output",
            str(output),
        ],
    )

    assert result.exit_code == 0
    report = json.loads(output.read_text(encoding="utf-8"))
    assert report["selection"]["gate_passed"] is True
    assert '"decision_accuracy"' in result.stdout


def test_memory_cli_writes_isolation_report(tmp_path: Path) -> None:
    output = tmp_path / "memory.json"
    result = CliRunner().invoke(app, ["eval-memory", "--output", str(output)])

    assert result.exit_code == 0
    report = json.loads(output.read_text(encoding="utf-8"))
    assert report["metrics"]["cross_scope_leakage_rate"] == 0
    assert report["selection"]["gate_passed"] is True
