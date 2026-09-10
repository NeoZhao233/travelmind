from __future__ import annotations

import hashlib
from pathlib import Path
from typing import Any

from pydantic import BaseModel, Field

from travelmind.context.models import ContextItem, ContextKind
from travelmind.context.refinement import EvidenceRefiner
from travelmind.context.tokenization import HeuristicTokenEstimator


class RefinementItemCase(BaseModel):
    id: str
    content: str
    priority: int = Field(ge=0, le=100)
    metadata: dict[str, str] = Field(default_factory=dict)


class RefinementCase(BaseModel):
    case_id: str
    targets: list[str]
    items: list[RefinementItemCase]
    expected_kept_ids: list[str]
    expected_conflict_status: str | None = None
    critical_phrases: list[str] = Field(default_factory=list)
    compression_case: bool = False


def _load_cases(path: Path) -> list[RefinementCase]:
    cases = [
        RefinementCase.model_validate_json(line)
        for line in path.read_text(encoding="utf-8").splitlines()
        if line.strip()
    ]
    identities = [case.case_id for case in cases]
    if len(identities) != len(set(identities)):
        raise ValueError("Duplicate context refinement case IDs")
    return cases


def _head_clip(text: str, target: int, estimator: HeuristicTokenEstimator) -> str:
    low, high, best = 1, len(text), text[:1]
    while low <= high:
        midpoint = (low + high) // 2
        candidate = text[:midpoint] + "…"
        if estimator.estimate(candidate) <= target:
            best = candidate
            low = midpoint + 1
        else:
            high = midpoint - 1
    return best


def run_context_refinement_experiment(
    root: Path,
    *,
    compression_target_tokens: int = 45,
    duplicate_threshold: float = 0.92,
) -> dict[str, Any]:
    root = root.resolve()
    dataset = root / "evals/datasets/context_refinement_seed.jsonl"
    cases = _load_cases(dataset)
    estimator = HeuristicTokenEstimator()
    refiner = EvidenceRefiner(
        compression_target_tokens=compression_target_tokens,
        duplicate_threshold=duplicate_threshold,
        estimator=estimator,
    )
    rows = []
    for case in cases:
        items = [
            ContextItem(
                item_id=f"evidence:{item.id}",
                kind=ContextKind.EVIDENCE,
                content=item.content,
                priority=item.priority,
                metadata={"document_id": item.id, **item.metadata},
            )
            for item in case.items
        ]
        result = refiner.refine(items, set(case.targets))
        actual_ids = [item.metadata["document_id"] for item in result.items]
        conflict_statuses = [item.status for item in result.trace.conflicts]
        actual_status = conflict_statuses[0] if conflict_statuses else None
        refined_text = " ".join(item.content for item in result.items)
        head_text = " ".join(
            _head_clip(item.content, compression_target_tokens, estimator) for item in items
        )
        rows.append(
            {
                "case_id": case.case_id,
                "decision_correct": (
                    set(actual_ids) == set(case.expected_kept_ids)
                    and actual_status == case.expected_conflict_status
                ),
                "actual_kept_ids": actual_ids,
                "conflict_status": actual_status,
                "compression_case": case.compression_case,
                "head_critical_facts_preserved": sum(
                    phrase in head_text for phrase in case.critical_phrases
                ),
                "extractive_critical_facts_preserved": sum(
                    phrase in refined_text for phrase in case.critical_phrases
                ),
                "critical_fact_count": len(case.critical_phrases),
                "trace": result.trace.model_dump(mode="json"),
            }
        )
    compression_rows = [row for row in rows if row["compression_case"]]
    fact_count = sum(row["critical_fact_count"] for row in compression_rows)
    before = sum(row["trace"]["estimated_evidence_tokens_before"] for row in rows)
    after = sum(row["trace"]["estimated_evidence_tokens_after"] for row in rows)
    metrics = {
        "cases": len(rows),
        "decision_accuracy": sum(row["decision_correct"] for row in rows) / len(rows),
        "head_critical_fact_preservation": sum(
            row["head_critical_facts_preserved"] for row in compression_rows
        )
        / fact_count,
        "extractive_critical_fact_preservation": sum(
            row["extractive_critical_facts_preserved"] for row in compression_rows
        )
        / fact_count,
        "estimated_evidence_token_reduction": 1 - after / before,
        "duplicate_groups": sum(len(row["trace"]["duplicate_groups"]) for row in rows),
        "resolved_conflicts": sum(
            conflict["status"] == "resolved"
            for row in rows
            for conflict in row["trace"]["conflicts"]
        ),
        "unresolved_conflicts": sum(
            conflict["status"] == "unresolved"
            for row in rows
            for conflict in row["trace"]["conflicts"]
        ),
    }
    gate_passed = (
        metrics["decision_accuracy"] == 1
        and metrics["extractive_critical_fact_preservation"] == 1
        and metrics["extractive_critical_fact_preservation"]
        > metrics["head_critical_fact_preservation"]
        and metrics["estimated_evidence_token_reduction"] > 0
    )
    return {
        "schema_version": 1,
        "experiment": "context-refinement-controlled-v1",
        "dataset_fingerprint_sha256": hashlib.sha256(dataset.read_bytes()).hexdigest(),
        "configuration": {
            "compression_target_tokens": compression_target_tokens,
            "duplicate_threshold": duplicate_threshold,
            "estimator": estimator.name,
        },
        "metrics": metrics,
        "selection": {
            "selected_policy": "deterministic-refinement-v1" if gate_passed else "none",
            "gate_passed": gate_passed,
        },
        "cases": rows,
        "limitations": [
            "The controlled seven-case seed isolates behavior but is not a natural traffic set.",
            "Near-duplicate matching is lexical and does not detect paraphrases.",
            "Conflict resolution requires trustworthy authority and observation metadata.",
            "Extractive compression preserves text spans, not full answer faithfulness.",
        ],
    }
