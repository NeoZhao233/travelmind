from __future__ import annotations

from collections.abc import Callable
from datetime import UTC, datetime, timedelta
from typing import Protocol

from travelmind.memory.models import MemoryScope, MemoryTurn, UserPreference


class MemoryStore(Protocol):
    def read_turns(self, scope: MemoryScope) -> list[MemoryTurn]: ...

    def append_turn(self, scope: MemoryScope, turn: MemoryTurn) -> None: ...

    def read_preferences(self, scope: MemoryScope) -> list[UserPreference]: ...

    def put_preference(self, scope: MemoryScope, preference: UserPreference) -> bool: ...

    def delete_thread(self, scope: MemoryScope) -> None: ...

    def delete_user(self, scope: MemoryScope) -> None: ...


class InMemoryMemoryStore:
    """Deterministic reference store; tuple keys prevent delimiter-collision leakage."""

    def __init__(
        self,
        *,
        short_term_ttl: timedelta = timedelta(minutes=30),
        max_turns_per_thread: int = 8,
        clock: Callable[[], datetime] | None = None,
    ) -> None:
        if short_term_ttl <= timedelta(0):
            raise ValueError("short_term_ttl must be positive")
        if max_turns_per_thread < 1:
            raise ValueError("max_turns_per_thread must be positive")
        self.short_term_ttl = short_term_ttl
        self.max_turns_per_thread = max_turns_per_thread
        self.clock = clock or (lambda: datetime.now(UTC))
        self._turns: dict[tuple[str, str, str], list[tuple[MemoryTurn, datetime]]] = {}
        self._preferences: dict[tuple[str, str], dict[str, UserPreference]] = {}

    def _purge_expired(self, scope: MemoryScope) -> None:
        now = self.clock()
        retained = [item for item in self._turns.get(scope.thread_key, []) if item[1] > now]
        if retained:
            self._turns[scope.thread_key] = retained
        else:
            self._turns.pop(scope.thread_key, None)

    def read_turns(self, scope: MemoryScope) -> list[MemoryTurn]:
        self._purge_expired(scope)
        return [turn.model_copy(deep=True) for turn, _ in self._turns.get(scope.thread_key, [])]

    def append_turn(self, scope: MemoryScope, turn: MemoryTurn) -> None:
        self._purge_expired(scope)
        expires_at = self.clock() + self.short_term_ttl
        previous = [
            item
            for item in self._turns.get(scope.thread_key, [])
            if item[0].turn_id != turn.turn_id
        ]
        values = [*previous, (turn.model_copy(deep=True), expires_at)]
        self._turns[scope.thread_key] = values[-self.max_turns_per_thread :]

    def read_preferences(self, scope: MemoryScope) -> list[UserPreference]:
        values = self._preferences.get(scope.user_key, {})
        return [values[key].model_copy(deep=True) for key in sorted(values)]

    def put_preference(self, scope: MemoryScope, preference: UserPreference) -> bool:
        values = self._preferences.setdefault(scope.user_key, {})
        existing = values.get(preference.key)
        if existing is not None and existing.updated_at > preference.updated_at:
            return False
        values[preference.key] = preference.model_copy(deep=True)
        return True

    def delete_thread(self, scope: MemoryScope) -> None:
        self._turns.pop(scope.thread_key, None)

    def delete_user(self, scope: MemoryScope) -> None:
        for key in [key for key in self._turns if key[:2] == scope.user_key]:
            del self._turns[key]
        self._preferences.pop(scope.user_key, None)
