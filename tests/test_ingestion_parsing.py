import hashlib
import json
from datetime import UTC, datetime

import pytest

from travelmind.ingestion import (
    ParseQuarantineStore,
    SnapshotReceipt,
    SourceParseRejectedError,
    TypedSourceParser,
    json_object_parser,
)

NOW = datetime(2026, 9, 9, tzinfo=UTC)
URL = "https://official.example/source"


def _payload(document_id="official-document", fact_document_id=None):
    return {
        "document": {
            "document_id": document_id,
            "place_id": "place-one",
            "title": "Official source",
            "section": "Admission",
            "content": "This official source content is long enough for validation.",
            "source_url": URL,
            "authority": "official_operator",
            "freshness": "dynamic",
            "collected_at": NOW.isoformat(),
        },
        "facts": [
            {
                "fact_id": "ticket-price-one",
                "place_id": "place-one",
                "document_id": fact_document_id or document_id,
                "fact_type": "admission",
                "value": 30,
                "unit": "CNY",
                "qualifiers": {"season": "high"},
                "observed_at": NOW.isoformat(),
            }
        ],
    }


def _snapshot(content: bytes) -> SnapshotReceipt:
    return SnapshotReceipt(
        source_id="official-source",
        source_url=URL,
        fetched_at=NOW,
        content_sha256=hashlib.sha256(content).hexdigest(),
        byte_count=len(content),
    )


def test_typed_parser_accepts_consistent_document_and_facts(tmp_path) -> None:
    content = json.dumps(_payload()).encode()
    parser = TypedSourceParser(
        json_object_parser,
        parser_version="official-json-v1",
        quarantine=ParseQuarantineStore(tmp_path),
    )

    batch = parser.parse(_snapshot(content), content)

    assert batch.document.document_id == "official-document"
    assert batch.facts[0].document_id == batch.document.document_id
    assert not list(tmp_path.iterdir())


def test_cross_record_validation_failure_writes_sanitized_quarantine(tmp_path) -> None:
    payload = _payload(fact_document_id="different-secret-document")
    content = json.dumps(payload).encode()
    parser = TypedSourceParser(
        json_object_parser,
        parser_version="official-json-v1",
        quarantine=ParseQuarantineStore(tmp_path),
    )

    with pytest.raises(SourceParseRejectedError, match="ValidationError"):
        parser.parse(_snapshot(content), content)

    receipts = list(tmp_path.glob("*.json"))
    assert len(receipts) == 1
    serialized = receipts[0].read_text()
    assert "different-secret-document" not in serialized
    assert "ValidationError" in serialized
    assert receipts[0].stat().st_mode & 0o777 == 0o600


def test_snapshot_hash_mismatch_is_quarantined_before_parser_call(tmp_path) -> None:
    calls = 0

    def parser(content):
        nonlocal calls
        calls += 1
        return json.loads(content)

    valid = json.dumps(_payload()).encode()
    typed = TypedSourceParser(
        parser,
        parser_version="official-json-v1",
        quarantine=ParseQuarantineStore(tmp_path),
    )

    with pytest.raises(SourceParseRejectedError, match="ValueError"):
        typed.parse(_snapshot(valid), b"tampered content")

    assert calls == 0
    assert len(list(tmp_path.glob("*.json"))) == 1
