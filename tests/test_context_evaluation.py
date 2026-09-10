from pathlib import Path

from travelmind.evaluation.context_runner import (
    run_context_budget_experiment,
    run_context_budget_sweep,
    run_context_coverage_experiment,
)

ROOT = Path(__file__).resolve().parents[1]


def test_context_experiment_reports_budget_quality_tradeoff_without_prompt_text() -> None:
    report = run_context_budget_experiment(ROOT)

    assert report["metrics"]["cases"] == 15
    assert report["metrics"]["estimated_token_reduction_rate"] > 0
    assert report["metrics"]["mandatory_preservation_rate"] == 1
    assert all(
        row["budgeted_estimated_tokens"] <= report["configuration"]["max_context_tokens"]
        for row in report["cases"]
    )
    assert "rendered" not in report["cases"][0]
    assert "content" not in str(report["cases"][0]["trace"])


def test_budget_sweep_selects_smallest_configuration_passing_recall_gate() -> None:
    report = run_context_budget_sweep(ROOT)

    assert report["selected_max_context_tokens"] == 768
    assert len(report["runs"]) == 4


def test_coverage_packing_improves_stress_budget_without_recall_regression() -> None:
    report = run_context_coverage_experiment(
        ROOT,
        max_context_tokens=768,
        reserved_output_tokens=192,
        safety_margin_tokens=64,
    )
    metrics = report["metrics"]

    assert (
        metrics["mean_coverage_relevant_document_recall"]
        > metrics["mean_priority_relevant_document_recall"]
    )
    assert metrics["multi_constraint_coverage_expected_aspect_coverage"] == 1
    assert metrics["recall_regressed_cases"] == 0
    assert metrics["mandatory_preservation_rate"] == 1
    assert "expected_fact_types" not in report["selector_inputs"]
    assert report["selection"] == {
        "selected_policy": "bounded-aspect-gain-v1",
        "gate_passed": True,
        "gate": (
            "mandatory preservation 1.0; zero per-case recall regressions; mean recall "
            "non-decreasing; mean expected-aspect coverage strictly increasing"
        ),
    }
