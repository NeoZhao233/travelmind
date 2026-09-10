from __future__ import annotations

import hashlib
import json
from collections import defaultdict
from typing import Literal

from pydantic import BaseModel, Field

from travelmind.domain.models import FactRecord, SourceAuthority, SourceDocument

_AUTHORITY_RANK = {
    SourceAuthority.OFFICIAL_OPERATOR: 4,
    SourceAuthority.GOVERNMENT: 3,
    SourceAuthority.OFFICIAL_AGGREGATOR: 2,
    SourceAuthority.THIRD_PARTY: 1,
}


def semantic_fact_key(fact: FactRecord) -> str:
    identity = json.dumps(
        {
            "place_id": fact.place_id,
            "fact_type": fact.fact_type.value,
            "unit": fact.unit,
            "qualifiers": fact.qualifiers,
            "valid_from": fact.valid_from.isoformat() if fact.valid_from else None,
            "valid_to": fact.valid_to.isoformat() if fact.valid_to else None,
        },
        ensure_ascii=False,
        sort_keys=True,
        separators=(",", ":"),
    )
    return hashlib.sha256(identity.encode()).hexdigest()


class FactResolution(BaseModel):
    fact_key: str = Field(pattern=r"^[0-9a-f]{64}$")
    status: Literal["selected", "unresolved"]
    selected_fact_id: str | None = None
    competing_fact_ids: list[str]
    reason_code: Literal[
        "single_value",
        "equivalent_values",
        "higher_authority",
        "newer_observation",
        "insufficient_precedence",
    ]


class FactConflictResolver:
    def resolve(
        self,
        facts: list[FactRecord],
        documents: dict[str, SourceDocument],
    ) -> list[FactResolution]:
        by_key: dict[str, list[FactRecord]] = defaultdict(list)
        for fact in facts:
            if fact.document_id not in documents:
                raise ValueError("fact references an unknown source document")
            by_key[semantic_fact_key(fact)].append(fact)
        return [self._resolve_group(key, group, documents) for key, group in sorted(by_key.items())]

    def _resolve_group(
        self,
        key: str,
        facts: list[FactRecord],
        documents: dict[str, SourceDocument],
    ) -> FactResolution:
        def precedence(fact: FactRecord) -> tuple[int, float, str]:
            return (
                _AUTHORITY_RANK[documents[fact.document_id].authority],
                fact.observed_at.timestamp(),
                fact.fact_id,
            )

        ordered = sorted(facts, key=precedence, reverse=True)
        by_value: dict[str, list[FactRecord]] = defaultdict(list)
        for fact in ordered:
            value_key = json.dumps(fact.value, ensure_ascii=False, sort_keys=True)
            by_value[value_key].append(fact)
        if len(by_value) == 1:
            return FactResolution(
                fact_key=key,
                status="selected",
                selected_fact_id=ordered[0].fact_id,
                competing_fact_ids=[fact.fact_id for fact in ordered],
                reason_code="single_value" if len(ordered) == 1 else "equivalent_values",
            )

        value_representatives = sorted(
            (max(group, key=precedence) for group in by_value.values()),
            key=precedence,
            reverse=True,
        )
        top, runner_up = value_representatives[:2]
        top_authority = _AUTHORITY_RANK[documents[top.document_id].authority]
        runner_authority = _AUTHORITY_RANK[documents[runner_up.document_id].authority]
        if top_authority > runner_authority:
            reason = "higher_authority"
        elif top.observed_at > runner_up.observed_at:
            reason = "newer_observation"
        else:
            return FactResolution(
                fact_key=key,
                status="unresolved",
                selected_fact_id=None,
                competing_fact_ids=[fact.fact_id for fact in ordered],
                reason_code="insufficient_precedence",
            )
        return FactResolution(
            fact_key=key,
            status="selected",
            selected_fact_id=top.fact_id,
            competing_fact_ids=[fact.fact_id for fact in ordered],
            reason_code=reason,
        )
