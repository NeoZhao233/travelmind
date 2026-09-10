from pathlib import Path

from travelmind.evaluation.refinement_runner import run_context_refinement_experiment

ROOT = Path(__file__).resolve().parents[1]


def test_controlled_refinement_passes_decision_and_fact_preservation_gates() -> None:
    report = run_context_refinement_experiment(ROOT)
    metrics = report["metrics"]

    assert metrics["cases"] == 7
    assert metrics["decision_accuracy"] == 1
    assert metrics["extractive_critical_fact_preservation"] == 1
    assert metrics["head_critical_fact_preservation"] == 0
    assert metrics["estimated_evidence_token_reduction"] > 0.4
    assert metrics["unresolved_conflicts"] == 1
    assert report["selection"]["gate_passed"] is True
    assert "content" not in str(report["cases"][0]["trace"])
