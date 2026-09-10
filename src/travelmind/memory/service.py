from __future__ import annotations

import json
from datetime import datetime

from travelmind.context.models import ContextItem, ContextKind
from travelmind.memory.models import (
    MemoryDeletionError,
    MemoryScope,
    MemorySnapshot,
    MemoryTurn,
    MemoryWriteResult,
    UserPreference,
)
from travelmind.memory.store import MemoryStore

ALLOWED_PREFERENCE_KEYS = frozenset(
    {"pace", "interests", "budget_style", "mobility_preference", "dietary_preference"}
)


class MemoryManager:
    def __init__(self, store: MemoryStore) -> None:
        self.store = store

    def load(self, scope: MemoryScope) -> MemorySnapshot:
        try:
            return MemorySnapshot(
                turns=self.store.read_turns(scope),
                preferences=self.store.read_preferences(scope),
            )
        except Exception:
            return MemorySnapshot(degraded_components=["memory_store"])

    def append_turn(self, scope: MemoryScope, turn: MemoryTurn) -> MemoryWriteResult:
        try:
            self.store.append_turn(scope, turn)
        except Exception:
            return MemoryWriteResult(
                persisted=False,
                reason_code="memory_store_unavailable",
                degraded_components=["memory_store"],
            )
        return MemoryWriteResult(persisted=True, reason_code="stored")

    def remember_preference(
        self,
        scope: MemoryScope,
        *,
        key: str,
        value: str,
        updated_at: datetime,
        consent: bool,
    ) -> MemoryWriteResult:
        if not consent:
            return MemoryWriteResult(persisted=False, reason_code="consent_required")
        if key not in ALLOWED_PREFERENCE_KEYS:
            return MemoryWriteResult(persisted=False, reason_code="preference_key_rejected")
        preference = UserPreference(
            key=key,
            value=value,
            updated_at=updated_at,
            consent_recorded=True,
        )
        try:
            stored = self.store.put_preference(scope, preference)
        except Exception:
            return MemoryWriteResult(
                persisted=False,
                reason_code="memory_store_unavailable",
                degraded_components=["memory_store"],
            )
        if not stored:
            return MemoryWriteResult(persisted=False, reason_code="stale_update_ignored")
        return MemoryWriteResult(persisted=True, reason_code="stored_with_consent")

    def forget_thread(self, scope: MemoryScope) -> None:
        try:
            self.store.delete_thread(scope)
        except Exception as exc:
            raise MemoryDeletionError("Thread deletion could not be confirmed") from exc

    def forget_user(self, scope: MemoryScope) -> None:
        try:
            self.store.delete_user(scope)
        except Exception as exc:
            raise MemoryDeletionError("User deletion could not be confirmed") from exc


def memory_context_items(
    snapshot: MemorySnapshot,
    *,
    overridden_preference_keys: set[str] | None = None,
) -> list[ContextItem]:
    """Render optional memory; current-request keys always override stored preferences."""

    overridden = overridden_preference_keys or set()
    preferences = {
        item.key: item.value for item in snapshot.preferences if item.key not in overridden
    }
    items: list[ContextItem] = []
    if preferences:
        items.append(
            ContextItem(
                item_id="memory:user-preferences",
                kind=ContextKind.HISTORY,
                content=(
                    "以下是用户明确同意保存的历史偏好，仅作建议；当前请求优先："
                    + json.dumps(preferences, ensure_ascii=False, sort_keys=True)
                ),
                priority=65,
                mandatory=False,
                metadata={"memory_scope": "user_preferences"},
            )
        )
    for index, turn in enumerate(snapshot.turns):
        items.append(
            ContextItem(
                item_id=f"memory:turn:{turn.turn_id}",
                kind=ContextKind.HISTORY,
                content=f"{turn.role}: {turn.content}",
                priority=min(64, 50 + index),
                mandatory=False,
                metadata={"memory_scope": "thread"},
            )
        )
    return items
