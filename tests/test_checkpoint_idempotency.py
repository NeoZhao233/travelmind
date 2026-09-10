import threading

import pytest

from travelmind.agentic.builder import build_agentic_travel_graph
from travelmind.execution import (
    IdempotencyInProgressError,
    IdempotentPlanner,
    InMemoryReceiptStore,
    build_idempotency_key,
    build_in_memory_checkpointer,
)
from travelmind.planner.demo import DemoPlanner
from travelmind.retrieval.base import InMemoryRetriever
from travelmind.schemas import Evidence, TravelRequest


def _evidence(identity: str = "complete-evidence") -> Evidence:
    return Evidence(
        id=identity,
        content="官方门票票价、开放时间、预约规则、入口交通与无障碍设施。",
        source_url="https://example.invalid/checkpoint",
        source_type="official",
        score=1,
        metadata={"place_id": "place-1", "name": "Place One", "cost": 20},
    )


class CountingPlanner(DemoPlanner):
    def __init__(self) -> None:
        self.calls = 0

    def generate(self, request, evidence):
        self.calls += 1
        return super().generate(request, evidence)


def test_graph_resumes_after_generate_without_repeating_planner() -> None:
    saver = build_in_memory_checkpointer()
    planner = CountingPlanner()
    config = {"configurable": {"thread_id": "tenant-a:user-a:thread-a"}}
    graph = build_agentic_travel_graph(
        retriever=InMemoryRetriever([_evidence()]),
        planner=planner,
        checkpointer=saver,
        interrupt_after=["generate"],
    )

    interrupted = graph.invoke({"request": TravelRequest(query="故宫门票和开放时间")}, config)

    assert interrupted["status"] == "generated"
    assert graph.get_state(config).next == ("validate",)
    assert planner.calls == 1

    rebuilt_graph = build_agentic_travel_graph(
        retriever=InMemoryRetriever([_evidence()]),
        planner=planner,
        checkpointer=saver,
        interrupt_after=["generate"],
    )
    resumed = rebuilt_graph.invoke(None, config)

    assert resumed["status"] == "completed"
    assert rebuilt_graph.get_state(config).next == ()
    assert planner.calls == 1


def test_checkpointed_graph_requires_explicit_thread_identity() -> None:
    graph = build_agentic_travel_graph(
        retriever=InMemoryRetriever([_evidence()]),
        planner=DemoPlanner(),
        checkpointer=build_in_memory_checkpointer(),
    )

    with pytest.raises(ValueError, match="thread_id"):
        graph.invoke({"request": TravelRequest(query="故宫门票")})


def test_idempotent_planner_replays_completed_receipt() -> None:
    inner = CountingPlanner()
    wrapper = IdempotentPlanner(
        inner,
        receipt_store=InMemoryReceiptStore(),
        execution_scope="tenant-a:user-a:thread-a",
        planner_version="demo-v1",
    )
    request = TravelRequest(query="故宫门票")

    first = wrapper.generate(request, [_evidence()])
    second = wrapper.generate(request, [_evidence()])

    assert first == second
    assert first is not second
    assert inner.calls == 1
    assert wrapper.execution_count == 1
    assert wrapper.replay_count == 1


def test_in_progress_receipt_rejects_concurrent_duplicate() -> None:
    store: InMemoryReceiptStore[str] = InMemoryReceiptStore()
    entered = threading.Event()
    release = threading.Event()

    def slow_operation() -> str:
        entered.set()
        release.wait(timeout=2)
        return "done"

    worker = threading.Thread(target=lambda: store.execute("same-key", slow_operation))
    worker.start()
    assert entered.wait(timeout=1)
    with pytest.raises(IdempotencyInProgressError):
        store.execute("same-key", lambda: "duplicate")
    release.set()
    worker.join(timeout=2)
    assert not worker.is_alive()


def test_idempotency_key_is_scoped_hashed_and_version_sensitive() -> None:
    first = build_idempotency_key(
        scope="tenant-a:user-a:thread-a",
        operation="planner.generate",
        payload={"query": "passport-secret", "version": "v1"},
    )
    second = build_idempotency_key(
        scope="tenant-a:user-a:thread-a",
        operation="planner.generate",
        payload={"query": "passport-secret", "version": "v2"},
    )

    assert len(first) == 64
    assert "passport-secret" not in first
    assert first != second
