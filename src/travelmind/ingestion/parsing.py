from __future__ import annotations

import hashlib
import json
import os
from collections.abc import Callable
from pathlib import Path
from typing import Any
from uuid import uuid4

from pydantic import BaseModel, Field, model_validator

from travelmind.domain.models import FactRecord, SourceDocument
from travelmind.ingestion.publishing import SnapshotReceipt


class SourceParseRejectedError(RuntimeError):
    """Parser output failed the typed ingestion boundary."""


class ParsedSourceBatch(BaseModel):
    parser_version: str = Field(min_length=1)
    snapshot_sha256: str = Field(pattern=r"^[0-9a-f]{64}$")
    document: SourceDocument
    facts: list[FactRecord] = Field(min_length=1)

    @model_validator(mode="after")
    def references_are_consistent(self) -> ParsedSourceBatch:
        fact_ids = [fact.fact_id for fact in self.facts]
        if len(fact_ids) != len(set(fact_ids)):
            raise ValueError("parsed facts contain duplicate fact IDs")
        for fact in self.facts:
            if fact.document_id != self.document.document_id:
                raise ValueError("parsed fact references a different document")
            if fact.place_id != self.document.place_id:
                raise ValueError("parsed fact place does not match its document")
        return self


class ParseQuarantineReceipt(BaseModel):
    schema_version: int = 1
    snapshot_sha256: str = Field(pattern=r"^[0-9a-f]{64}$")
    parser_version: str
    error_type: str


class ParseQuarantineStore:
    def __init__(self, root: Path) -> None:
        self.root = root.resolve()
        self.root.mkdir(parents=True, exist_ok=True)

    def record(
        self,
        *,
        snapshot_sha256: str,
        parser_version: str,
        error_type: str,
    ) -> ParseQuarantineReceipt:
        receipt = ParseQuarantineReceipt(
            snapshot_sha256=snapshot_sha256,
            parser_version=parser_version,
            error_type=error_type,
        )
        identity = hashlib.sha256(f"{snapshot_sha256}|{parser_version}".encode()).hexdigest()
        destination = self.root / f"{identity}.json"
        temporary = destination.with_name(f".{destination.name}.{uuid4().hex}.tmp")
        try:
            with temporary.open("xb") as handle:
                handle.write(receipt.model_dump_json(indent=2).encode())
                handle.flush()
                os.fsync(handle.fileno())
            temporary.chmod(0o600)
            os.replace(temporary, destination)
        finally:
            temporary.unlink(missing_ok=True)
        return receipt


class TypedSourceParser:
    def __init__(
        self,
        parser: Callable[[bytes], dict[str, Any]],
        *,
        parser_version: str,
        quarantine: ParseQuarantineStore,
    ) -> None:
        if not parser_version.strip():
            raise ValueError("parser version must be non-empty")
        self._parser = parser
        self.parser_version = parser_version
        self._quarantine = quarantine

    def parse(self, snapshot: SnapshotReceipt, content: bytes) -> ParsedSourceBatch:
        if hashlib.sha256(content).hexdigest() != snapshot.content_sha256:
            self._reject(snapshot, ValueError("snapshot content hash mismatch"))
        try:
            candidate = self._parser(content)
            batch = ParsedSourceBatch.model_validate(
                {
                    **candidate,
                    "parser_version": self.parser_version,
                    "snapshot_sha256": snapshot.content_sha256,
                }
            )
            if str(batch.document.source_url).rstrip("/") != snapshot.source_url.rstrip("/"):
                raise ValueError("parsed source URL does not match snapshot")
            return batch
        except Exception as exc:
            self._reject(snapshot, exc)

    def _reject(self, snapshot: SnapshotReceipt, exc: Exception) -> None:
        self._quarantine.record(
            snapshot_sha256=snapshot.content_sha256,
            parser_version=self.parser_version,
            error_type=type(exc).__name__,
        )
        raise SourceParseRejectedError(f"source parse rejected by {type(exc).__name__}") from exc


def json_object_parser(content: bytes) -> dict[str, Any]:
    candidate = json.loads(content)
    if not isinstance(candidate, dict):
        raise ValueError("parsed payload must be an object")
    return candidate
