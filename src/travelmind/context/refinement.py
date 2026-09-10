from __future__ import annotations

import re
from collections import defaultdict
from datetime import UTC, datetime
from difflib import SequenceMatcher

from travelmind.context.coverage import decode_aspects
from travelmind.context.models import (
    ConflictTrace,
    ContextItem,
    ContextKind,
    DuplicateGroupTrace,
    EvidenceRefinementTrace,
    RefinedContextItems,
)
from travelmind.context.tokenization import HeuristicTokenEstimator, TokenEstimator

_AUTHORITY_RANK = {
    "official_operator": 4,
    "government": 3,
    "official_aggregator": 2,
    "official": 2,
    "third_party": 1,
    "guide": 1,
}
_ASPECT_TERMS = {
    "opening_hours": ("开放", "闭馆", "停止入", "周一", "时间"),
    "admission": ("门票", "联票", "免费", "元", "价格"),
    "booking": ("预约", "实名", "余票"),
    "access": ("入口", "出口", "路线", "门"),
    "accessibility": ("无障碍", "行动不便", "长辈"),
    "transport": ("交通", "地铁", "公交", "步行"),
    "description": ("历史", "文化", "建筑", "园林", "景观"),
}
_CRITICAL_PATTERN = re.compile(r"\d|免费|不销售|无需|不得|关闭|闭馆|除外|例外|可能|必须|需要|停止")
_NORMALIZE_PATTERN = re.compile(r"[\W_]+", re.UNICODE)
_SENTENCE_PATTERN = re.compile(r"(?<=[。！？!?；;])\s*")


def _normalized(text: str) -> str:
    return _NORMALIZE_PATTERN.sub("", text).casefold()


def _timestamp(item: ContextItem) -> datetime | None:
    raw = item.metadata.get("observed_at") or item.metadata.get("source_updated_at")
    if not raw:
        return None
    try:
        value = datetime.fromisoformat(raw.replace("Z", "+00:00"))
    except ValueError:
        return None
    return value if value.tzinfo else value.replace(tzinfo=UTC)


def _authority(item: ContextItem) -> int:
    label = item.metadata.get("authority") or item.metadata.get("source_type", "")
    return _AUTHORITY_RANK.get(label, 0)


def _winner_key(item: ContextItem) -> tuple[int, float, int]:
    observed = _timestamp(item)
    return (_authority(item), observed.timestamp() if observed else float("-inf"), item.priority)


class EvidenceRefiner:
    def __init__(
        self,
        *,
        duplicate_threshold: float = 0.92,
        compression_target_tokens: int = 120,
        estimator: TokenEstimator | None = None,
    ) -> None:
        if not 0.8 <= duplicate_threshold <= 1:
            raise ValueError("duplicate_threshold must be between 0.8 and 1")
        if compression_target_tokens < 16:
            raise ValueError("compression_target_tokens must be at least 16")
        self.duplicate_threshold = duplicate_threshold
        self.compression_target_tokens = compression_target_tokens
        self.estimator = estimator or HeuristicTokenEstimator()

    def _deduplicate(
        self, evidence: list[ContextItem]
    ) -> tuple[list[ContextItem], list[DuplicateGroupTrace]]:
        groups: list[list[ContextItem]] = []
        for item in evidence:
            normalized = _normalized(item.content)
            for group in groups:
                representative = group[0]
                same_fact = item.metadata.get("fact_key") and item.metadata.get(
                    "fact_key"
                ) == representative.metadata.get("fact_key")
                different_values = (
                    item.metadata.get("fact_value") is not None
                    and representative.metadata.get("fact_value") is not None
                    and item.metadata["fact_value"] != representative.metadata["fact_value"]
                )
                if same_fact and different_values:
                    continue
                similarity = SequenceMatcher(
                    None, normalized, _normalized(representative.content)
                ).ratio()
                if similarity >= self.duplicate_threshold:
                    group.append(item)
                    break
            else:
                groups.append([item])
        kept: list[ContextItem] = []
        traces: list[DuplicateGroupTrace] = []
        for group in groups:
            winner = max(group, key=_winner_key)
            if len(group) > 1:
                merged_ids = sorted(
                    item.metadata.get("document_id", item.item_id) for item in group
                )
                winner = winner.model_copy(
                    update={
                        "metadata": {
                            **winner.metadata,
                            "merged_document_ids": ",".join(merged_ids),
                        }
                    }
                )
                traces.append(
                    DuplicateGroupTrace(
                        kept_item_id=winner.item_id,
                        suppressed_item_ids=sorted(
                            item.item_id for item in group if item.item_id != winner.item_id
                        ),
                    )
                )
            kept.append(winner)
        return kept, traces

    def _resolve_conflicts(
        self, evidence: list[ContextItem]
    ) -> tuple[list[ContextItem], list[ConflictTrace]]:
        by_key: dict[str, list[ContextItem]] = defaultdict(list)
        passthrough: list[ContextItem] = []
        for item in evidence:
            if key := item.metadata.get("fact_key"):
                by_key[key].append(item)
            else:
                passthrough.append(item)
        retained = list(passthrough)
        traces: list[ConflictTrace] = []
        for key, group in by_key.items():
            values = {item.metadata.get("fact_value") for item in group}
            if len(values) <= 1:
                retained.extend(group)
                continue
            ordered = sorted(group, key=_winner_key, reverse=True)
            top, runner_up = ordered[0], ordered[1]
            top_time, runner_time = _timestamp(top), _timestamp(runner_up)
            authority_wins = _authority(top) > _authority(runner_up)
            freshness_wins = (
                _authority(top) == _authority(runner_up)
                and top_time is not None
                and runner_time is not None
                and top_time > runner_time
            )
            if authority_wins or freshness_wins:
                retained.append(top)
                traces.append(
                    ConflictTrace(
                        fact_key=key,
                        status="resolved",
                        kept_item_ids=[top.item_id],
                        suppressed_item_ids=[item.item_id for item in ordered[1:]],
                        reason_code=("higher_authority" if authority_wins else "newer_observation"),
                    )
                )
            else:
                retained.extend(group)
                traces.append(
                    ConflictTrace(
                        fact_key=key,
                        status="unresolved",
                        kept_item_ids=[item.item_id for item in group],
                        reason_code="insufficient_precedence",
                    )
                )
        original_order = {item.item_id: index for index, item in enumerate(evidence)}
        retained.sort(key=lambda item: original_order[item.item_id])
        return retained, traces

    def _compress(self, item: ContextItem, targets: set[str]) -> tuple[ContextItem, bool]:
        if self.estimator.estimate(item.content) <= self.compression_target_tokens:
            return item, False
        sentences = [part for part in _SENTENCE_PATTERN.split(item.content) if part]
        terms = tuple(term for aspect in targets for term in _ASPECT_TERMS.get(aspect, ()))
        ranked = sorted(
            enumerate(sentences),
            key=lambda pair: (
                -(
                    4 * sum(term in pair[1] for term in terms)
                    + 3 * bool(_CRITICAL_PATTERN.search(pair[1]))
                    + (1 if pair[0] == 0 else 0)
                ),
                pair[0],
            ),
        )
        chosen: list[tuple[int, str]] = []
        for index, sentence in ranked:
            candidate = "".join(value for _, value in sorted([*chosen, (index, sentence)]))
            if self.estimator.estimate(candidate) <= self.compression_target_tokens:
                chosen.append((index, sentence))
        if not chosen:
            return item, False
        content = "".join(value for _, value in sorted(chosen))
        if len(content) >= len(item.content):
            return item, False
        return item.model_copy(update={"content": content}), True

    def refine(
        self,
        items: list[ContextItem],
        coverage_targets: set[str] | None = None,
    ) -> RefinedContextItems:
        passthrough = [item for item in items if item.kind != ContextKind.EVIDENCE]
        evidence = [item for item in items if item.kind == ContextKind.EVIDENCE]
        before = sum(self.estimator.estimate(item.content) for item in evidence)
        deduplicated, duplicate_traces = self._deduplicate(evidence)
        reconciled, conflict_traces = self._resolve_conflicts(deduplicated)
        compressed: list[ContextItem] = []
        compressed_ids: list[str] = []
        skipped_ids: list[str] = []
        for item in reconciled:
            targets = set(coverage_targets or set()) | decode_aspects(item.metadata.get("aspects"))
            refined, changed = self._compress(item, targets)
            compressed.append(refined)
            if changed:
                compressed_ids.append(item.item_id)
            elif self.estimator.estimate(item.content) > self.compression_target_tokens:
                skipped_ids.append(item.item_id)
        after = sum(self.estimator.estimate(item.content) for item in compressed)
        original_order = {item.item_id: index for index, item in enumerate(items)}
        output = [*passthrough, *compressed]
        output.sort(key=lambda item: original_order[item.item_id])
        return RefinedContextItems(
            items=output,
            trace=EvidenceRefinementTrace(
                duplicate_groups=duplicate_traces,
                conflicts=conflict_traces,
                compressed_item_ids=compressed_ids,
                compression_skipped_item_ids=skipped_ids,
                estimated_evidence_tokens_before=before,
                estimated_evidence_tokens_after=after,
                degraded_components=(
                    ["token_estimator"] if getattr(self.estimator, "degraded", False) else []
                ),
            ),
        )
