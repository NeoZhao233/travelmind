from datetime import UTC, datetime, timedelta

from travelmind.domain.models import FactRecord, SourceDocument
from travelmind.ingestion import FactConflictResolver

NOW = datetime(2026, 9, 9, tzinfo=UTC)


def _document(identity, authority):
    return SourceDocument(
        document_id=identity,
        place_id="place-one",
        title=identity,
        section="Admission",
        content="This source content is deliberately long enough to validate.",
        source_url=f"https://example.invalid/{identity}",
        authority=authority,
        freshness="dynamic",
        collected_at=NOW,
    )


def _fact(identity, document_id, value, observed_at=NOW):
    return FactRecord(
        fact_id=identity,
        place_id="place-one",
        document_id=document_id,
        fact_type="admission",
        value=value,
        unit="CNY",
        qualifiers={"season": "high", "ticket_type": "entrance"},
        observed_at=observed_at,
    )


def test_higher_authority_beats_newer_third_party_conflict() -> None:
    documents = {
        "official-source": _document("official-source", "official_operator"),
        "guide-source": _document("guide-source", "third_party"),
    }
    resolution = FactConflictResolver().resolve(
        [
            _fact("official-price", "official-source", 30, NOW - timedelta(days=1)),
            _fact("guide-price", "guide-source", 20, NOW),
        ],
        documents,
    )[0]

    assert resolution.status == "selected"
    assert resolution.selected_fact_id == "official-price"
    assert resolution.reason_code == "higher_authority"


def test_equal_authority_uses_newer_observation() -> None:
    documents = {
        "source-one": _document("source-one", "government"),
        "source-two": _document("source-two", "government"),
    }
    resolution = FactConflictResolver().resolve(
        [
            _fact("older-price", "source-one", 30, NOW - timedelta(days=1)),
            _fact("newer-price", "source-two", 35, NOW),
        ],
        documents,
    )[0]

    assert resolution.selected_fact_id == "newer-price"
    assert resolution.reason_code == "newer_observation"


def test_equal_precedence_conflict_remains_unresolved() -> None:
    documents = {
        "source-one": _document("source-one", "government"),
        "source-two": _document("source-two", "government"),
    }
    resolution = FactConflictResolver().resolve(
        [
            _fact("price-one", "source-one", 30),
            _fact("price-two", "source-two", 35),
        ],
        documents,
    )[0]

    assert resolution.status == "unresolved"
    assert resolution.selected_fact_id is None
    assert resolution.reason_code == "insufficient_precedence"


def test_equivalent_high_authority_duplicates_beat_different_low_authority_value() -> None:
    documents = {
        "official-one": _document("official-one", "official_operator"),
        "official-two": _document("official-two", "official_operator"),
        "guide-source": _document("guide-source", "third_party"),
    }
    resolution = FactConflictResolver().resolve(
        [
            _fact("official-price-one", "official-one", 30),
            _fact("official-price-two", "official-two", 30),
            _fact("guide-price", "guide-source", 20),
        ],
        documents,
    )[0]

    assert resolution.status == "selected"
    assert resolution.selected_fact_id in {"official-price-one", "official-price-two"}
    assert resolution.reason_code == "higher_authority"
