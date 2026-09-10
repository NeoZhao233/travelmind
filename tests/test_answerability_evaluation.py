from pathlib import Path

from travelmind.evaluation.answerability_runner import run_answerability_admission_experiment

ROOT = Path(__file__).resolve().parents[1]


def test_admission_threshold_is_tuned_on_development_and_evaluated_on_test() -> None:
    report = run_answerability_admission_experiment(ROOT)
    test_metrics = report["metrics_by_split"]["test"]

    assert report["configuration"]["selection_split"] == "development"
    assert report["configuration"]["evaluation_split"] == "test"
    assert test_metrics["answerable_recall"] >= 0.8
    assert test_metrics["abstention_accuracy"] >= 0.8
    assert test_metrics["balanced_accuracy"] > 0.5


def test_passing_quality_gates_does_not_bypass_missing_human_review() -> None:
    report = run_answerability_admission_experiment(ROOT)

    assert report["selection"]["status"] == "blocked_pending_human_review"
    assert report["selection"]["gates"]["labels_independently_reviewed"] is False
