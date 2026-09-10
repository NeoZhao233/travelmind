from __future__ import annotations

import hashlib
from collections import Counter
from pathlib import Path
from typing import Any

from travelmind.agentic.builder import build_agentic_travel_graph
from travelmind.agentic.evaluation_models import DatasetSplit, TrajectoryLabel
from travelmind.agentic.policies import CoverageEvidenceGrader
from travelmind.domain.models import SourceAuthority, SourceDocument
from travelmind.ingestion.dataset import load_jsonl
from travelmind.planner.demo import DemoPlanner
from travelmind.schemas import Evidence, TravelRequest


def _as_evidence(document: SourceDocument) -> Evidence:
    source_type = "guide" if document.authority == SourceAuthority.THIRD_PARTY else "official"
    return Evidence(
        id=document.document_id,
        content=document.content,
        source_url=str(document.source_url),
        source_type=source_type,
        score=1.0,
        retrieved_at=document.collected_at,
        metadata={
            "place_id": document.place_id,
            "source_section": document.section,
            "tags": document.tags,
        },
    )


class _ScriptedRetriever:
    def __init__(self, label: TrajectoryLabel, documents: dict[str, Evidence]) -> None:
        self.label = label
        self.documents = documents
        self.calls = 0

    def search(self, queries: list[str], *, limit: int) -> list[Evidence]:
        del queries
        index = min(self.calls, len(self.label.retrieval_steps) - 1)
        self.calls += 1
        step = self.label.retrieval_steps[index]
        if step.error_type == "TimeoutError":
            raise TimeoutError("injected trajectory timeout")
        return [self.documents[item] for item in step.document_ids][:limit]


def _run_direct(label: TrajectoryLabel, documents: dict[str, Evidence]) -> dict[str, Any]:
    retriever = _ScriptedRetriever(label, documents)
    evidence: list[Evidence] = []
    error_type = None
    try:
        evidence = retriever.search([label.query], limit=10)
    except Exception as exc:
        error_type = type(exc).__name__
    assessment = CoverageEvidenceGrader().grade(TravelRequest(query=label.query), evidence)
    return {
        "completed": assessment.sufficient,
        "retrieval_calls": retriever.calls,
        "rewrite_attempts": 0,
        "degraded": error_type is not None,
        "error_type": error_type,
        "predicted_sufficient": assessment.sufficient,
    }


def _run_agentic(label: TrajectoryLabel, documents: dict[str, Evidence]) -> dict[str, Any]:
    retriever = _ScriptedRetriever(label, documents)
    graph = build_agentic_travel_graph(
        retriever=retriever,
        planner=DemoPlanner(),
        max_retrieval_attempts=len(label.retrieval_steps),
    )
    result = graph.invoke({"request": TravelRequest(query=label.query)})
    return {
        "completed": result["status"] == "completed",
        "retrieval_calls": retriever.calls,
        "rewrite_attempts": result["rewrite_attempts"],
        "degraded": bool(result["degraded_components"]),
        "degraded_components": result["degraded_components"],
        "predicted_sufficient": result["evidence_assessment"].sufficient,
        "trajectory": [event.model_dump(mode="json") for event in result["trajectory"]],
    }


def _summarize(rows: list[dict[str, Any]], system: str) -> dict[str, float | int]:
    task_success = 0
    unsupported = 0
    safe_abstention = 0
    calls = 0
    degraded = 0
    for row in rows:
        outcome = row[system]
        oracle_at_used_step = row[f"{system}_oracle_at_used_step"]
        task_success += outcome["completed"] == row["oracle_eventually_sufficient"]
        unsupported += outcome["completed"] and not oracle_at_used_step
        safe_abstention += not outcome["completed"] and not oracle_at_used_step
        calls += outcome["retrieval_calls"]
        degraded += outcome["degraded"]
    count = len(rows)
    return {
        "cases": count,
        "task_success_rate": task_success / count,
        "unsupported_generation_rate": unsupported / count,
        "safe_abstention_rate": safe_abstention / count,
        "average_retrieval_calls": calls / count,
        "degraded_case_count": degraded,
    }


def run_trajectory_experiment(root: Path) -> dict[str, Any]:
    root = root.resolve()
    labels = load_jsonl(root / "evals/datasets/agentic_trajectory_seed.jsonl", TrajectoryLabel)
    sources = load_jsonl(root / "data/seed/documents.jsonl", SourceDocument)
    documents = {item.document_id: _as_evidence(item) for item in sources}
    counts = Counter(item.case_id for item in labels)
    if duplicates := sorted(item for item, count in counts.items() if count > 1):
        raise ValueError(f"Duplicate trajectory case IDs: {duplicates}")
    if {item.split for item in labels} != set(DatasetSplit):
        raise ValueError("Trajectory labels must contain development and test splits")
    referenced = {
        document_id
        for label in labels
        for step in label.retrieval_steps
        for document_id in step.document_ids
    }
    if missing := sorted(referenced - set(documents)):
        raise ValueError(f"Trajectory labels reference unknown documents: {missing}")

    rows = []
    for label in labels:
        direct = _run_direct(label, documents)
        agentic = _run_agentic(label, documents)
        direct_index = min(direct["retrieval_calls"], len(label.retrieval_steps)) - 1
        agentic_index = min(agentic["retrieval_calls"], len(label.retrieval_steps)) - 1
        rows.append(
            {
                "case_id": label.case_id,
                "split": label.split.value,
                "oracle_first_step_sufficient": label.oracle_sufficient_after_step[0],
                "oracle_eventually_sufficient": label.oracle_sufficient_after_step[-1],
                "direct_oracle_at_used_step": label.oracle_sufficient_after_step[direct_index],
                "agentic_oracle_at_used_step": label.oracle_sufficient_after_step[agentic_index],
                "direct": direct,
                "agentic": agentic,
            }
        )

    direct_metrics = _summarize(rows, "direct")
    agentic_metrics = _summarize(rows, "agentic")
    recovery_cases = [
        row
        for row in rows
        if not row["oracle_first_step_sufficient"] and row["oracle_eventually_sufficient"]
    ]
    agentic_metrics["rewrite_recovery_rate"] = sum(
        row["agentic"]["completed"] for row in recovery_cases
    ) / len(recovery_cases)

    digest = hashlib.sha256()
    for relative in (
        "data/seed/documents.jsonl",
        "evals/datasets/agentic_trajectory_seed.jsonl",
    ):
        digest.update((root / relative).read_bytes())
    return {
        "schema_version": 1,
        "experiment": "controlled-agentic-trajectory-v1",
        "dataset_fingerprint_sha256": digest.hexdigest(),
        "configuration": {
            "cases": len(labels),
            "reviewed_cases": sum(item.reviewed for item in labels),
            "retrieval": "scripted real-document IDs; no ranking latency",
        },
        "direct_metrics": direct_metrics,
        "agentic_metrics": agentic_metrics,
        "retrieval_call_amplification": (
            agentic_metrics["average_retrieval_calls"] / direct_metrics["average_retrieval_calls"]
        ),
        "cases": rows,
        "limitations": [
            "Controlled retrieval isolates orchestration and does not measure Hybrid RRF quality.",
            "Labels are project drafts without independent review.",
            "Harness runtime is not provider or production latency.",
        ],
    }
