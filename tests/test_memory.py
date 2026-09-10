from datetime import UTC, datetime, timedelta

import pytest

from travelmind.context.builder import BudgetedContextBuilder, build_context_items
from travelmind.context.models import ContextBudget
from travelmind.memory import (
    InMemoryMemoryStore,
    MemoryDeletionError,
    MemoryManager,
    MemoryScope,
    MemoryTurn,
    memory_context_items,
)
from travelmind.schemas import TravelRequest


def _turn(identity: str, content: str, now: datetime) -> MemoryTurn:
    return MemoryTurn(turn_id=identity, role="user", content=content, created_at=now)


def test_thread_history_is_isolated_by_tenant_user_and_thread() -> None:
    now = datetime(2026, 9, 9, tzinfo=UTC)
    manager = MemoryManager(InMemoryMemoryStore(clock=lambda: now))
    owner = MemoryScope(tenant_id="company-a", user_id="user-1", thread_id="trip-1")
    other_thread = owner.model_copy(update={"thread_id": "trip-2"})
    other_user = owner.model_copy(update={"user_id": "user-2"})
    other_tenant = owner.model_copy(update={"tenant_id": "company-b"})

    manager.append_turn(owner, _turn("turn-1", "只属于当前会话", now))

    assert [item.content for item in manager.load(owner).turns] == ["只属于当前会话"]
    assert manager.load(other_thread).turns == []
    assert manager.load(other_user).turns == []
    assert manager.load(other_tenant).turns == []


def test_short_term_memory_expires_and_is_capacity_bounded() -> None:
    current = [datetime(2026, 9, 9, tzinfo=UTC)]
    store = InMemoryMemoryStore(
        short_term_ttl=timedelta(minutes=10),
        max_turns_per_thread=2,
        clock=lambda: current[0],
    )
    manager = MemoryManager(store)
    scope = MemoryScope(tenant_id="t", user_id="u", thread_id="thread")
    for index in range(3):
        manager.append_turn(scope, _turn(f"turn-{index}", str(index), current[0]))

    assert [item.turn_id for item in manager.load(scope).turns] == ["turn-1", "turn-2"]

    current[0] += timedelta(minutes=11)
    assert manager.load(scope).turns == []


def test_turn_write_is_idempotent_and_stale_preference_cannot_overwrite() -> None:
    now = datetime(2026, 9, 9, tzinfo=UTC)
    manager = MemoryManager(InMemoryMemoryStore(clock=lambda: now))
    scope = MemoryScope(tenant_id="t", user_id="u", thread_id="thread")
    turn = _turn("same-id", "same content", now)

    manager.append_turn(scope, turn)
    manager.append_turn(scope, turn)
    manager.remember_preference(scope, key="pace", value="relaxed", updated_at=now, consent=True)
    stale = manager.remember_preference(
        scope,
        key="pace",
        value="intensive",
        updated_at=now - timedelta(days=1),
        consent=True,
    )

    assert len(manager.load(scope).turns) == 1
    assert stale.reason_code == "stale_update_ignored"
    assert manager.load(scope).preferences[0].value == "relaxed"


def test_long_term_preferences_require_consent_and_are_user_scoped() -> None:
    now = datetime(2026, 9, 9, tzinfo=UTC)
    manager = MemoryManager(InMemoryMemoryStore(clock=lambda: now))
    first = MemoryScope(tenant_id="t", user_id="u", thread_id="one")
    second = first.model_copy(update={"thread_id": "two"})

    denied = manager.remember_preference(
        first, key="pace", value="relaxed", updated_at=now, consent=False
    )
    rejected = manager.remember_preference(
        first, key="passport_number", value="secret", updated_at=now, consent=True
    )
    stored = manager.remember_preference(
        first, key="pace", value="relaxed", updated_at=now, consent=True
    )

    assert denied.reason_code == "consent_required"
    assert rejected.reason_code == "preference_key_rejected"
    assert stored.persisted is True
    assert manager.load(first).preferences == manager.load(second).preferences


def test_current_request_overrides_stored_preferences_in_context() -> None:
    now = datetime(2026, 9, 9, tzinfo=UTC)
    manager = MemoryManager(InMemoryMemoryStore(clock=lambda: now))
    scope = MemoryScope(tenant_id="t", user_id="u", thread_id="one")
    manager.remember_preference(scope, key="pace", value="relaxed", updated_at=now, consent=True)
    manager.remember_preference(
        scope, key="interests", value="history", updated_at=now, consent=True
    )

    items = memory_context_items(manager.load(scope), overridden_preference_keys={"pace"})

    assert "history" in items[0].content
    assert "relaxed" not in items[0].content
    assert items[0].mandatory is False


def test_optional_memory_cannot_evict_current_request_from_budget() -> None:
    now = datetime(2026, 9, 9, tzinfo=UTC)
    manager = MemoryManager(InMemoryMemoryStore(max_turns_per_thread=3, clock=lambda: now))
    scope = MemoryScope(tenant_id="t", user_id="u", thread_id="one")
    for index in range(3):
        manager.append_turn(scope, _turn(str(index), "很长的历史内容" * 100, now))
    items = [
        *build_context_items(TravelRequest(query="当前明确请求：只安排故宫"), []),
        *memory_context_items(manager.load(scope)),
    ]
    budget = ContextBudget(max_context_tokens=260, reserved_output_tokens=60)

    packed = BudgetedContextBuilder(budget).build(items)

    assert "user-request" in packed.trace.included_item_ids
    assert "当前明确请求：只安排故宫" in packed.rendered
    assert packed.trace.dropped_item_ids


def test_forget_thread_preserves_preferences_and_other_threads() -> None:
    now = datetime(2026, 9, 9, tzinfo=UTC)
    manager = MemoryManager(InMemoryMemoryStore(clock=lambda: now))
    first = MemoryScope(tenant_id="t", user_id="u", thread_id="one")
    second = first.model_copy(update={"thread_id": "two"})
    manager.append_turn(first, _turn("one", "first", now))
    manager.append_turn(second, _turn("two", "second", now))
    manager.remember_preference(first, key="pace", value="relaxed", updated_at=now, consent=True)

    manager.forget_thread(first)

    assert manager.load(first).turns == []
    assert len(manager.load(first).preferences) == 1
    assert len(manager.load(second).turns) == 1

    manager.forget_user(first)
    assert manager.load(second).turns == []
    assert manager.load(second).preferences == []


def test_store_outage_degrades_reads_and_writes_but_deletion_fails_closed() -> None:
    class BrokenStore:
        def __getattr__(self, name: str):
            def fail(*args, **kwargs):
                del args, kwargs
                raise RuntimeError(f"secret failure in {name}")

            return fail

    now = datetime(2026, 9, 9, tzinfo=UTC)
    manager = MemoryManager(BrokenStore())
    scope = MemoryScope(tenant_id="t", user_id="u", thread_id="one")

    snapshot = manager.load(scope)
    write = manager.append_turn(scope, _turn("one", "private", now))

    assert snapshot.turns == []
    assert snapshot.degraded_components == ["memory_store"]
    assert write.persisted is False
    assert "secret" not in write.model_dump_json()
    with pytest.raises(MemoryDeletionError, match="could not be confirmed"):
        manager.forget_user(scope)
