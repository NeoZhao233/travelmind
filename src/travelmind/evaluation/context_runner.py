from __future__ import annotations

import hashlib
import json
from pathlib import Path
from time import perf_counter
from typing import Any

from travelmind.context.builder import (
    BaselineContextBuilder,
    BudgetedContextBuilder,
    CoverageAwareContextBuilder,
    build_context_items,
)
from travelmind.context.coverage import decode_aspects, encode_aspects, infer_coverage_targets
from travelmind.context.models import ContextBudget, ContextItem, ContextKind
from travelmind.context.pipeline import RefinedCoverageContextBuilder
from travelmind.domain.models import (
    FactRecord,
    RetrievalExample,
    SourceAuthority,
    SourceDocument,
)
from travelmind.ingestion.dataset import load_jsonl
from travelmind.schemas import Evidence, TravelRequest


def _as_evidence(
    document: SourceDocument,
    score: float,
    aspects: set[str] | None = None,
) -> Evidence:
    return Evidence(
        id=document.document_id,
        content=document.content,
        source_url=str(document.source_url),
        source_type=("guide" if document.authority == SourceAuthority.THIRD_PARTY else "official"),
        score=score,
        retrieved_at=document.collected_at,
        metadata={
            "document_id": document.document_id,
            "aspects": encode_aspects(aspects or set()),
        },
    )


def _mean(values: list[float | int]) -> float:
    return sum(values) / len(values)


def run_context_budget_experiment(
    root: Path,
    *,
    max_context_tokens: int = 768,
    reserved_output_tokens: int = 192,
    safety_margin_tokens: int = 64,
    max_tokens_per_evidence: int = 160,
) -> dict[str, Any]:
    root = root.resolve()
    budget = ContextBudget(
        max_context_tokens=max_context_tokens,
        reserved_output_tokens=reserved_output_tokens,
        safety_margin_tokens=safety_margin_tokens,
        max_tokens_per_evidence=max_tokens_per_evidence,
    )
    examples = load_jsonl(root / "evals/datasets/retrieval_seed.jsonl", RetrievalExample)
    documents = {
        item.document_id: item
        for item in load_jsonl(root / "data/seed/documents.jsonl", SourceDocument)
    }
    retrieval_report = json.loads(
        (root / "evals/results/hybrid_rrf_seed.json").read_text(encoding="utf-8")
    )
    ranking_by_id = {
        item["query_id"]: item["ranked_scores"] for item in retrieval_report["per_query"]
    }
    baseline_builder = BaselineContextBuilder()
    budgeted_builder = BudgetedContextBuilder(budget)
    rows = []
    for example in examples:
        ranked = ranking_by_id[example.query_id]
        evidence = [
            _as_evidence(documents[item["document_id"]], float(item["score"])) for item in ranked
        ]
        items = build_context_items(TravelRequest(query=example.query), evidence)
        if example.hard_filters:
            items.insert(
                2,
                ContextItem(
                    item_id="retrieval-hard-filters",
                    kind=ContextKind.CONSTRAINTS,
                    content=json.dumps(example.hard_filters, ensure_ascii=False, sort_keys=True),
                    priority=100,
                    mandatory=True,
                ),
            )
        baseline = baseline_builder.build(items)
        budgeted = budgeted_builder.build(items)
        relevant = set(example.relevant_documents)
        baseline_documents = {
            item.metadata["document_id"]
            for item in baseline.items
            if item.kind == ContextKind.EVIDENCE
        }
        budgeted_documents = {
            item.metadata["document_id"]
            for item in budgeted.items
            if item.kind == ContextKind.EVIDENCE
        }
        denominator = len(relevant) or 1
        rows.append(
            {
                "query_id": example.query_id,
                "query_type": example.query_type.value,
                "baseline_estimated_tokens": baseline.trace.estimated_input_tokens_after,
                "budgeted_estimated_tokens": budgeted.trace.estimated_input_tokens_after,
                "baseline_evidence_count": len(baseline_documents),
                "budgeted_evidence_count": len(budgeted_documents),
                "baseline_relevant_document_recall": len(baseline_documents & relevant)
                / denominator,
                "budgeted_relevant_document_recall": len(budgeted_documents & relevant)
                / denominator,
                "mandatory_preserved": all(
                    item.item_id in budgeted.trace.included_item_ids
                    for item in items
                    if item.mandatory
                ),
                "trace": budgeted.trace.model_dump(mode="json"),
            }
        )

    baseline_tokens = [row["baseline_estimated_tokens"] for row in rows]
    budgeted_tokens = [row["budgeted_estimated_tokens"] for row in rows]
    digest = hashlib.sha256()
    for relative in (
        "data/seed/documents.jsonl",
        "evals/datasets/retrieval_seed.jsonl",
        "evals/results/hybrid_rrf_seed.json",
    ):
        digest.update((root / relative).read_bytes())
    return {
        "schema_version": 1,
        "experiment": "context-baseline-vs-fixed-budget-v1",
        "dataset_fingerprint_sha256": digest.hexdigest(),
        "configuration": budget.model_dump(mode="json"),
        "estimator": baseline_builder.estimator.name,
        "metrics": {
            "cases": len(rows),
            "mean_baseline_estimated_input_tokens": _mean(baseline_tokens),
            "mean_budgeted_estimated_input_tokens": _mean(budgeted_tokens),
            "estimated_token_reduction_rate": 1 - _mean(budgeted_tokens) / _mean(baseline_tokens),
            "mean_baseline_evidence_count": _mean([row["baseline_evidence_count"] for row in rows]),
            "mean_budgeted_evidence_count": _mean([row["budgeted_evidence_count"] for row in rows]),
            "mean_baseline_relevant_document_recall": _mean(
                [row["baseline_relevant_document_recall"] for row in rows]
            ),
            "mean_budgeted_relevant_document_recall": _mean(
                [row["budgeted_relevant_document_recall"] for row in rows]
            ),
            "mandatory_preservation_rate": _mean([row["mandatory_preserved"] for row in rows]),
            "queries_with_clipping": sum(bool(row["trace"]["clipped_item_ids"]) for row in rows),
            "queries_with_drops": sum(bool(row["trace"]["dropped_item_ids"]) for row in rows),
        },
        "cases": rows,
        "limitations": [
            "Token counts use a conservative heuristic, not the DeepSeek tokenizer.",
            (
                "Relevant-document recall does not measure answer faithfulness or citation "
                "correctness."
            ),
            "The fixed budget preserves retrieval order; coverage-aware selection is Stage 4C.",
            "The 15-query seed is too small for production sizing claims.",
        ],
    }


def run_context_budget_sweep(root: Path) -> dict[str, Any]:
    configurations = (
        (512, 128, 48),
        (768, 192, 64),
        (1024, 256, 96),
        (1536, 384, 128),
    )
    runs = [
        run_context_budget_experiment(
            root,
            max_context_tokens=max_context,
            reserved_output_tokens=output_reserve,
            safety_margin_tokens=margin,
        )
        for max_context, output_reserve, margin in configurations
    ]
    eligible = [
        run
        for run in runs
        if run["metrics"]["mandatory_preservation_rate"] == 1
        and run["metrics"]["mean_budgeted_relevant_document_recall"] >= 0.9
    ]
    selected = min(eligible, key=lambda run: run["configuration"]["max_context_tokens"])
    return {
        "schema_version": 1,
        "experiment": "context-budget-sweep-v1",
        "selection_rule": (
            "smallest max_context_tokens with mandatory preservation 1.0 and mean relevant "
            "document recall at least 0.9"
        ),
        "selected_max_context_tokens": selected["configuration"]["max_context_tokens"],
        "selected_configuration": selected["configuration"],
        "runs": [
            {"configuration": run["configuration"], "metrics": run["metrics"]} for run in runs
        ],
        "limitations": [
            "The 0.9 recall threshold is an initial engineering gate, not a calibrated SLA.",
            "Counts are heuristic estimates and need calibration against provider usage.",
        ],
    }


def _document_aspects(root: Path) -> dict[str, set[str]]:
    aspects: dict[str, set[str]] = {}
    for fact in load_jsonl(root / "data/seed/facts.jsonl", FactRecord):
        aspects.setdefault(fact.document_id, set()).add(fact.fact_type.value)
    return aspects


def _selected_evidence(packed: Any) -> list[ContextItem]:
    return [item for item in packed.items if item.kind == ContextKind.EVIDENCE]


def _aspect_coverage(selected: list[ContextItem], targets: set[str]) -> float:
    if not targets:
        return 1.0
    covered = set().union(*(decode_aspects(item.metadata.get("aspects")) for item in selected))
    return len(covered & targets) / len(targets)


def run_context_coverage_experiment(
    root: Path,
    *,
    max_context_tokens: int = 768,
    reserved_output_tokens: int = 192,
    safety_margin_tokens: int = 64,
    max_tokens_per_evidence: int = 160,
) -> dict[str, Any]:
    """Compare rank-order packing with coverage-aware packing on identical candidates."""

    root = root.resolve()
    budget = ContextBudget(
        max_context_tokens=max_context_tokens,
        reserved_output_tokens=reserved_output_tokens,
        safety_margin_tokens=safety_margin_tokens,
        max_tokens_per_evidence=max_tokens_per_evidence,
    )
    examples = load_jsonl(root / "evals/datasets/retrieval_seed.jsonl", RetrievalExample)
    documents = {
        item.document_id: item
        for item in load_jsonl(root / "data/seed/documents.jsonl", SourceDocument)
    }
    aspects_by_document = _document_aspects(root)
    retrieval_report = json.loads(
        (root / "evals/results/hybrid_rrf_seed.json").read_text(encoding="utf-8")
    )
    ranking_by_id = {
        item["query_id"]: item["ranked_scores"] for item in retrieval_report["per_query"]
    }
    priority_builder = BudgetedContextBuilder(budget)
    coverage_builder = CoverageAwareContextBuilder(budget)
    rows = []
    for example in examples:
        evidence = [
            _as_evidence(
                documents[item["document_id"]],
                float(item["score"]),
                aspects_by_document.get(item["document_id"], set()),
            )
            for item in ranking_by_id[example.query_id]
        ]
        items = build_context_items(TravelRequest(query=example.query), evidence)
        if example.hard_filters:
            items.insert(
                2,
                ContextItem(
                    item_id="retrieval-hard-filters",
                    kind=ContextKind.CONSTRAINTS,
                    content=json.dumps(example.hard_filters, ensure_ascii=False, sort_keys=True),
                    priority=100,
                    mandatory=True,
                ),
            )
        inferred_targets = infer_coverage_targets(example.query, example.hard_filters)
        evaluation_targets = {item.value for item in example.expected_fact_types}
        priority = priority_builder.build(items)
        coverage = coverage_builder.build(items, inferred_targets)
        priority_evidence = _selected_evidence(priority)
        coverage_evidence = _selected_evidence(coverage)
        relevant = set(example.relevant_documents)
        priority_documents = {item.metadata["document_id"] for item in priority_evidence}
        coverage_documents = {item.metadata["document_id"] for item in coverage_evidence}
        denominator = len(relevant) or 1
        rows.append(
            {
                "query_id": example.query_id,
                "query_type": example.query_type.value,
                "inferred_targets": sorted(inferred_targets),
                "priority_estimated_tokens": priority.trace.estimated_input_tokens_after,
                "coverage_estimated_tokens": coverage.trace.estimated_input_tokens_after,
                "priority_evidence_count": len(priority_evidence),
                "coverage_evidence_count": len(coverage_evidence),
                "priority_relevant_document_recall": len(priority_documents & relevant)
                / denominator,
                "coverage_relevant_document_recall": len(coverage_documents & relevant)
                / denominator,
                "priority_expected_aspect_coverage": _aspect_coverage(
                    priority_evidence, evaluation_targets
                ),
                "coverage_expected_aspect_coverage": _aspect_coverage(
                    coverage_evidence, evaluation_targets
                ),
                "mandatory_preserved": all(
                    item.item_id in coverage.trace.included_item_ids
                    for item in items
                    if item.mandatory
                ),
                "trace": coverage.trace.model_dump(mode="json"),
            }
        )

    multi_rows = [row for row in rows if row["query_type"] == "multi_constraint"]
    digest = hashlib.sha256()
    for relative in (
        "data/seed/documents.jsonl",
        "data/seed/facts.jsonl",
        "evals/datasets/retrieval_seed.jsonl",
        "evals/results/hybrid_rrf_seed.json",
    ):
        digest.update((root / relative).read_bytes())
    metrics = {
        "cases": len(rows),
        "mean_priority_relevant_document_recall": _mean(
            [row["priority_relevant_document_recall"] for row in rows]
        ),
        "mean_coverage_relevant_document_recall": _mean(
            [row["coverage_relevant_document_recall"] for row in rows]
        ),
        "mean_priority_expected_aspect_coverage": _mean(
            [row["priority_expected_aspect_coverage"] for row in rows]
        ),
        "mean_coverage_expected_aspect_coverage": _mean(
            [row["coverage_expected_aspect_coverage"] for row in rows]
        ),
        "multi_constraint_priority_relevant_document_recall": _mean(
            [row["priority_relevant_document_recall"] for row in multi_rows]
        ),
        "multi_constraint_coverage_relevant_document_recall": _mean(
            [row["coverage_relevant_document_recall"] for row in multi_rows]
        ),
        "multi_constraint_priority_expected_aspect_coverage": _mean(
            [row["priority_expected_aspect_coverage"] for row in multi_rows]
        ),
        "multi_constraint_coverage_expected_aspect_coverage": _mean(
            [row["coverage_expected_aspect_coverage"] for row in multi_rows]
        ),
        "mean_priority_estimated_tokens": _mean([row["priority_estimated_tokens"] for row in rows]),
        "mean_coverage_estimated_tokens": _mean([row["coverage_estimated_tokens"] for row in rows]),
        "mandatory_preservation_rate": _mean([row["mandatory_preserved"] for row in rows]),
        "recall_improved_cases": sum(
            row["coverage_relevant_document_recall"] > row["priority_relevant_document_recall"]
            for row in rows
        ),
        "recall_regressed_cases": sum(
            row["coverage_relevant_document_recall"] < row["priority_relevant_document_recall"]
            for row in rows
        ),
    }
    gate_passed = (
        metrics["mandatory_preservation_rate"] == 1
        and metrics["recall_regressed_cases"] == 0
        and metrics["mean_coverage_relevant_document_recall"]
        >= metrics["mean_priority_relevant_document_recall"]
        and metrics["mean_coverage_expected_aspect_coverage"]
        > metrics["mean_priority_expected_aspect_coverage"]
    )
    return {
        "schema_version": 1,
        "experiment": "context-priority-vs-coverage-v1",
        "dataset_fingerprint_sha256": digest.hexdigest(),
        "configuration": budget.model_dump(mode="json"),
        "selection_policy": {
            "name": "bounded-aspect-gain-v1",
            "coverage_bonus": coverage_builder.coverage_bonus,
        },
        "selector_inputs": "query, hard_filters, typed fact metadata; no relevance labels",
        "metrics": metrics,
        "selection": {
            "selected_policy": ("bounded-aspect-gain-v1" if gate_passed else "priority-order-v1"),
            "gate_passed": gate_passed,
            "gate": (
                "mandatory preservation 1.0; zero per-case recall regressions; mean recall "
                "non-decreasing; mean expected-aspect coverage strictly increasing"
            ),
        },
        "cases": rows,
        "limitations": [
            "The deterministic query-aspect lexicon is narrow and Chinese-specific.",
            "Typed fact coverage depends on ingestion completeness.",
            "Expected fact types are used only for evaluation, never for selection.",
            "The 15-query project-authored seed is not an independent held-out benchmark.",
        ],
    }


def run_final_context_ablation(root: Path) -> dict[str, Any]:
    """Compare the Stage 4 context variants on identical retrieved candidates."""

    root = root.resolve()
    budget = ContextBudget(
        max_context_tokens=768,
        reserved_output_tokens=192,
        safety_margin_tokens=64,
        max_tokens_per_evidence=160,
    )
    examples = load_jsonl(root / "evals/datasets/retrieval_seed.jsonl", RetrievalExample)
    documents = {
        item.document_id: item
        for item in load_jsonl(root / "data/seed/documents.jsonl", SourceDocument)
    }
    aspects_by_document = _document_aspects(root)
    retrieval_report = json.loads(
        (root / "evals/results/hybrid_rrf_seed.json").read_text(encoding="utf-8")
    )
    rankings = {item["query_id"]: item["ranked_scores"] for item in retrieval_report["per_query"]}
    builders = {
        "unbounded": BaselineContextBuilder(),
        "priority": BudgetedContextBuilder(budget),
        "coverage": CoverageAwareContextBuilder(budget),
        "refined_coverage": RefinedCoverageContextBuilder(budget),
    }
    totals = {
        name: {"tokens": [], "recall": [], "aspects": [], "latency_ms": [], "citations": []}
        for name in builders
    }
    rows = []
    for example in examples:
        evidence = [
            _as_evidence(
                documents[item["document_id"]],
                float(item["score"]),
                aspects_by_document.get(item["document_id"], set()),
            )
            for item in rankings[example.query_id]
        ]
        items = build_context_items(TravelRequest(query=example.query), evidence)
        if example.hard_filters:
            items.insert(
                2,
                ContextItem(
                    item_id="retrieval-hard-filters",
                    kind=ContextKind.CONSTRAINTS,
                    content=json.dumps(example.hard_filters, ensure_ascii=False, sort_keys=True),
                    priority=100,
                    mandatory=True,
                ),
            )
        targets = infer_coverage_targets(example.query, example.hard_filters)
        expected = {item.value for item in example.expected_fact_types}
        relevant = set(example.relevant_documents)
        case = {"query_id": example.query_id, "variants": {}}
        for name, builder in builders.items():
            started = perf_counter()
            if name == "unbounded" or name == "priority":
                packed = builder.build(items)
            elif name == "coverage":
                packed = builder.build(items, targets)
            else:
                packed = builder.build(items, targets).packed
            latency = (perf_counter() - started) * 1000
            selected = _selected_evidence(packed)
            selected_ids = {item.metadata["document_id"] for item in selected}
            recall = len(selected_ids & relevant) / (len(relevant) or 1)
            aspect_score = _aspect_coverage(selected, expected)
            citation_ready = all(
                item.metadata.get("document_id") and item.metadata.get("source_url")
                for item in selected
            )
            values = totals[name]
            values["tokens"].append(packed.trace.estimated_input_tokens_after)
            values["recall"].append(recall)
            values["aspects"].append(aspect_score)
            values["latency_ms"].append(latency)
            values["citations"].append(citation_ready)
            case["variants"][name] = {
                "estimated_tokens": packed.trace.estimated_input_tokens_after,
                "relevant_document_recall": recall,
                "expected_aspect_coverage": aspect_score,
                "citation_ready": citation_ready,
            }
        rows.append(case)
    metrics = {
        name: {
            "mean_estimated_tokens": _mean(values["tokens"]),
            "mean_relevant_document_recall": _mean(values["recall"]),
            "mean_expected_aspect_coverage": _mean(values["aspects"]),
            "mean_local_build_latency_ms": _mean(values["latency_ms"]),
            "citation_readiness_rate": _mean(values["citations"]),
        }
        for name, values in totals.items()
    }
    selected = metrics["refined_coverage"]
    coverage = metrics["coverage"]
    gate = (
        selected["mean_relevant_document_recall"] >= coverage["mean_relevant_document_recall"]
        and selected["mean_expected_aspect_coverage"] >= coverage["mean_expected_aspect_coverage"]
        and selected["citation_readiness_rate"] == 1
    )
    return {
        "schema_version": 1,
        "experiment": "stage4-final-context-ablation-v1",
        "configuration": budget.model_dump(mode="json"),
        "metrics": metrics,
        "selection": {
            "selected_pipeline": "refined_coverage" if gate else "coverage",
            "evidence_level_gate_passed": gate,
            "answer_level_status": "not_measured",
        },
        "cases": rows,
        "limitations": [
            "This measures evidence readiness, not generated-answer correctness or faithfulness.",
            "Local builder latency excludes retrieval and model generation.",
            (
                "Citation readiness checks provenance availability, not citation correctness "
                "in answers."
            ),
        ],
    }
