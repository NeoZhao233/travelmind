from datetime import datetime

import pytest
from pydantic import ValidationError

from travelmind.domain.models import PlaceRecord, RetrievalExample, SourceDocument
from travelmind.schemas import Evidence


def test_place_coordinates_must_be_provided_as_a_pair() -> None:
    with pytest.raises(ValidationError, match="provided together"):
        PlaceRecord(
            place_id="sample-place",
            name="Sample",
            city="Beijing",
            categories=["museum"],
            official_url="https://example.com",
            longitude=116.4,
        )


def test_non_abstention_example_requires_relevant_documents() -> None:
    with pytest.raises(ValidationError, match="require relevant documents"):
        RetrievalExample(
            query_id="missing-ground-truth",
            query="Where should I go?",
            query_type="semantic",
            annotator="test",
        )


def test_relevance_grade_is_bounded() -> None:
    with pytest.raises(ValidationError, match="1, 2, or 3"):
        RetrievalExample(
            query_id="invalid-grade",
            query="Where should I go?",
            query_type="semantic",
            relevant_documents={"document": 4},
            annotator="test",
        )


def test_source_collection_time_requires_timezone() -> None:
    with pytest.raises(ValidationError, match="must include a timezone"):
        SourceDocument(
            document_id="timezone-test",
            place_id="sample-place",
            title="Sample",
            section="Opening hours",
            content="This source document is long enough for schema validation.",
            source_url="https://example.com/source",
            authority="official_operator",
            freshness="dynamic",
            collected_at=datetime(2026, 9, 8, 10, 0),
        )


def test_evidence_accepts_raw_cosine_scores_below_zero() -> None:
    evidence = Evidence(
        id="negative-cosine",
        content="A valid dense retrieval result can have a negative cosine similarity.",
        source_url="https://example.com/evidence",
        source_type="official",
        score=-0.2,
    )

    assert evidence.score == -0.2
