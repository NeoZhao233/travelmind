from datetime import UTC, datetime, timedelta

from travelmind.runtime.grounding import validate_grounding
from travelmind.runtime.models import ToolObservation, ToolOutcome
from travelmind.schemas import Activity, DayPlan, Evidence, Itinerary


def _itinerary(*, place_id: str, evidence_ids: list[str]) -> Itinerary:
    return Itinerary(
        days=[
            DayPlan(
                day=1,
                activities=[
                    Activity(
                        place_id=place_id,
                        name="测试景点",
                        start_at=datetime(2026, 1, 1, 9, tzinfo=UTC),
                        end_at=datetime(2026, 1, 1, 11, tzinfo=UTC),
                        estimated_cost=0,
                        evidence_ids=evidence_ids,
                    )
                ],
            )
        ],
        estimated_total_cost=0,
    )


def test_grounding_rejects_unknown_place_and_fabricated_citation() -> None:
    evidence = Evidence(
        id="real-source",
        content="真实景点资料",
        source_url="https://example.com",
        source_type="official",
        score=1,
        metadata={"place_id": "real-place"},
    )

    issues = validate_grounding(
        _itinerary(place_id="invented-place", evidence_ids=["invented-source"]),
        [evidence],
        [],
    )

    assert {item.code for item in issues} == {"UNKNOWN_EVIDENCE_ID", "UNKNOWN_PLACE_ID"}


def test_tool_observation_makes_dynamic_evidence_admissible() -> None:
    observation = ToolObservation(
        call_id="call-1",
        step_id="availability",
        tool_name="availability",
        outcome=ToolOutcome.SUCCESS,
        payload={"place_id": "dynamic-place", "status": "open"},
        evidence_ids=["live-source"],
        observed_at=datetime.now(UTC),
    )

    issues = validate_grounding(
        _itinerary(place_id="dynamic-place", evidence_ids=["live-source"]),
        [],
        [observation],
    )

    assert issues == []


def test_grounding_rejects_stale_tool_evidence() -> None:
    observation = ToolObservation(
        call_id="call-stale",
        step_id="availability",
        tool_name="availability",
        outcome=ToolOutcome.SUCCESS,
        payload={"place_id": "dynamic-place", "status": "open"},
        evidence_ids=["stale-live-source"],
        observed_at=datetime(2025, 12, 1, tzinfo=UTC),
        valid_until=datetime(2025, 12, 31, tzinfo=UTC),
    )

    issues = validate_grounding(
        _itinerary(place_id="dynamic-place", evidence_ids=["stale-live-source"]),
        [],
        [observation],
        now=datetime(2026, 1, 1, tzinfo=UTC) + timedelta(hours=1),
    )

    assert [item.code for item in issues] == ["STALE_TOOL_EVIDENCE"]
