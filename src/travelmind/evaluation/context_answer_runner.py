from __future__ import annotations

import hashlib
import json
from pathlib import Path
from typing import Any

from pydantic import BaseModel, Field, ValidationError

from travelmind.agentic.llm_provider import StructuredLLMProvider
from travelmind.context.builder import BaselineContextBuilder, build_context_items
from travelmind.context.coverage import infer_coverage_targets
from travelmind.context.models import ContextBudget, ContextKind
from travelmind.context.pipeline import RefinedCoverageContextBuilder
from travelmind.domain.models import FactRecord, SourceAuthority, SourceDocument
from travelmind.ingestion.dataset import load_jsonl
from travelmind.schemas import Evidence, TravelRequest


class ContextAnswerCase(BaseModel):
    case_id: str
    retrieval_query_id: str | None
    query: str
    required_term_groups: list[list[str]]
    supporting_documents: list[str]
    should_abstain: bool


class AnswerClaim(BaseModel):
    text: str = Field(min_length=1)
    evidence_ids: list[str] = Field(default_factory=list)


class AnswerOutput(BaseModel):
    answer: str = Field(min_length=1)
    claims: list[AnswerClaim] = Field(default_factory=list)
    abstained: bool
    uncertainty: str | None = None


def _evidence(document: SourceDocument, aspects: set[str]) -> Evidence:
    return Evidence(
        id=document.document_id,
        content=document.content,
        source_url=str(document.source_url),
        source_type=("guide" if document.authority == SourceAuthority.THIRD_PARTY else "official"),
        score=1,
        retrieved_at=document.collected_at,
        metadata={
            "document_id": document.document_id,
            "aspects": ",".join(sorted(aspects)),
            "authority": document.authority.value,
        },
    )


def run_context_answer_ablation(root: Path, provider: StructuredLLMProvider) -> dict[str, Any]:
    root = root.resolve()
    dataset_path = root / "evals/datasets/context_answer_seed.jsonl"
    cases = load_jsonl(dataset_path, ContextAnswerCase)
    documents = {
        item.document_id: item
        for item in load_jsonl(root / "data/seed/documents.jsonl", SourceDocument)
    }
    aspects: dict[str, set[str]] = {}
    for fact in load_jsonl(root / "data/seed/facts.jsonl", FactRecord):
        aspects.setdefault(fact.document_id, set()).add(fact.fact_type.value)
    retrieval = json.loads(
        (root / "evals/results/hybrid_rrf_seed.json").read_text(encoding="utf-8")
    )
    rankings = {row["query_id"]: row["ranked_scores"] for row in retrieval["per_query"]}
    budget = ContextBudget(
        max_context_tokens=768,
        reserved_output_tokens=192,
        safety_margin_tokens=64,
        max_tokens_per_evidence=160,
    )
    builders = {
        "unbounded": BaselineContextBuilder(),
        "refined_coverage": RefinedCoverageContextBuilder(budget),
    }
    rows = []
    for case in cases:
        ranked = rankings.get(case.retrieval_query_id, [])
        evidence = [
            _evidence(documents[row["document_id"]], aspects.get(row["document_id"], set()))
            for row in ranked
        ]
        items = build_context_items(TravelRequest(query=case.query), evidence)
        for variant, builder in builders.items():
            targets = infer_coverage_targets(case.query)
            packed = (
                builder.build(items)
                if variant == "unbounded"
                else builder.build(items, targets).packed
            )
            available = {
                item.metadata["document_id"]
                for item in packed.items
                if item.kind == ContextKind.EVIDENCE
            }
            try:
                result = provider.complete_json(
                    system_prompt=(
                        "仅依据上下文回答并严格返回JSON对象，例如："
                        '{"answer":"简洁回答","claims":[{"text":"事实",'
                        '"evidence_ids":["document_id"]}],"abstained":false,'
                        '"uncertainty":null}。每个事实claim必须'
                        "引用证据标签中的document_id，禁止添加evidence:前缀或URL；回答必须"
                        "简洁；证据不足必须abstained=true。"
                    ),
                    user_prompt=packed.rendered,
                    max_tokens=256,
                )
                output = AnswerOutput.model_validate(result.data)
                failed = False
                error_type = None
            except (Exception, ValidationError) as exc:
                output, result, failed = (
                    AnswerOutput(answer="答案生成失败", abstained=True),
                    None,
                    True,
                )
                error_type = type(exc).__name__
            text = output.answer + " " + " ".join(claim.text for claim in output.claims)
            term_coverage = (
                sum(any(term in text for term in group) for group in case.required_term_groups)
                / len(case.required_term_groups)
                if case.required_term_groups
                else 1.0
            )
            cited = [identity for claim in output.claims for identity in claim.evidence_ids]
            normalized_citations = [identity.removeprefix("evidence:") for identity in cited]
            valid_citations = [
                identity for identity in normalized_citations if identity in available
            ]
            supporting = set(case.supporting_documents)
            citation_precision = (
                sum(identity in supporting for identity in normalized_citations)
                / len(normalized_citations)
                if normalized_citations
                else (1.0 if case.should_abstain else 0.0)
            )
            citation_recall = (
                len(set(valid_citations) & supporting) / len(supporting) if supporting else 1.0
            )
            abstention_correct = output.abstained == case.should_abstain
            success = (
                not failed and abstention_correct and term_coverage == 1 and citation_recall == 1
            )
            rows.append(
                {
                    "case_id": case.case_id,
                    "variant": variant,
                    "success": success,
                    "fallback": failed,
                    "error_type": error_type,
                    "cited_evidence_ids": normalized_citations,
                    "output": output.model_dump(mode="json"),
                    "term_coverage": term_coverage,
                    "citation_precision": citation_precision,
                    "citation_recall": citation_recall,
                    "abstention_correct": abstention_correct,
                    "prompt_tokens": result.usage.prompt_tokens if result else 0,
                    "completion_tokens": result.usage.completion_tokens if result else 0,
                    "latency_ms": result.latency_ms if result else None,
                }
            )
    metrics = {}
    for variant in builders:
        selected = [row for row in rows if row["variant"] == variant]
        successful_calls = [row for row in selected if not row["fallback"]]
        metrics[variant] = {
            "task_success_rate": sum(row["success"] for row in selected) / len(selected),
            "mean_term_coverage": sum(row["term_coverage"] for row in selected) / len(selected),
            "mean_citation_precision": sum(row["citation_precision"] for row in selected)
            / len(selected),
            "mean_citation_recall": sum(row["citation_recall"] for row in selected) / len(selected),
            "abstention_accuracy": sum(row["abstention_correct"] for row in selected)
            / len(selected),
            "fallback_rate": sum(row["fallback"] for row in selected) / len(selected),
            "total_tokens": sum(
                row["prompt_tokens"] + row["completion_tokens"] for row in selected
            ),
            "mean_latency_ms": sum(row["latency_ms"] for row in successful_calls)
            / len(successful_calls)
            if successful_calls
            else None,
        }
    candidate, baseline = metrics["refined_coverage"], metrics["unbounded"]
    gate = (
        candidate["task_success_rate"] >= baseline["task_success_rate"]
        and candidate["mean_citation_recall"] >= baseline["mean_citation_recall"]
        and candidate["fallback_rate"] <= 0.1
        and candidate["total_tokens"] < baseline["total_tokens"]
    )
    return {
        "schema_version": 1,
        "experiment": "deepseek-context-answer-ablation-v1",
        "dataset_fingerprint_sha256": hashlib.sha256(dataset_path.read_bytes()).hexdigest(),
        "configuration": {
            "variants": list(builders),
            "thinking": "disabled",
            "temperature": 0,
            "max_output_tokens": 256,
        },
        "metrics": metrics,
        "selection": {
            "selected_pipeline": "refined_coverage" if gate else "unbounded",
            "gate_passed": gate,
        },
        "cases": rows,
        "limitations": [
            "Seven project-authored cases are a pilot, not a blind benchmark.",
            (
                "Reference-term matching undercounts valid paraphrases and must be paired "
                "with error review."
            ),
            "Citation metrics check expected document IDs, not fine-grained entailment.",
        ],
    }
