from datetime import UTC, datetime
from pathlib import Path

from travelmind.agentic.llm_provider import LLMUsage, StructuredLLMResult
from travelmind.evaluation.e2e_planning_runner import (
    E2EPlanningCase,
    _catalog,
    _operational_context,
    _runtime_input,
    run_e2e_planning_experiment,
)
from travelmind.pipeline import EndToEndPlanningPipeline
from travelmind.planner.candidates import (
    CandidatePlanningProblem,
    ExplainableGreedyPlanner,
    PlanningDayWindow,
)
from travelmind.planner.llm_candidates import (
    DeepSeekRankedPlanningStrategy,
    DeterministicPlanningStrategy,
)
from travelmind.retrieval.bm25 import BM25Retriever
from travelmind.schemas import TravelConstraints, TravelRequest

PROJECT_ROOT = Path(__file__).resolve().parents[1]


class RankedProvider:
    def __init__(self, ranked_place_ids: list[str]) -> None:
        self.ranked_place_ids = ranked_place_ids

    def complete_json(self, **kwargs) -> StructuredLLMResult:
        del kwargs
        return StructuredLLMResult(
            data={
                "ranked_place_ids": self.ranked_place_ids,
                "reason_codes": ["preference_match"],
            },
            model="fake-ranker",
            usage=LLMUsage(prompt_tokens=100, completion_tokens=20, total_tokens=120),
            latency_ms=10,
            provider_attempts=1,
        )


def test_offline_e2e_pipeline_passes_frozen_baseline() -> None:
    report = run_e2e_planning_experiment(PROJECT_ROOT)

    assert report["metrics"]["deterministic"] == {
        "task_success_rate": 1,
        "valid_plan_rate": 1,
        "constraint_satisfaction_rate": 1,
        "required_place_coverage": 1,
        "expected_place_hit_rate": 0.9333333333333333,
        "expected_place_precision": 0.9,
        "mean_selected_place_count": 2,
        "repair_activation_rate": 0,
        "fallback_rate": 0,
        "total_provider_tokens": 0,
        "mean_provider_latency_ms": None,
        "mean_estimated_context_tokens": 486.2,
    }
    assert report["selection"]["status"] == "candidate_not_run"
    history = next(item for item in report["cases"] if item["case_id"] == "history_two_days")
    assert history["candidate_count"] > history["packed_evidence_count"]


def test_deepseek_ranker_accepts_safe_shortlist_and_appends_omitted_candidates() -> None:
    catalog = _catalog(PROJECT_ROOT)[:2]
    availability, travel = _operational_context(catalog, 1)
    problem = CandidatePlanningProblem(
        constraints=TravelConstraints(days=1),
        day_windows=[
            PlanningDayWindow(
                day=1,
                available_from=datetime(2026, 10, 13, 8, 30, tzinfo=UTC),
                available_until=datetime(2026, 10, 13, 18, 30, tzinfo=UTC),
                origin_place_id="hotel",
            )
        ],
        candidates=[
            item.model_copy(update={"evidence_ids": [f"doc-{item.place_id}"]}) for item in catalog
        ],
        availability=availability,
        travel_times=travel,
    )
    strategy = DeepSeekRankedPlanningStrategy(
        RankedProvider([catalog[0].place_id]),
        fallback=ExplainableGreedyPlanner(),
    )

    result = strategy.plan(
        problem,
        TravelRequest(query="test", constraints=TravelConstraints(days=1)),
        "evidence",
    )

    assert result.call is not None
    assert result.call.fallback_used is False
    assert result.call.success is True
    assert result.call.missing_candidate_count == 1
    assert result.planning.itinerary.days


def test_deepseek_ranker_applies_valid_complete_ranking() -> None:
    catalog = _catalog(PROJECT_ROOT)[:2]
    availability, travel = _operational_context(catalog, 1)
    problem = CandidatePlanningProblem(
        constraints=TravelConstraints(days=1, pace="relaxed"),
        day_windows=[
            PlanningDayWindow(
                day=1,
                available_from=datetime(2026, 10, 13, 8, 30, tzinfo=UTC),
                available_until=datetime(2026, 10, 13, 18, 30, tzinfo=UTC),
                origin_place_id="hotel",
            )
        ],
        candidates=[
            item.model_copy(update={"evidence_ids": [f"doc-{item.place_id}"]}) for item in catalog
        ],
        availability=availability,
        travel_times=travel,
    )
    expected_order = [catalog[1].place_id, catalog[0].place_id]

    result = DeepSeekRankedPlanningStrategy(RankedProvider(expected_order)).plan(
        problem,
        TravelRequest(query="test", constraints=problem.constraints),
        "evidence",
    )

    assert result.call is not None
    assert result.call.success is True
    assert result.call.fallback_used is False
    assert [
        item.place_id for item in result.planning.itinerary.days[0].activities
    ] == expected_order


class ExplodingRetriever:
    def search(self, queries: list[str], *, limit: int):
        del queries, limit
        raise TimeoutError("secret retrieval request")


def _simple_runtime_input():
    case = E2EPlanningCase(
        case_id="fallback",
        query="喜欢皇家园林和湖景，一天轻松游",
        constraints=TravelConstraints(
            destination="北京",
            days=1,
            pace="relaxed",
            required_places=["summer-palace"],
        ),
        expected_place_ids=["summer-palace"],
        minimum_expected_hits=1,
    )
    catalog = _catalog(PROJECT_ROOT)
    return _runtime_input(PROJECT_ROOT, case, catalog)


def test_e2e_pipeline_degrades_to_fallback_retriever() -> None:
    pipeline = EndToEndPlanningPipeline(
        retriever=ExplodingRetriever(),
        fallback_retriever=BM25Retriever.from_project(PROJECT_ROOT),
        planning_strategy=DeterministicPlanningStrategy(),
    )

    result = pipeline.run(_simple_runtime_input())

    assert result.status == "completed"
    assert result.degraded_components == ["retriever"]
    assert result.failure_reason is None


def test_e2e_pipeline_safely_fails_when_both_retrievers_fail() -> None:
    pipeline = EndToEndPlanningPipeline(
        retriever=ExplodingRetriever(),
        fallback_retriever=ExplodingRetriever(),
        planning_strategy=DeterministicPlanningStrategy(),
    )

    result = pipeline.run(_simple_runtime_input())

    assert result.status == "failed"
    assert result.itinerary is None
    assert result.degraded_components == ["retriever", "fallback_retriever"]
    assert "secret" not in result.failure_reason
