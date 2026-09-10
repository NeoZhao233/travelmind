from __future__ import annotations

import hashlib
import json
import tempfile
from datetime import UTC, datetime, timedelta
from pathlib import Path

from travelmind.domain.models import FactRecord, SourceDocument
from travelmind.ingestion import (
    FactConflictResolver,
    IncrementalFactIndex,
    ParsedSourceBatch,
    ParseQuarantineStore,
    SnapshotReceipt,
    SourceParseRejectedError,
    TypedSourceParser,
    json_object_parser,
)

_NOW = datetime(2026, 9, 9, tzinfo=UTC)
_URL = "https://official.example/source"


def _document(
    identity: str,
    authority: str,
    *,
    source_url: str | None = None,
) -> SourceDocument:
    return SourceDocument(
        document_id=identity,
        place_id="place-one",
        title=identity,
        section="Facts",
        content="This controlled source content is long enough for typed validation.",
        source_url=source_url or f"https://official.example/{identity}",
        authority=authority,
        freshness="dynamic",
        collected_at=_NOW,
    )


def _fact(
    identity: str,
    document_id: str,
    fact_type: str,
    value,
    *,
    observed_at: datetime = _NOW,
) -> FactRecord:
    return FactRecord(
        fact_id=identity,
        place_id="place-one",
        document_id=document_id,
        fact_type=fact_type,
        value=value,
        unit="CNY" if fact_type == "admission" else None,
        qualifiers={"scope": "standard"},
        observed_at=observed_at,
    )


def _batch(
    document: SourceDocument,
    facts: list[FactRecord],
    snapshot: str,
) -> ParsedSourceBatch:
    return ParsedSourceBatch(
        parser_version="controlled-parser-v1",
        snapshot_sha256=snapshot,
        document=document,
        facts=facts,
    )


def _snapshot(content: bytes) -> SnapshotReceipt:
    return SnapshotReceipt(
        source_id="official-source",
        source_url=_URL,
        fetched_at=_NOW,
        content_sha256=hashlib.sha256(content).hexdigest(),
        byte_count=len(content),
    )


def run_incremental_ingestion_drill() -> dict:
    with tempfile.TemporaryDirectory(prefix="travelmind-parse-") as directory:
        quarantine = ParseQuarantineStore(Path(directory))
        parsed_document = _document(
            "parsed-source",
            "official_operator",
            source_url=_URL,
        )
        valid_payload = {
            "document": parsed_document.model_dump(mode="json"),
            "facts": [
                _fact("parsed-ticket", "parsed-source", "admission", 30).model_dump(mode="json")
            ],
        }
        valid_content = json.dumps(valid_payload).encode()
        parser = TypedSourceParser(
            json_object_parser,
            parser_version="controlled-parser-v1",
            quarantine=quarantine,
        )
        parsed = parser.parse(_snapshot(valid_content), valid_content)

        invalid_payload = {
            **valid_payload,
            "facts": [
                {
                    **valid_payload["facts"][0],
                    "document_id": "mismatched-sensitive-document",
                }
            ],
        }
        invalid_content = json.dumps(invalid_payload).encode()
        try:
            parser.parse(_snapshot(invalid_content), invalid_content)
            invalid_rejected = False
        except SourceParseRejectedError:
            invalid_rejected = True
        quarantine_files = list(Path(directory).glob("*.json"))
        quarantine_text = "".join(path.read_text() for path in quarantine_files)

    resolver = FactConflictResolver()
    conflict_documents = {
        "official-source": _document("official-source", "official_operator"),
        "guide-source": _document("guide-source", "third_party"),
    }
    authority_resolution = resolver.resolve(
        [
            _fact(
                "official-price",
                "official-source",
                "admission",
                30,
                observed_at=_NOW - timedelta(days=1),
            ),
            _fact("guide-price", "guide-source", "admission", 20),
        ],
        conflict_documents,
    )[0]

    equal_documents = {
        "government-one": _document("government-one", "government"),
        "government-two": _document("government-two", "government"),
    }
    unresolved = resolver.resolve(
        [
            _fact("government-price-one", "government-one", "admission", 30),
            _fact("government-price-two", "government-two", "admission", 35),
        ],
        equal_documents,
    )[0]

    index = IncrementalFactIndex()
    ticket_document = _document("ticket-source", "official_operator")
    description_document = _document("description-source", "official_operator")
    index.apply(
        _batch(
            ticket_document,
            [_fact("ticket-v1", "ticket-source", "admission", 30)],
            "a" * 64,
        )
    )
    index.apply(
        _batch(
            description_document,
            [
                _fact(
                    "description-v1",
                    "description-source",
                    "description",
                    "historic place",
                )
            ],
            "b" * 64,
        )
    )
    update = _batch(
        ticket_document,
        [_fact("ticket-v2", "ticket-source", "admission", 35)],
        "c" * 64,
    )
    incremental = index.apply(update)
    active_after_update = index.active_facts
    no_op = index.apply(update)
    before_collision = index.active_facts
    try:
        index.apply(
            _batch(
                _document("collision-source", "third_party"),
                [
                    _fact(
                        "description-v1",
                        "collision-source",
                        "booking",
                        True,
                    )
                ],
                "d" * 64,
            )
        )
        collision_rejected = False
    except ValueError:
        collision_rejected = True

    checks = {
        "typed_payload_accepted": parsed.facts[0].value == 30,
        "invalid_cross_reference_quarantined": (invalid_rejected and len(quarantine_files) == 1),
        "quarantine_payload_redacted": ("mismatched-sensitive-document" not in quarantine_text),
        "authority_conflict_selected_official": (
            authority_resolution.selected_fact_id == "official-price"
            and authority_resolution.reason_code == "higher_authority"
        ),
        "equal_precedence_conflict_unresolved": (
            unresolved.status == "unresolved" and unresolved.selected_fact_id is None
        ),
        "incremental_update_touched_one_of_two_keys": (
            incremental.affected_key_count == 1
            and incremental.total_key_count == 2
            and {fact.value for fact in active_after_update} == {35, "historic place"}
        ),
        "identical_batch_was_no_op": (no_op.status == "no_op" and no_op.affected_key_count == 0),
        "failed_update_preserved_previous_state": (
            collision_rejected and index.active_facts == before_collision
        ),
    }
    return {
        "experiment": "stage8c-typed-parse-conflict-and-incremental-index-drill",
        "configuration_sha256": hashlib.sha256(
            b"parser-v1|authority-then-time|semantic-key|incremental-atomic"
        ).hexdigest(),
        "checks": checks,
        "metrics": {
            "check_pass_rate": sum(checks.values()) / len(checks),
            "parse_quarantine_accuracy": float(checks["invalid_cross_reference_quarantined"]),
            "conflict_policy_accuracy": (
                int(checks["authority_conflict_selected_official"])
                + int(checks["equal_precedence_conflict_unresolved"])
            )
            / 2,
            "incremental_key_recompute_ratio": (
                incremental.affected_key_count / incremental.total_key_count
            ),
            "no_op_detection_rate": float(checks["identical_batch_was_no_op"]),
            "failed_update_state_preservation_rate": float(
                checks["failed_update_preserved_previous_state"]
            ),
        },
        "limitations": [
            "The parser consumes controlled JSON rather than real HTML layouts.",
            "The incremental reference index is in memory, not Qdrant or Elasticsearch.",
            "Authority-first precedence needs source-owner review for each fact class.",
            "Unresolved facts are excluded; user-facing uncertainty integration is future work.",
        ],
    }
