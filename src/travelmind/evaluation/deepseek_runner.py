from __future__ import annotations

import hashlib
from pathlib import Path
from typing import Any

from travelmind.agentic.evaluation_models import (
    DatasetSplit,
    EvidenceGradingLabel,
    RoutingLabel,
)
from travelmind.agentic.llm_policies import (
    LLMEvidenceGrader,
    LLMPolicyTelemetry,
    LLMQueryRouter,
)
from travelmind.agentic.llm_provider import StructuredLLMProvider
from travelmind.agentic.policies import CoverageEvidenceGrader, RuleBasedQueryRouter
from travelmind.domain.models import RetrievalExample, SourceAuthority, SourceDocument
from travelmind.ingestion.dataset import load_jsonl
from travelmind.schemas import Evidence, TravelRequest


def _evidence(document: SourceDocument) -> Evidence:
    return Evidence(
        id=document.document_id,
        content=document.content,
        source_url=str(document.source_url),
        source_type=("guide" if document.authority == SourceAuthority.THIRD_PARTY else "official"),
        score=1,
        retrieved_at=document.collected_at,
        metadata={"source_section": document.section, "tags": document.tags},
    )


def _accuracy(rows: list[dict[str, Any]], split: str) -> dict[str, float | int]:
    selected = [row for row in rows if split == "all" or row["split"] == split]
    return {
        "cases": len(selected),
        "accuracy": sum(row["correct"] for row in selected) / len(selected),
    }


def _binary(rows: list[dict[str, Any]], split: str) -> dict[str, float | int]:
    selected = [row for row in rows if split == "all" or row["split"] == split]
    tp = sum(row["expected"] and row["predicted"] for row in selected)
    fp = sum(not row["expected"] and row["predicted"] for row in selected)
    fn = sum(row["expected"] and not row["predicted"] for row in selected)
    precision = tp / (tp + fp) if tp + fp else 0.0
    recall = tp / (tp + fn) if tp + fn else 0.0
    return {
        "cases": len(selected),
        "accuracy": sum(row["correct"] for row in selected) / len(selected),
        "precision": precision,
        "recall": recall,
        "f1": 2 * precision * recall / (precision + recall) if precision + recall else 0.0,
    }


def run_deepseek_policy_experiment(root: Path, provider: StructuredLLMProvider) -> dict[str, Any]:
    root = root.resolve()
    routing_labels = load_jsonl(root / "evals/datasets/agentic_routing_seed.jsonl", RoutingLabel)
    grading_labels = load_jsonl(
        root / "evals/datasets/agentic_grading_seed.jsonl", EvidenceGradingLabel
    )
    queries = {
        item.query_id: item
        for item in load_jsonl(root / "evals/datasets/retrieval_seed.jsonl", RetrievalExample)
    }
    documents = {
        item.document_id: item
        for item in load_jsonl(root / "data/seed/documents.jsonl", SourceDocument)
    }
    telemetry = LLMPolicyTelemetry()
    llm_router = LLMQueryRouter(provider, telemetry)
    llm_grader = LLMEvidenceGrader(provider, telemetry)
    fallback_router = RuleBasedQueryRouter()
    fallback_grader = CoverageEvidenceGrader()

    routing_rows = []
    for label in routing_labels:
        request = TravelRequest(query=queries[label.retrieval_query_id].query)
        fallback = False
        try:
            decision = llm_router.route(request)
        except Exception:
            decision = fallback_router.route(request)
            fallback = True
        routing_rows.append(
            {
                "case_id": label.case_id,
                "split": label.split.value,
                "expected": label.expected_intent.value,
                "predicted": decision.intent.value,
                "correct": decision.intent == label.expected_intent,
                "fallback": fallback,
            }
        )

    grading_rows = []
    for label in grading_labels:
        request = TravelRequest(query=label.query)
        evidence = [_evidence(documents[item]) for item in label.evidence_document_ids]
        fallback = False
        try:
            assessment = llm_grader.grade(request, evidence)
        except Exception:
            assessment = fallback_grader.grade(request, evidence)
            fallback = True
        grading_rows.append(
            {
                "case_id": label.case_id,
                "split": label.split.value,
                "expected": label.expected_sufficient,
                "predicted": assessment.sufficient,
                "correct": assessment.sufficient == label.expected_sufficient,
                "fallback": fallback,
            }
        )

    calls = telemetry.calls
    successful = [item for item in calls if item.success]
    metrics_splits = ("all", DatasetSplit.DEVELOPMENT.value, DatasetSplit.TEST.value)
    digest = hashlib.sha256()
    for relative in (
        "data/seed/documents.jsonl",
        "evals/datasets/retrieval_seed.jsonl",
        "evals/datasets/agentic_routing_seed.jsonl",
        "evals/datasets/agentic_grading_seed.jsonl",
    ):
        digest.update((root / relative).read_bytes())
    return {
        "schema_version": 1,
        "experiment": "deepseek-policy-with-deterministic-fallback",
        "dataset_fingerprint_sha256": digest.hexdigest(),
        "configuration": {
            "response_format": "json_object",
            "thinking": "disabled",
            "router_prompt_version": "router-v2-nonthinking",
            "grader_prompt_version": "grader-v3-explicit-scope",
        },
        "routing_metrics": {split: _accuracy(routing_rows, split) for split in metrics_splits},
        "grading_metrics": {split: _binary(grading_rows, split) for split in metrics_splits},
        "telemetry": {
            "calls": len(calls),
            "successful_calls": len(successful),
            "fallback_rate": 1 - len(successful) / len(calls),
            "total_tokens": sum(item.total_tokens for item in calls),
            "post_provider_validation_failures": sum(
                not item.success and item.model is not None for item in calls
            ),
            "mean_success_latency_ms": (
                sum(item.latency_ms or 0 for item in successful) / len(successful)
                if successful
                else None
            ),
            "by_component": {
                component: {
                    "calls": sum(item.component == component for item in calls),
                    "failures": sum(
                        item.component == component and not item.success for item in calls
                    ),
                }
                for component in ("query_router", "evidence_grader")
            },
        },
        "routing_cases": routing_rows,
        "grading_cases": grading_rows,
        "policy_calls": [item.model_dump(mode="json") for item in calls],
        "limitations": [
            "Labels are small project-authored drafts and the test split is not blind.",
            "Rewriter quality requires a separate end-to-end trajectory experiment.",
            "Fallback-inclusive quality must be read with raw fallback rate.",
        ],
    }
