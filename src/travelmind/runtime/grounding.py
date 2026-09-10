from __future__ import annotations

from datetime import UTC, datetime

from travelmind.runtime.models import GroundingIssue, StepKind, ToolObservation, ToolOutcome
from travelmind.schemas import Evidence, Itinerary


def validate_grounding(
    itinerary: Itinerary,
    evidence: list[Evidence],
    observations: list[ToolObservation],
    *,
    now: datetime | None = None,
) -> list[GroundingIssue]:
    """Verify machine-checkable provenance; it does not pretend to judge all prose semantics."""

    checked_at = now or datetime.now(UTC)
    evidence_ids = {item.id for item in evidence}
    known_places = {
        str(item.metadata["place_id"])
        for item in evidence
        if item.metadata.get("place_id") is not None
    }
    successful = [item for item in observations if item.outcome == ToolOutcome.SUCCESS]
    failed_evidence = {
        identity
        for observation in observations
        if observation.outcome != ToolOutcome.SUCCESS
        for identity in observation.evidence_ids
    }
    tool_evidence = {
        identity: observation
        for observation in successful
        for identity in observation.evidence_ids
    }
    for observation in successful:
        evidence_ids.update(observation.evidence_ids)
        place_id = observation.payload.get("place_id")
        if place_id is not None:
            known_places.add(str(place_id))

    issues: list[GroundingIssue] = []
    for day in itinerary.days:
        for activity in day.activities:
            if not activity.evidence_ids:
                issues.append(
                    GroundingIssue(
                        code="ACTIVITY_EVIDENCE_MISSING",
                        message="Activity has no provenance citation.",
                        place_id=activity.place_id,
                    )
                )
            for identity in activity.evidence_ids:
                if identity in failed_evidence:
                    issues.append(
                        GroundingIssue(
                            code="FAILED_TOOL_EVIDENCE",
                            message="Activity cites evidence from an unsuccessful tool call.",
                            place_id=activity.place_id,
                            evidence_id=identity,
                        )
                    )
                elif identity not in evidence_ids:
                    issues.append(
                        GroundingIssue(
                            code="UNKNOWN_EVIDENCE_ID",
                            message=(
                                "Activity cites evidence absent from retrieval "
                                "and tool observations."
                            ),
                            place_id=activity.place_id,
                            evidence_id=identity,
                        )
                    )
                observation = tool_evidence.get(identity)
                if (
                    observation is not None
                    and observation.valid_until is not None
                    and observation.valid_until < activity.start_at
                ):
                    issues.append(
                        GroundingIssue(
                            code="STALE_TOOL_EVIDENCE",
                            message="Tool evidence expires before the planned activity.",
                            place_id=activity.place_id,
                            evidence_id=identity,
                        )
                    )
            if known_places and activity.place_id not in known_places:
                issues.append(
                    GroundingIssue(
                        code="UNKNOWN_PLACE_ID",
                        message="Activity place is absent from all admissible evidence.",
                        place_id=activity.place_id,
                    )
                )

            availability = [
                item
                for item in successful
                if item.payload.get("kind") == StepKind.CHECK_AVAILABILITY
                and item.payload.get("place_id") == activity.place_id
            ]
            if availability and all(
                item.valid_until is not None and item.valid_until < checked_at
                for item in availability
            ):
                issues.append(
                    GroundingIssue(
                        code="STALE_DYNAMIC_EVIDENCE",
                        message="Opening-hours evidence is stale at validation time.",
                        place_id=activity.place_id,
                    )
                )
    return issues
