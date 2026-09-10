from datetime import UTC, datetime

import pytest

from travelmind.context.builder import (
    BaselineContextBuilder,
    BudgetedContextBuilder,
    CoverageAwareContextBuilder,
    build_context_items,
)
from travelmind.context.coverage import infer_coverage_targets
from travelmind.context.models import ContextBudget, ContextBudgetError, ContextKind
from travelmind.context.tokenization import FallbackTokenEstimator
from travelmind.schemas import Evidence, TravelConstraints, TravelRequest


def _evidence(identity: str, content: str, score: float = 1) -> Evidence:
    return Evidence(
        id=identity,
        content=content,
        source_url="https://example.com/official",
        source_type="official",
        score=score,
        retrieved_at=datetime.now(UTC),
        metadata={"document_id": identity},
    )


def test_baseline_trace_records_shape_without_copying_content() -> None:
    items = build_context_items(
        TravelRequest(query="故宫门票", constraints=TravelConstraints(budget=100)),
        [_evidence("ticket", "官方门票价格为六十元")],
    )

    packed = BaselineContextBuilder().build(items)

    assert packed.trace.mode == "unbounded_baseline"
    assert packed.trace.estimated_input_tokens_before > 0
    assert "故宫门票" in packed.rendered
    assert all(not hasattr(item, "content") for item in packed.trace.items)


def test_default_constraints_do_not_consume_context_budget() -> None:
    items = build_context_items(TravelRequest(query="故宫门票"), [])

    assert [item.kind for item in items] == [
        ContextKind.SYSTEM,
        ContextKind.USER_REQUEST,
    ]


def test_budget_preserves_mandatory_items_and_output_reserve() -> None:
    request = TravelRequest(
        query="带父母去故宫",
        constraints=TravelConstraints(budget=300, required_places=["故宫"]),
    )
    items = build_context_items(
        request,
        [_evidence(f"doc-{index}", "证据" * 120) for index in range(4)],
    )
    budget = ContextBudget(
        max_context_tokens=360,
        reserved_output_tokens=80,
        safety_margin_tokens=30,
        max_tokens_per_evidence=80,
    )

    packed = BudgetedContextBuilder(budget).build(items)

    assert packed.trace.estimated_input_tokens_after <= budget.input_token_limit
    assert {"system-instruction", "user-request", "structured-constraints"} <= set(
        packed.trace.included_item_ids
    )
    assert packed.trace.reserved_output_tokens == 80
    assert packed.trace.clipped_item_ids or packed.trace.dropped_item_ids


def test_budget_fails_closed_instead_of_truncating_user_request() -> None:
    items = build_context_items(TravelRequest(query="必须保留" * 100), [])
    budget = ContextBudget(max_context_tokens=100, reserved_output_tokens=30)

    with pytest.raises(ContextBudgetError, match="request was not truncated"):
        BudgetedContextBuilder(budget).build(items)


def test_higher_priority_evidence_is_considered_first() -> None:
    items = build_context_items(
        TravelRequest(query="门票"),
        [
            _evidence("first", "甲" * 120),
            _evidence("second", "乙" * 120),
        ],
    )
    budget = ContextBudget(
        max_context_tokens=300,
        reserved_output_tokens=50,
        max_tokens_per_evidence=70,
    )

    packed = BudgetedContextBuilder(budget).build(items)

    included_evidence = [item for item in packed.items if item.kind == ContextKind.EVIDENCE]
    assert included_evidence
    assert included_evidence[0].item_id == "evidence:first"


def test_tokenizer_failure_degrades_to_heuristic_and_is_traced() -> None:
    class ExplodingEstimator:
        name = "unavailable-model-tokenizer"

        def estimate(self, text: str) -> int:
            del text
            raise RuntimeError("secret tokenizer details")

    estimator = FallbackTokenEstimator(ExplodingEstimator())
    items = build_context_items(TravelRequest(query="故宫门票"), [])

    packed = BaselineContextBuilder(estimator).build(items)

    assert packed.trace.degraded_components == ["token_estimator"]
    assert "secret" not in packed.model_dump_json()


def test_coverage_targets_are_inferred_only_from_runtime_inputs() -> None:
    targets = infer_coverage_targets(
        "周一带行动不便的父母去免费且不用预约的地方",
        {"weekday": "monday", "booking_required": False},
    )

    assert targets == {
        "opening_hours",
        "admission",
        "booking",
        "accessibility",
    }


def test_coverage_builder_prefers_one_document_covering_more_missing_aspects() -> None:
    evidence = [
        _evidence("booking-one", "预约证据" * 40),
        _evidence("booking-two", "重复预约证据" * 40),
        _evidence("broad", "开放、免费、免预约且无障碍" * 40),
    ]
    evidence[0].metadata["aspects"] = "booking"
    evidence[1].metadata["aspects"] = "booking"
    evidence[2].metadata["aspects"] = "admission,booking,opening_hours,accessibility"
    items = build_context_items(TravelRequest(query="带父母低预算出行"), evidence)
    budget = ContextBudget(
        max_context_tokens=300,
        reserved_output_tokens=60,
        safety_margin_tokens=20,
        max_tokens_per_evidence=100,
    )

    packed = CoverageAwareContextBuilder(budget).build(
        items,
        {"admission", "booking", "opening_hours", "accessibility"},
    )

    included = [item.item_id for item in packed.items if item.kind == ContextKind.EVIDENCE]
    assert included[0] == "evidence:broad"
    broad_trace = next(item for item in packed.trace.items if item.item_id == "evidence:broad")
    assert broad_trace.reason_code.startswith("new_aspect_coverage")


def test_missing_aspect_metadata_falls_back_to_retrieval_priority() -> None:
    items = build_context_items(
        TravelRequest(query="门票"),
        [_evidence("first", "甲" * 80), _evidence("second", "乙" * 80)],
    )
    budget = ContextBudget(max_context_tokens=280, reserved_output_tokens=50)

    packed = CoverageAwareContextBuilder(budget).build(items, {"admission"})

    included = [item.item_id for item in packed.items if item.kind == ContextKind.EVIDENCE]
    assert included[0] == "evidence:first"
