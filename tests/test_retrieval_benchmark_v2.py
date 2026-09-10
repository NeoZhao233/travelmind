from pathlib import Path

from travelmind.domain.models import RetrievalExample
from travelmind.evaluation.runner import run_bm25_experiment
from travelmind.ingestion.dataset import load_jsonl, validate_retrieval_dataset

ROOT = Path(__file__).resolve().parents[1]
DATASET = Path("evals/datasets/retrieval_benchmark_v2.jsonl")


def test_v2_benchmark_is_balanced_clustered_and_split_by_intent() -> None:
    summary = validate_retrieval_dataset(ROOT, ROOT / DATASET)
    examples = load_jsonl(ROOT / DATASET, RetrievalExample)

    assert summary.retrieval_examples == 105
    assert summary.intent_clusters == 35
    assert summary.abstention_examples == 30
    assert summary.reviewed_examples == 0
    assert summary.query_types == {
        "semantic": 21,
        "exact": 21,
        "metadata": 21,
        "temporal": 21,
        "multi_constraint": 21,
    }
    assert summary.evaluation_splits == {"development": 45, "test": 60}
    split_by_intent: dict[str, set[str]] = {}
    for example in examples:
        split_by_intent.setdefault(str(example.intent_id), set()).add(example.evaluation_split)
    assert all(len(splits) == 1 for splits in split_by_intent.values())

    review_packet = (ROOT / "evals/annotations/retrieval_benchmark_v2_review.md").read_text()
    assert review_packet.count("- [ ] Independently reviewed and approved") == 35
    assert "- [x] Independently reviewed and approved" not in review_packet


def test_v2_bm25_report_exposes_split_and_effective_cluster_count() -> None:
    report = run_bm25_experiment(ROOT, dataset_path=DATASET)

    assert report["dataset_path"] == DATASET.as_posix()
    assert set(report["metrics_by_split"]) == {"development", "test"}
    assert report["intent_cluster_metrics"]["intent_clusters"] == 35
    assert report["intent_cluster_metrics"]["relevance_intent_clusters"] == 25
    assert report["intent_cluster_metrics"]["abstention_intent_clusters"] == 10
    interval = report["intent_cluster_metrics_by_split"]["test"]["recall_at_5"]
    assert 0 <= interval["lower_95"] <= interval["mean"] <= interval["upper_95"] <= 1
