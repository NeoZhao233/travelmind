from datetime import UTC, datetime, timedelta

from travelmind.schemas import Activity, DayPlan, Evidence, Itinerary, TravelRequest


class DemoPlanner:
    """A deterministic placeholder that keeps graph tests independent of an LLM provider."""

    def generate(self, request: TravelRequest, evidence: list[Evidence]) -> Itinerary:
        start = datetime(2026, 1, 1, 9, tzinfo=UTC)
        activities: list[Activity] = []
        for index, item in enumerate(evidence[:2]):
            item_start = start + timedelta(hours=index * 3)
            activities.append(
                Activity(
                    place_id=str(item.metadata.get("place_id", item.id)),
                    name=str(item.metadata.get("name", f"Place {index + 1}")),
                    start_at=item_start,
                    end_at=item_start + timedelta(hours=2),
                    estimated_cost=float(item.metadata.get("cost", 0)),
                    evidence_ids=[item.id],
                )
            )

        total_cost = sum(activity.estimated_cost for activity in activities)
        return Itinerary(
            days=[DayPlan(day=1, activities=activities)],
            estimated_total_cost=total_cost,
            assumptions=["Demo planner: replace with an evaluated LLM planner."],
        )
