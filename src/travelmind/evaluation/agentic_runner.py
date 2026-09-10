from __future__ import annotations

import hashlib
from collections import Counter
from datetime import UTC, datetime
from pathlib import Path
from typing import Any

from travelmind.agentic.evaluation_models import (
    DatasetSplit,
    EvidenceGradingLabel,
    RoutingLabel,
)
from travelmind.agentic.policies import CoverageEvidenceGrader, RuleBasedQueryRouter
from travelmind.domain.models import RetrievalExample, SourceAuthority, SourceDocument
from travelmind.ingestion.dataset import load_jsonl
from travelmind.schemas import Evidence, TravelRequest

_AGENTIC_DATASET_PATHS = (
    "data/seed/documents.jsonl",
    "evals/datasets/retrieval_seed.jsonl",
    "evals/datasets/agentic_routing_seed.jsonl",
    "evals/datasets/agentic_grading_seed.jsonl",
)
_POLICY_VERSION = "rule-v1"


def _fingerprint(root: Path) -> str:
    digest = hashlib.sha256()
    for relative_path in _AGENTIC_DATASET_PATHS:
        digest.update(relative_path.encode())
        digest.update(b"\0")
        digest.update((root / relative_path).read_bytes())
        digest.update(b"\0")
    return digest.hexdigest()


def _ensure_unique(values: list[str], *, label: str) -> None:
    duplicates = sorted(item for item, count in Counter(values).items() if count > 1)
    if duplicates:
        raise ValueError(f"Duplicate {label}: {duplicates}")


def _classification_metrics(expected: list[bool], predicted: list[bool]) -> dict[str, float]:
    pairs = zip(expected, predicted, strict=True)
    true_positive = sum(wanted and actual for wanted, actual in pairs)
    true_negative = sum(
        not wanted and not actual for wanted, actual in zip(expected, predicted, strict=True)
    )
    false_positive = sum(
        not wanted and actual for wanted, actual in zip(expected, predicted, strict=True)
    )
    false_negative = sum(
        wanted and not actual for wanted, actual in zip(expected, predicted, strict=True)
    )
    predicted_positive = true_positive + false_positive
    actual_positive = true_positive + false_negative
    precision = true_positive / predicted_positive if predicted_positive else 0.0
    recall = true_positive / actual_positive if actual_positive else 0.0
    return {
        "accuracy": (true_positive + true_negative) / len(expected),
        "precision": precision,
        "recall": recall,
        "f1": 2 * precision * recall / (precision + recall) if precision + recall else 0.0,
    }


def _source_to_evidence(document: SourceDocument) -> Evidence:
    source_type = "guide" if document.authority == SourceAuthority.THIRD_PARTY else "official"
    return Evidence(
        id=document.document_id,
        content=document.content,
        source_url=str(document.source_url),
        source_type=source_type,
        score=1.0,
        retrieved_at=document.collected_at,
        metadata={
            "document_id": document.document_id,
            "place_id": document.place_id,
            "source_title": document.title,
            "source_section": document.section,
            "tags": document.tags,
        },
    )


def run_deterministic_agentic_policy_experiment(root: Path) -> dict[str, Any]:
    root = root.resolve()
    retrieval_examples = load_jsonl(root / "evals/datasets/retrieval_seed.jsonl", RetrievalExample)
    routing_labels = load_jsonl(root / "evals/datasets/agentic_routing_seed.jsonl", RoutingLabel)
    grading_labels = load_jsonl(
        root / "evals/datasets/agentic_grading_seed.jsonl", EvidenceGradingLabel
    )
    documents = load_jsonl(root / "data/seed/documents.jsonl", SourceDocument)
    _ensure_unique([item.case_id for item in routing_labels], label="routing case IDs")
    _ensure_unique([item.case_id for item in grading_labels], label="grading case IDs")

    retrieval_by_id = {item.query_id: item for item in retrieval_examples}
    document_by_id = {item.document_id: item for item in documents}
    missing_queries = sorted(
        {item.retrieval_query_id for item in routing_labels} - set(retrieval_by_id)
    )
    missing_documents = sorted(
        {document_id for item in grading_labels for document_id in item.evidence_document_ids}
        - set(document_by_id)
    )
    if missing_queries:
        raise ValueError(f"Routing labels reference unknown queries: {missing_queries}")
    if missing_documents:
        raise ValueError(f"Grading labels reference unknown documents: {missing_documents}")
    if {item.split for item in routing_labels} != set(DatasetSplit):
        raise ValueError("Routing labels must contain development and test splits")
    if {item.split for item in grading_labels} != set(DatasetSplit):
        raise ValueError("Grading labels must contain development and test splits")

    router = RuleBasedQueryRouter()
    routing_rows = []
    confusion: Counter[str] = Counter()
    for label in routing_labels:
        query = retrieval_by_id[label.retrieval_query_id].query
        decision = router.route(TravelRequest(query=query))
        correct = decision.intent == label.expected_intent
        confusion[f"{label.expected_intent.value}->{decision.intent.value}"] += 1
        routing_rows.append(
            {
                "case_id": label.case_id,
                "split": label.split.value,
                "expected_intent": label.expected_intent.value,
                "predicted_intent": decision.intent.value,
                "correct": correct,
                "reason_codes": decision.reason_codes,
            }
        )

    grader = CoverageEvidenceGrader()
    grading_rows = []
    for label in grading_labels:
        evidence = [
            _source_to_evidence(document_by_id[document_id])
            for document_id in label.evidence_document_ids
        ]
        assessment = grader.grade(TravelRequest(query=label.query), evidence)
        grading_rows.append(
            {
                "case_id": label.case_id,
                "split": label.split.value,
                "expected_sufficient": label.expected_sufficient,
                "predicted_sufficient": assessment.sufficient,
                "classification_correct": assessment.sufficient == label.expected_sufficient,
                "expected_required_aspects": label.expected_required_aspects,
                "predicted_required_aspects": assessment.required_aspects,
                "required_aspects_exact_match": set(assessment.required_aspects)
                == set(label.expected_required_aspects),
                "expected_missing_aspects": label.expected_missing_aspects,
                "predicted_missing_aspects": assessment.missing_aspects,
                "missing_aspects_exact_match": set(assessment.missing_aspects)
                == set(label.expected_missing_aspects),
                "reason_codes": assessment.reason_codes,
            }
        )

    routing_metrics: dict[str, Any] = {}
    grading_metrics: dict[str, Any] = {}
    for split_name in ("all", DatasetSplit.DEVELOPMENT.value, DatasetSplit.TEST.value):
        route_subset = [
            row for row in routing_rows if split_name == "all" or row["split"] == split_name
        ]
        grade_subset = [
            row for row in grading_rows if split_name == "all" or row["split"] == split_name
        ]
        routing_metrics[split_name] = {
            "cases": len(route_subset),
            "accuracy": sum(row["correct"] for row in route_subset) / len(route_subset),
        }
        expected = [row["expected_sufficient"] for row in grade_subset]
        predicted = [row["predicted_sufficient"] for row in grade_subset]
        grading_metrics[split_name] = {
            "cases": len(grade_subset),
            **_classification_metrics(expected, predicted),
            "required_aspects_exact_match": sum(
                row["required_aspects_exact_match"] for row in grade_subset
            )
            / len(grade_subset),
            "missing_aspects_exact_match": sum(
                row["missing_aspects_exact_match"] for row in grade_subset
            )
            / len(grade_subset),
        }

    return {
        "schema_version": 1,
        "experiment": "deterministic-agentic-policy-baseline",
        "generated_at": datetime.now(UTC).isoformat(),
        "dataset_fingerprint_sha256": _fingerprint(root),
        "configuration": {
            "policy_version": _POLICY_VERSION,
            "router": "RuleBasedQueryRouter",
            "grader": "CoverageEvidenceGrader",
            "routing_cases": len(routing_labels),
            "grading_cases": len(grading_labels),
            "reviewed_routing_cases": sum(item.reviewed for item in routing_labels),
            "reviewed_grading_cases": sum(item.reviewed for item in grading_labels),
        },
        "routing_metrics": routing_metrics,
        "routing_confusion": dict(sorted(confusion.items())),
        "grading_metrics": grading_metrics,
        "routing_cases": routing_rows,
        "grading_cases": grading_rows,
        "limitations": [
            (
                "All agentic policy labels are project drafts and have not been "
                "independently reviewed."
            ),
            "The test split is fixed for plumbing but is not blind to the dataset author.",
            "The seed is too small for statistical significance or prompt/model selection claims.",
            "This run evaluates deterministic routing and grading only, not rewrite recovery.",
            "No LLM, token cost, or provider latency is measured in this baseline.",
        ],
    }
