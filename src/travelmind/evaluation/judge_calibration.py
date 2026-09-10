from __future__ import annotations

import hashlib
import json
from collections import Counter
from pathlib import Path
from statistics import median_low
from typing import Any, Literal

from pydantic import BaseModel, Field

from travelmind.agentic.llm_provider import StructuredLLMProvider
from travelmind.evaluation.context_answer_runner import ContextAnswerCase
from travelmind.ingestion.dataset import load_jsonl

DIMENSIONS = (
    "answer_correctness",
    "evidence_grounding",
    "clarity_actionability",
    "uncertainty_calibration",
)


class JudgeScores(BaseModel):
    answer_correctness: int = Field(ge=1, le=5)
    evidence_grounding: int = Field(ge=1, le=5)
    clarity_actionability: int = Field(ge=1, le=5)
    uncertainty_calibration: int = Field(ge=1, le=5)


class JudgeOutput(BaseModel):
    scores: JudgeScores
    reason_codes: list[str] = Field(default_factory=list, max_length=8)
    evidence_summary: str = Field(min_length=1, max_length=240)


class CalibrationItem(BaseModel):
    candidate_id: str
    case_id: str
    query: str
    response: dict[str, Any]
    should_abstain: bool
    human_scores: JudgeScores | None = None
    annotator_id: str | None = None
    annotation_notes: str | None = None


class CalibrationDataset(BaseModel):
    schema_version: int = 1
    rubric_version: str
    label_provenance: Literal["human_pending", "human_verified", "ai_assisted_unverified"] = (
        "human_pending"
    )
    source_report: str
    source_report_sha256: str
    source_variant_hidden: bool = True
    items: list[CalibrationItem] = Field(min_length=1)


class HumanLabelsIncompleteError(ValueError):
    """Raised before provider calls when calibration labels are incomplete."""


def prepare_calibration_packet(
    root: Path,
    *,
    source_report_path: Path,
    variant: str = "refined_coverage",
) -> dict[str, Any]:
    root = root.resolve()
    report_path = (
        source_report_path if source_report_path.is_absolute() else root / source_report_path
    ).resolve()
    report_raw = report_path.read_bytes()
    report = json.loads(report_raw)
    queries = {
        case.case_id: case
        for case in load_jsonl(root / "evals/datasets/context_answer_seed.jsonl", ContextAnswerCase)
    }
    rows = [row for row in report["cases"] if row["variant"] == variant]
    if not rows:
        raise ValueError(f"source report has no rows for variant: {variant}")
    items = []
    for row in sorted(rows, key=lambda item: item["case_id"]):
        case = queries[row["case_id"]]
        identity_payload = json.dumps(
            [row["case_id"], variant, row["output"]],
            ensure_ascii=False,
            sort_keys=True,
        )
        items.append(
            {
                "candidate_id": hashlib.sha256(identity_payload.encode()).hexdigest()[:16],
                "case_id": row["case_id"],
                "query": case.query,
                "response": row["output"],
                "should_abstain": case.should_abstain,
                "human_scores": None,
                "annotator_id": None,
                "annotation_notes": None,
            }
        )
    return CalibrationDataset(
        rubric_version="subjective-answer-rubric-v1",
        source_report=str(report_path.relative_to(root)),
        source_report_sha256=hashlib.sha256(report_raw).hexdigest(),
        items=items,
    ).model_dump(mode="json")


def _quadratic_weighted_kappa(human: list[int], judge: list[int]) -> float:
    if len(human) != len(judge) or not human:
        raise ValueError("kappa requires equal non-empty score arrays")
    size = 5
    observed = [[0.0] * size for _ in range(size)]
    human_hist, judge_hist = Counter(human), Counter(judge)
    for left, right in zip(human, judge, strict=True):
        observed[left - 1][right - 1] += 1
    weighted_observed = 0.0
    weighted_expected = 0.0
    count = len(human)
    for left in range(size):
        for right in range(size):
            weight = ((left - right) ** 2) / ((size - 1) ** 2)
            weighted_observed += weight * observed[left][right] / count
            expected = human_hist[left + 1] * judge_hist[right + 1] / (count * count)
            weighted_expected += weight * expected
    if weighted_expected == 0:
        return 1.0 if weighted_observed == 0 else 0.0
    return 1 - weighted_observed / weighted_expected


def _prompt(item: CalibrationItem) -> str:
    payload = {
        "query": item.query,
        "response": item.response,
        "should_abstain": item.should_abstain,
    }
    return json.dumps(payload, ensure_ascii=False, sort_keys=True)


def run_judge_calibration(
    dataset_path: Path,
    provider: StructuredLLMProvider,
    *,
    repeats: int = 3,
) -> dict[str, Any]:
    if repeats < 2:
        raise ValueError("calibration requires at least two repeats for stability")
    raw = dataset_path.read_bytes()
    dataset = CalibrationDataset.model_validate_json(raw)
    incomplete = [
        item.candidate_id
        for item in dataset.items
        if item.human_scores is None or not item.annotator_id
    ]
    if incomplete:
        raise HumanLabelsIncompleteError(
            f"human labels are incomplete for {len(incomplete)} candidates; provider was not called"
        )

    rows: list[dict[str, Any]] = []
    for item in dataset.items:
        for repeat in range(1, repeats + 1):
            try:
                result = provider.complete_json(
                    system_prompt=(
                        "你是旅游问答质量评审。只按 rubric-v1 对给定回答的正确性、证据支撑、"
                        "清晰可执行性、不确定性处理分别打1到5分。返回 JSON："
                        '{"scores":{"answer_correctness":1,"evidence_grounding":1,'
                        '"clarity_actionability":1,"uncertainty_calibration":1},'
                        '"reason_codes":[],"evidence_summary":"不超过80字的可审核依据"}。'
                        "不要猜测系统身份，不要输出思维过程。"
                    ),
                    user_prompt=_prompt(item),
                    max_tokens=256,
                )
                output = JudgeOutput.model_validate(result.data)
                rows.append(
                    {
                        "candidate_id": item.candidate_id,
                        "case_id": item.case_id,
                        "repeat": repeat,
                        "success": True,
                        "scores": output.scores.model_dump(),
                        "reason_codes": output.reason_codes,
                        "evidence_summary": output.evidence_summary,
                        "model": result.model,
                        "latency_ms": result.latency_ms,
                        "total_tokens": result.usage.total_tokens,
                        "error_type": None,
                    }
                )
            except Exception as exc:
                rows.append(
                    {
                        "candidate_id": item.candidate_id,
                        "case_id": item.case_id,
                        "repeat": repeat,
                        "success": False,
                        "scores": None,
                        "reason_codes": [],
                        "evidence_summary": None,
                        "model": None,
                        "latency_ms": None,
                        "total_tokens": 0,
                        "error_type": type(exc).__name__,
                    }
                )

    successful = [row for row in rows if row["success"]]
    human_by_id = {item.candidate_id: item.human_scores for item in dataset.items}
    dimension_metrics = {}
    for dimension in DIMENSIONS:
        human: list[int] = []
        judged: list[int] = []
        for item in dataset.items:
            repeated_scores = [
                row["scores"][dimension]
                for row in successful
                if row["candidate_id"] == item.candidate_id
            ]
            if repeated_scores:
                human.append(getattr(human_by_id[item.candidate_id], dimension))
                judged.append(median_low(repeated_scores))
        dimension_metrics[dimension] = {
            "mae": sum(abs(left - right) for left, right in zip(human, judged, strict=True))
            / len(human)
            if human
            else None,
            "exact_agreement": sum(left == right for left, right in zip(human, judged, strict=True))
            / len(human)
            if human
            else None,
            "within_one_agreement": sum(
                abs(left - right) <= 1 for left, right in zip(human, judged, strict=True)
            )
            / len(human)
            if human
            else None,
            "quadratic_weighted_kappa": _quadratic_weighted_kappa(human, judged) if human else None,
            "mean_bias": sum(right - left for left, right in zip(human, judged, strict=True))
            / len(human)
            if human
            else None,
        }
    stable = 0
    for item in dataset.items:
        item_rows = [row for row in rows if row["candidate_id"] == item.candidate_id]
        vectors = {
            tuple(row["scores"][dimension] for dimension in DIMENSIONS)
            for row in item_rows
            if row["success"]
        }
        stable += (
            len(item_rows) == repeats
            and all(row["success"] for row in item_rows)
            and len(vectors) == 1
        )
    consistency = stable / len(dataset.items)
    fallback_rate = 1 - len(successful) / len(rows)
    metrics_gate = (
        fallback_rate <= 0.05
        and consistency >= 0.8
        and all(
            metrics["mae"] is not None
            and metrics["mae"] <= 0.75
            and metrics["within_one_agreement"] >= 0.9
            and metrics["quadratic_weighted_kappa"] >= 0.6
            for metrics in dimension_metrics.values()
        )
    )
    gate = metrics_gate and dataset.label_provenance == "human_verified"
    if dataset.label_provenance == "ai_assisted_unverified":
        selection_status = "reference_only"
    else:
        selection_status = "accepted" if gate else "rejected"
    return {
        "experiment": "stage6c-llm-judge-calibration",
        "dataset_sha256": hashlib.sha256(raw).hexdigest(),
        "rubric_version": dataset.rubric_version,
        "label_provenance": dataset.label_provenance,
        "repeats": repeats,
        "dimension_metrics": dimension_metrics,
        "repeat_exact_consistency": consistency,
        "fallback_rate": fallback_rate,
        "total_provider_tokens": sum(row["total_tokens"] for row in rows),
        "selection": {
            "judge_accepted": gate,
            "metrics_gate_passed": metrics_gate,
            "status": selection_status,
        },
        "calls": rows,
        "limitations": [
            "Calibration quality is bounded by the human rubric labels and annotator agreement.",
            "A small seed can validate plumbing but cannot establish general judge reliability.",
            "Deterministic safety and citation checks remain outside the LLM judge.",
        ],
    }
