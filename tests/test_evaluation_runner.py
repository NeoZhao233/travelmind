from pathlib import Path

from travelmind.evaluation.runner import run_bm25_experiment

PROJECT_ROOT = Path(__file__).resolve().parents[1]


def test_bm25_experiment_is_fingerprinted_and_bounded() -> None:
    report = run_bm25_experiment(PROJECT_ROOT)

    assert report["dataset_summary"]["retrieval_examples"] == 15
    assert len(report["dataset_fingerprint_sha256"]) == 64
    assert report["latency_ms"]["samples"] == 15
    assert len(report["per_query"]) == 15
    assert set(report["metrics_by_query_type"]) == {
        "exact",
        "metadata",
        "multi_constraint",
        "semantic",
        "temporal",
    }
    for metric in ("precision_at_k", "recall_at_k", "mrr_at_k", "ndcg_at_k"):
        assert all(0 <= value <= 1 for value in report["metrics"][metric].values())


def test_filtered_experiment_records_filter_mode_and_unsupported_keys() -> None:
    report = run_bm25_experiment(PROJECT_ROOT, apply_filters=True)

    assert report["configuration"]["apply_supported_metadata_filters"] is True
    assert report["unsupported_filter_counts"]["weekday"] == 4
