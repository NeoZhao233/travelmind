from travelmind.agentic.models import QueryIntent
from travelmind.agentic.policies import (
    CoverageEvidenceGrader,
    MissingAspectQueryRewriter,
    RuleBasedQueryRouter,
)
from travelmind.schemas import Evidence, TravelRequest


def _evidence(content: str, *, source_type: str = "official") -> Evidence:
    return Evidence(
        id=content,
        content=content,
        source_url="https://example.com/source",
        source_type=source_type,
        score=1.0,
    )


def test_router_marks_multi_constraint_queries_for_decomposition() -> None:
    decision = RuleBasedQueryRouter().route(
        TravelRequest(query="周一带父母去北京，希望免费并且不用预约")
    )

    assert decision.intent == QueryIntent.MULTI_CONSTRAINT
    assert decision.retrieval_strategy == "hybrid"
    assert decision.should_decompose is True
    assert decision.requires_structured_validation is True


def test_grader_requires_each_explicit_fact_aspect() -> None:
    request = TravelRequest(query="故宫门票和预约规则")
    assessment = CoverageEvidenceGrader().grade(
        request,
        [_evidence("故宫参观需要提前预约")],
    )

    assert assessment.sufficient is False
    assert assessment.covered_aspects == ["booking"]
    assert assessment.missing_aspects == ["admission"]
    assert assessment.coverage_score == 0.5


def test_grader_rejects_guide_only_evidence_for_hard_facts() -> None:
    assessment = CoverageEvidenceGrader().grade(
        TravelRequest(query="故宫开放时间"),
        [_evidence("每天开放时间请看这里", source_type="guide")],
    )

    assert assessment.sufficient is False
    assert "no_trusted_evidence" in assessment.reason_codes


def test_rewriter_expands_only_missing_aspects_and_keeps_original() -> None:
    request = TravelRequest(query="故宫门票和预约规则")
    assessment = CoverageEvidenceGrader().grade(
        request,
        [_evidence("故宫参观需要提前预约")],
    )

    queries = MissingAspectQueryRewriter().rewrite(
        request,
        [request.query],
        assessment,
        attempt=1,
    )

    assert queries[0] == request.query
    assert len(queries) == 2
    assert "官方门票" in queries[1]
