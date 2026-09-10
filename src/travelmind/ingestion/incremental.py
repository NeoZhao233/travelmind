from __future__ import annotations

import hashlib
from copy import deepcopy

from pydantic import BaseModel, Field

from travelmind.domain.models import FactRecord, SourceDocument
from travelmind.ingestion.parsing import ParsedSourceBatch
from travelmind.ingestion.reconciliation import (
    FactConflictResolver,
    FactResolution,
    semantic_fact_key,
)


class IncrementalUpdateResult(BaseModel):
    status: str
    changed: bool
    affected_key_count: int = Field(ge=0)
    total_key_count: int = Field(ge=0)
    selected_key_count: int = Field(ge=0)
    unresolved_key_count: int = Field(ge=0)


class IncrementalFactIndex:
    """Atomic in-memory reference index that recomputes only changed source keys."""

    def __init__(self, resolver: FactConflictResolver | None = None) -> None:
        self._resolver = resolver or FactConflictResolver()
        self._documents: dict[str, SourceDocument] = {}
        self._facts: dict[str, FactRecord] = {}
        self._batch_hashes: dict[str, str] = {}
        self._resolutions: dict[str, FactResolution] = {}

    @property
    def active_facts(self) -> list[FactRecord]:
        selected_ids = {
            resolution.selected_fact_id
            for resolution in self._resolutions.values()
            if resolution.status == "selected" and resolution.selected_fact_id is not None
        }
        return [deepcopy(self._facts[identity]) for identity in sorted(selected_ids)]

    @property
    def resolutions(self) -> list[FactResolution]:
        return [deepcopy(self._resolutions[key]) for key in sorted(self._resolutions)]

    def apply(self, batch: ParsedSourceBatch) -> IncrementalUpdateResult:
        document_id = batch.document.document_id
        batch_hash = hashlib.sha256(batch.model_dump_json().encode()).hexdigest()
        if self._batch_hashes.get(document_id) == batch_hash:
            return self._result(status="no_op", changed=False, affected=0)

        documents = deepcopy(self._documents)
        facts = deepcopy(self._facts)
        resolutions = deepcopy(self._resolutions)
        old_facts = [fact for fact in facts.values() if fact.document_id == document_id]
        affected = {semantic_fact_key(fact) for fact in old_facts}
        for fact in old_facts:
            del facts[fact.fact_id]
        documents[document_id] = batch.document
        for fact in batch.facts:
            existing = facts.get(fact.fact_id)
            if existing is not None and existing.document_id != document_id:
                raise ValueError("fact ID collides with another source document")
            facts[fact.fact_id] = fact
            affected.add(semantic_fact_key(fact))

        for key in affected:
            candidates = [fact for fact in facts.values() if semantic_fact_key(fact) == key]
            if not candidates:
                resolutions.pop(key, None)
                continue
            resolved = self._resolver.resolve(candidates, documents)
            if len(resolved) != 1 or resolved[0].fact_key != key:
                raise RuntimeError("resolver returned an invalid incremental result")
            resolutions[key] = resolved[0]

        self._documents = documents
        self._facts = facts
        self._resolutions = resolutions
        self._batch_hashes[document_id] = batch_hash
        return self._result(status="updated", changed=True, affected=len(affected))

    def _result(self, *, status: str, changed: bool, affected: int) -> IncrementalUpdateResult:
        selected = sum(resolution.status == "selected" for resolution in self._resolutions.values())
        unresolved = len(self._resolutions) - selected
        return IncrementalUpdateResult(
            status=status,
            changed=changed,
            affected_key_count=affected,
            total_key_count=len(self._resolutions),
            selected_key_count=selected,
            unresolved_key_count=unresolved,
        )
