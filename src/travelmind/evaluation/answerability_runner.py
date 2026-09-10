from __future__ import annotations

import hashlib
from pathlib import Path
from typing import Any

from travelmind.domain.models import RetrievalExample
from travelmind.ingestion.dataset import load_jsonl, validate_retrieval_dataset
from travelmind.retrieval.bm25 import BM25Retriever


def _classification_metrics(rows: list[dict[str, Any]]) -> dict[str, float | int]:
    true_positive = sum(row["answerable"] and row["admitted"] for row in rows)
    false_negative = sum(row["answerable"] and not row["admitted"] for row in rows)
    true_negative = sum(not row["answerable"] and not row["admitted"] for row in rows)
    false_positive = sum(not row["answerable"] and row["admitted"] for row in rows)
    positive_total = true_positive + false_negative
    negative_total = true_negative + false_positive
    answerable_recall = true_positive / positive_total if positive_total else 0.0
    abstention_accuracy = true_negative / negative_total if negative_total else 0.0
    precision = true_positive / (true_positive + false_positive) if true_positive else 0.0
    return {
        "samples": len(rows),
        "true_positive": true_positive,
        "false_negative": false_negative,
        "true_negative": true_negative,
        "false_positive": false_positive,
        "answerable_recall": answerable_recall,
        "abstention_accuracy": abstention_accuracy,
        "balanced_accuracy": (answerable_recall + abstention_accuracy) / 2,
        "precision": precision,
    }


def _threshold_candidates(scores: list[float]) -> list[float]:
    unique = sorted(set(scores))
    if not unique:
        return [0.0]
    boundaries = [
        0.0,
        *[(left + right) / 2 for left, right in zip(unique, unique[1:], strict=False)],
    ]
    return [*boundaries, unique[-1] + 1e-9]


def _select_threshold(rows: list[dict[str, Any]]) -> tuple[float, dict[str, float | int]]:
    candidates = []
    for threshold in _threshold_candidates([float(row["score"]) for row in rows]):
        evaluated = [{**row, "admitted": row["score"] >= threshold} for row in rows]
        metrics = _classification_metrics(evaluated)
        if float(metrics["answerable_recall"]) < 0.8:
            continue
        candidates.append((threshold, metrics))
    if not candidates:
        raise ValueError("no admission threshold preserves development answerable recall")
    return max(
        candidates,
        key=lambda item: (
            float(item[1]["balanced_accuracy"]),
            float(item[1]["answerable_recall"]),
            -item[0],
        ),
    )


def _intent_metrics(rows: list[dict[str, Any]]) -> dict[str, float | int]:
    grouped: dict[str, list[dict[str, Any]]] = {}
    for row in rows:
        grouped.setdefault(str(row["intent_id"]), []).append(row)
    collapsed = []
    for intent_id, cluster in grouped.items():
        collapsed.append(
            {
                "intent_id": intent_id,
                "answerable": cluster[0]["answerable"],
                "admitted": sum(item["admitted"] for item in cluster) >= 2,
            }
        )
    return _classification_metrics(collapsed)


def run_answerability_admission_experiment(root: Path) -> dict[str, Any]:
    root = root.resolve()
    dataset = root / "evals/datasets/retrieval_benchmark_v2.jsonl"
    validate_retrieval_dataset(root, dataset)
    examples = load_jsonl(dataset, RetrievalExample)
    retriever = BM25Retriever.from_project(root)
    scored = []
    for example in examples:
        response = retriever.rank(example.query, limit=1)
        scored.append(
            {
                "query_id": example.query_id,
                "intent_id": example.intent_id,
                "split": example.evaluation_split,
                "answerable": not example.should_abstain,
                "score": response.hits[0].score if response.hits else 0.0,
                "top_document_id": response.hits[0].document_id if response.hits else None,
            }
        )
    development = [row for row in scored if row["split"] == "development"]
    threshold, development_metrics = _select_threshold(development)
    evaluated = [{**row, "admitted": row["score"] >= threshold} for row in scored]
    by_split = {
        split: _classification_metrics([row for row in evaluated if row["split"] == split])
        for split in ("development", "test")
    }
    intent_by_split = {
        split: _intent_metrics([row for row in evaluated if row["split"] == split])
        for split in ("development", "test")
    }
    test_metrics = by_split["test"]
    quality_gates_passed = (
        float(test_metrics["answerable_recall"]) >= 0.8
        and float(test_metrics["abstention_accuracy"]) >= 0.8
        and float(test_metrics["balanced_accuracy"]) > 0.5
    )
    return {
        "schema_version": 1,
        "experiment": "stage12-development-tuned-lexical-admission-v1",
        "dataset_sha256": hashlib.sha256(dataset.read_bytes()).hexdigest(),
        "configuration": {
            "score": "top1 in-process BM25 raw score",
            "selection_split": "development",
            "evaluation_split": "test",
            "minimum_development_answerable_recall": 0.8,
            "selected_threshold": threshold,
        },
        "always_admit_baseline": {
            "answerable_recall": 1.0,
            "abstention_accuracy": 0.0,
            "balanced_accuracy": 0.5,
        },
        "development_metrics": development_metrics,
        "metrics_by_split": by_split,
        "intent_metrics_by_split": intent_by_split,
        "selection": {
            "status": (
                "blocked_pending_human_review" if quality_gates_passed else "candidate_rejected"
            ),
            "gates": {
                "test_answerable_recall_at_least_80pct": (
                    float(test_metrics["answerable_recall"]) >= 0.8
                ),
                "test_abstention_accuracy_at_least_80pct": (
                    float(test_metrics["abstention_accuracy"]) >= 0.8
                ),
                "test_balanced_accuracy_above_always_admit": (
                    float(test_metrics["balanced_accuracy"]) > 0.5
                ),
                "labels_independently_reviewed": False,
            },
        },
        "cases": evaluated,
        "limitations": [
            "Labels are Codex-authored drafts with no independent human review.",
            "The threshold is corpus- and tokenizer-specific and must be recalibrated after "
            "indexing changes.",
            "Lexical admission complements evidence grading; it does not prove semantic "
            "entailment.",
        ],
    }
