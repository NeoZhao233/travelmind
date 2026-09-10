import json
from pathlib import Path

import pytest

from travelmind.agentic.llm_provider import LLMUsage, StructuredLLMResult
from travelmind.evaluation.judge_calibration import (
    HumanLabelsIncompleteError,
    prepare_calibration_packet,
    run_judge_calibration,
)

PROJECT_ROOT = Path(__file__).resolve().parents[1]


class FixedJudge:
    def __init__(self, score: int = 4) -> None:
        self.score = score
        self.calls = 0

    def complete_json(self, **kwargs) -> StructuredLLMResult:
        del kwargs
        self.calls += 1
        return StructuredLLMResult(
            data={
                "scores": {
                    "answer_correctness": self.score,
                    "evidence_grounding": self.score,
                    "clarity_actionability": self.score,
                    "uncertainty_calibration": self.score,
                },
                "reason_codes": ["supported"],
                "evidence_summary": "回答与人工 rubric 一致。",
            },
            model="fake-judge",
            usage=LLMUsage(prompt_tokens=20, completion_tokens=10, total_tokens=30),
            latency_ms=5,
            provider_attempts=1,
        )


def _packet() -> dict:
    return prepare_calibration_packet(
        PROJECT_ROOT,
        source_report_path=Path("evals/results/stage4_deepseek_answer_ablation_v4_final.json"),
    )


def test_packet_is_unlabeled_and_does_not_expose_source_variant() -> None:
    packet = _packet()

    assert len(packet["items"]) == 7
    assert packet["label_provenance"] == "human_pending"
    assert packet["source_variant_hidden"] is True
    assert all(item["human_scores"] is None for item in packet["items"])
    assert all("variant" not in item for item in packet["items"])


def test_incomplete_human_labels_block_provider_before_first_call(tmp_path: Path) -> None:
    path = tmp_path / "packet.json"
    path.write_text(json.dumps(_packet(), ensure_ascii=False), encoding="utf-8")
    provider = FixedJudge()

    with pytest.raises(HumanLabelsIncompleteError, match="provider was not called"):
        run_judge_calibration(path, provider)

    assert provider.calls == 0


def test_matching_repeated_judge_passes_calibration_contract(tmp_path: Path) -> None:
    packet = _packet()
    packet["label_provenance"] = "human_verified"
    for item in packet["items"]:
        item["human_scores"] = {
            "answer_correctness": 4,
            "evidence_grounding": 4,
            "clarity_actionability": 4,
            "uncertainty_calibration": 4,
        }
        item["annotator_id"] = "fixture-annotator"
    path = tmp_path / "packet.json"
    path.write_text(json.dumps(packet, ensure_ascii=False), encoding="utf-8")
    provider = FixedJudge()

    report = run_judge_calibration(path, provider, repeats=2)

    assert provider.calls == 14
    assert report["repeat_exact_consistency"] == 1
    assert report["fallback_rate"] == 0
    assert report["selection"] == {
        "judge_accepted": True,
        "metrics_gate_passed": True,
        "status": "accepted",
    }
    assert all(
        metrics["quadratic_weighted_kappa"] == 1 for metrics in report["dimension_metrics"].values()
    )


def test_ai_assisted_labels_cannot_claim_human_calibration(tmp_path: Path) -> None:
    packet = _packet()
    packet["label_provenance"] = "ai_assisted_unverified"
    for item in packet["items"]:
        item["human_scores"] = {
            "answer_correctness": 4,
            "evidence_grounding": 4,
            "clarity_actionability": 4,
            "uncertainty_calibration": 4,
        }
        item["annotator_id"] = "codex-ai-assisted-v1"
    path = tmp_path / "packet.json"
    path.write_text(json.dumps(packet, ensure_ascii=False), encoding="utf-8")

    report = run_judge_calibration(path, FixedJudge(), repeats=2)

    assert report["selection"] == {
        "judge_accepted": False,
        "metrics_gate_passed": True,
        "status": "reference_only",
    }
