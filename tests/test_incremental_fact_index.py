from datetime import UTC, datetime

import pytest

from travelmind.domain.models import FactRecord, SourceDocument
from travelmind.ingestion import IncrementalFactIndex, ParsedSourceBatch

NOW = datetime(2026, 9, 9, tzinfo=UTC)
SNAPSHOT = "a" * 64


def _batch(
    document_id,
    fact_id,
    fact_type,
    value,
    *,
    authority="official_operator",
    observed_at=NOW,
):
    document = SourceDocument(
        document_id=document_id,
        place_id="place-one",
        title=document_id,
        section="Facts",
        content="This source content is deliberately long enough to validate.",
        source_url=f"https://example.invalid/{document_id}",
        authority=authority,
        freshness="dynamic",
        collected_at=NOW,
    )
    fact = FactRecord(
        fact_id=fact_id,
        place_id="place-one",
        document_id=document_id,
        fact_type=fact_type,
        value=value,
        unit="CNY" if fact_type == "admission" else None,
        qualifiers={"scope": "standard"},
        observed_at=observed_at,
    )
    return ParsedSourceBatch(
        parser_version="fixture-v1",
        snapshot_sha256=SNAPSHOT,
        document=document,
        facts=[fact],
    )


def test_incremental_update_recomputes_only_affected_fact_key() -> None:
    index = IncrementalFactIndex()
    admission = _batch("ticket-source", "ticket-price", "admission", 30)
    description = _batch(
        "description-source",
        "place-description",
        "description",
        "historic place",
    )
    index.apply(admission)
    index.apply(description)

    updated = _batch("ticket-source", "ticket-price-v2", "admission", 35)
    result = index.apply(updated)

    assert result.affected_key_count == 1
    assert result.total_key_count == 2
    assert {fact.value for fact in index.active_facts} == {35, "historic place"}


def test_identical_batch_is_no_op() -> None:
    index = IncrementalFactIndex()
    batch = _batch("ticket-source", "ticket-price", "admission", 30)
    index.apply(batch)

    result = index.apply(batch)

    assert result.status == "no_op"
    assert result.changed is False
    assert result.affected_key_count == 0


def test_failed_incremental_update_preserves_previous_state() -> None:
    index = IncrementalFactIndex()
    first = _batch("ticket-source", "shared-fact", "admission", 30)
    index.apply(first)
    before = index.active_facts
    collision = _batch("other-source", "shared-fact", "description", "collision")

    with pytest.raises(ValueError, match="collides"):
        index.apply(collision)

    assert index.active_facts == before


def test_unresolved_cross_source_conflict_is_not_served() -> None:
    index = IncrementalFactIndex()
    index.apply(
        _batch(
            "government-one",
            "ticket-one",
            "admission",
            30,
            authority="government",
        )
    )
    result = index.apply(
        _batch(
            "government-two",
            "ticket-two",
            "admission",
            35,
            authority="government",
        )
    )

    assert result.unresolved_key_count == 1
    assert index.active_facts == []
