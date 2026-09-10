from typing import Any

import pytest

from travelmind.agentic.llm_policies import (
    LLMEvidenceGrader,
    LLMPolicyTelemetry,
    LLMQueryRewriter,
    LLMQueryRouter,
)
from travelmind.agentic.llm_provider import LLMOutputError, StructuredLLMResult
from travelmind.agentic.models import EvidenceAssessment, QueryIntent
from travelmind.schemas import Evidence, TravelRequest


class FakeProvider:
    def __init__(self, *outputs: dict[str, Any]) -> None:
        self.outputs = list(outputs)

    def complete_json(self, **kwargs: Any) -> StructuredLLMResult:
        del kwargs
        return StructuredLLMResult(
            data=self.outputs.pop(0),
            model="fake-deepseek",
            latency_ms=12,
            provider_attempts=1,
        )


def test_llm_router_validates_structured_decision_and_telemetry() -> None:
    telemetry = LLMPolicyTelemetry()
    router = LLMQueryRouter(
        FakeProvider(
            {
                "intent": "temporal",
                "retrieval_strategy": "hybrid",
                "requires_structured_validation": True,
                "should_decompose": False,
                "reason_codes": ["time_sensitive"],
            }
        ),
        telemetry,
    )

    decision = router.route(TravelRequest(query="下午四点还能进馆吗"))

    assert decision.intent == QueryIntent.TEMPORAL
    assert telemetry.calls[0].success is True


def test_llm_router_rejects_invalid_schema_and_records_failure() -> None:
    telemetry = LLMPolicyTelemetry()
    router = LLMQueryRouter(FakeProvider({"intent": "invented"}), telemetry)

    with pytest.raises(LLMOutputError):
        router.route(TravelRequest(query="故宫门票"))

    assert telemetry.calls[0].success is False
    assert telemetry.calls[0].error_type == "LLMOutputError"
    assert telemetry.calls[0].model == "fake-deepseek"
    assert telemetry.calls[0].latency_ms == 12


def test_llm_grader_rejects_inconsistent_sufficiency() -> None:
    grader = LLMEvidenceGrader(
        FakeProvider(
            {
                "sufficient": True,
                "coverage_score": 0.5,
                "required_aspects": ["booking"],
                "covered_aspects": [],
                "missing_aspects": ["booking"],
                "reason_codes": [],
            }
        )
    )
    evidence = Evidence(
        id="doc",
        content="介绍",
        source_url="https://example.com",
        source_type="official",
        score=1,
    )

    with pytest.raises(LLMOutputError):
        grader.grade(TravelRequest(query="需要预约吗"), [evidence])


def test_llm_rewriter_retains_history_deduplicates_and_caps_fanout() -> None:
    rewriter = LLMQueryRewriter(FakeProvider({"queries": ["官方预约规则", "原查询"]}))

    queries = rewriter.rewrite(
        TravelRequest(query="原查询"),
        ["原查询"],
        EvidenceAssessment(
            sufficient=False,
            coverage_score=0,
            required_aspects=["booking"],
            missing_aspects=["booking"],
        ),
        attempt=1,
    )

    assert queries == ["原查询", "官方预约规则"]
