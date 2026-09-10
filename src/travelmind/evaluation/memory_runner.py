from __future__ import annotations

from datetime import UTC, datetime, timedelta
from typing import Any

from travelmind.memory import (
    InMemoryMemoryStore,
    MemoryDeletionError,
    MemoryManager,
    MemoryScope,
    MemoryTurn,
    memory_context_items,
)


def run_memory_isolation_experiment() -> dict[str, Any]:
    current = [datetime(2026, 9, 9, tzinfo=UTC)]
    store = InMemoryMemoryStore(
        short_term_ttl=timedelta(minutes=30),
        max_turns_per_thread=3,
        clock=lambda: current[0],
    )
    manager = MemoryManager(store)
    owner = MemoryScope(tenant_id="tenant-a", user_id="user-a", thread_id="thread-a")
    scopes = {
        "other_thread": owner.model_copy(update={"thread_id": "thread-b"}),
        "other_user": owner.model_copy(update={"user_id": "user-b"}),
        "other_tenant": owner.model_copy(update={"tenant_id": "tenant-b"}),
    }
    manager.append_turn(
        owner,
        MemoryTurn(
            turn_id="sensitive-turn",
            role="user",
            content="private itinerary",
            created_at=current[0],
        ),
    )
    probes: list[dict[str, Any]] = []
    for name, scope in scopes.items():
        leaked = bool(manager.load(scope).turns)
        probes.append({"probe": name, "category": "isolation", "passed": not leaked})

    same_thread_visible = len(manager.load(owner).turns) == 1
    probes.append({"probe": "owner_read", "category": "lifecycle", "passed": same_thread_visible})
    for index in range(4):
        manager.append_turn(
            owner,
            MemoryTurn(
                turn_id=f"bounded-{index}",
                role="user",
                content=f"turn {index}",
                created_at=current[0],
            ),
        )
    probes.append(
        {
            "probe": "capacity_bound",
            "category": "lifecycle",
            "passed": len(manager.load(owner).turns) == 3,
        }
    )
    current[0] += timedelta(minutes=31)
    probes.append(
        {
            "probe": "ttl_expiration",
            "category": "lifecycle",
            "passed": manager.load(owner).turns == [],
        }
    )
    denied = manager.remember_preference(
        owner,
        key="pace",
        value="relaxed",
        updated_at=current[0],
        consent=False,
    )
    stored = manager.remember_preference(
        owner,
        key="pace",
        value="relaxed",
        updated_at=current[0],
        consent=True,
    )
    probes.extend(
        [
            {
                "probe": "consent_required",
                "category": "privacy",
                "passed": not denied.persisted,
            },
            {
                "probe": "consented_preference",
                "category": "privacy",
                "passed": stored.persisted,
            },
            {
                "probe": "current_request_override",
                "category": "privacy",
                "passed": not memory_context_items(
                    manager.load(owner), overridden_preference_keys={"pace"}
                ),
            },
        ]
    )
    repeated_turn = MemoryTurn(
        turn_id="idempotent-turn",
        role="user",
        content="retry-safe",
        created_at=current[0],
    )
    manager.append_turn(owner, repeated_turn)
    manager.append_turn(owner, repeated_turn)
    stale = manager.remember_preference(
        owner,
        key="pace",
        value="intensive",
        updated_at=current[0] - timedelta(days=1),
        consent=True,
    )
    probes.extend(
        [
            {
                "probe": "idempotent_turn_write",
                "category": "lifecycle",
                "passed": len(manager.load(owner).turns) == 1,
            },
            {
                "probe": "stale_preference_ignored",
                "category": "privacy",
                "passed": stale.reason_code == "stale_update_ignored"
                and manager.load(owner).preferences[0].value == "relaxed",
            },
        ]
    )

    class BrokenStore:
        def __getattr__(self, name: str):
            def fail(*args, **kwargs):
                del args, kwargs
                raise RuntimeError(name)

            return fail

    broken = MemoryManager(BrokenStore())
    stateless = broken.load(owner)
    write = broken.append_turn(
        owner,
        MemoryTurn(
            turn_id="failed-write",
            role="user",
            content="not persisted",
            created_at=current[0],
        ),
    )
    try:
        broken.forget_user(owner)
    except MemoryDeletionError:
        deletion_failed_closed = True
    else:
        deletion_failed_closed = False
    probes.extend(
        [
            {
                "probe": "read_outage_stateless",
                "category": "outage",
                "passed": not stateless.turns and stateless.degraded_components == ["memory_store"],
            },
            {
                "probe": "write_outage_disclosed",
                "category": "outage",
                "passed": not write.persisted,
            },
            {
                "probe": "delete_outage_fail_closed",
                "category": "outage",
                "passed": deletion_failed_closed,
            },
        ]
    )
    isolation = [probe for probe in probes if probe["category"] == "isolation"]
    metrics = {
        "probes": len(probes),
        "cross_scope_leakage_rate": 1
        - sum(probe["passed"] for probe in isolation) / len(isolation),
        "lifecycle_probe_accuracy": sum(
            probe["passed"] for probe in probes if probe["category"] == "lifecycle"
        )
        / sum(probe["category"] == "lifecycle" for probe in probes),
        "privacy_probe_accuracy": sum(
            probe["passed"] for probe in probes if probe["category"] == "privacy"
        )
        / sum(probe["category"] == "privacy" for probe in probes),
        "outage_probe_accuracy": sum(
            probe["passed"] for probe in probes if probe["category"] == "outage"
        )
        / sum(probe["category"] == "outage" for probe in probes),
    }
    gate_passed = (
        metrics["cross_scope_leakage_rate"] == 0
        and metrics["lifecycle_probe_accuracy"] == 1
        and metrics["privacy_probe_accuracy"] == 1
        and metrics["outage_probe_accuracy"] == 1
    )
    return {
        "schema_version": 1,
        "experiment": "memory-isolation-controlled-v1",
        "configuration": {
            "scope": "tenant_id/user_id/thread_id",
            "short_term_ttl_minutes": 30,
            "max_turns_per_thread": 3,
            "long_term_preference_consent": "required",
        },
        "metrics": metrics,
        "selection": {
            "selected_policy": "scoped-memory-v1" if gate_passed else "stateless",
            "gate_passed": gate_passed,
        },
        "probes": probes,
        "limitations": [
            "This validates store semantics in process, not Redis ACLs or network behavior.",
            "The experiment uses deterministic synthetic identities and timestamps.",
            "Long-term preference extraction from natural language is not implemented.",
            "Checkpoint persistence remains a separate Stage 7 concern.",
        ],
    }
