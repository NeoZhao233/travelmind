from pathlib import Path

from travelmind.evaluation.context_runner import run_final_context_ablation

ROOT = Path(__file__).resolve().parents[1]


def test_final_context_evidence_ablation_selects_without_overclaiming_answers() -> None:
    report = run_final_context_ablation(ROOT)
    metrics = report["metrics"]

    assert report["selection"]["selected_pipeline"] == "refined_coverage"
    assert report["selection"]["evidence_level_gate_passed"] is True
    assert report["selection"]["answer_level_status"] == "not_measured"
    assert metrics["coverage"]["mean_expected_aspect_coverage"] == 1
    assert (
        metrics["refined_coverage"]["mean_relevant_document_recall"]
        >= metrics["coverage"]["mean_relevant_document_recall"]
    )
    assert (
        metrics["refined_coverage"]["mean_estimated_tokens"]
        < metrics["unbounded"]["mean_estimated_tokens"]
    )
