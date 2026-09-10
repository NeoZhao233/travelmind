from __future__ import annotations

import hashlib

from langgraph.checkpoint.memory import InMemorySaver

from travelmind.agentic.builder import build_agentic_travel_graph
from travelmind.execution import (
    IdempotentPlanner,
    InMemoryReceiptStore,
    build_in_memory_checkpointer,
)
from travelmind.planner.demo import DemoPlanner
from travelmind.retrieval.base import InMemoryRetriever
from travelmind.schemas import Evidence, Itinerary, TravelRequest


class _CountingPlanner(DemoPlanner):
    def __init__(self) -> None:
        self.calls = 0

    def generate(self, request, evidence):
        self.calls += 1
        return super().generate(request, evidence)


class _BrokenSaver(InMemorySaver):
    def put(self, config, checkpoint, metadata, new_versions):
        del config, checkpoint, metadata, new_versions
        raise ConnectionError("checkpoint backend secret")


def _evidence() -> Evidence:
    return Evidence(
        id="complete-evidence",
        content="官方门票票价、开放时间、预约规则、入口交通与无障碍设施。",
        source_url="https://example.invalid/checkpoint",
        source_type="official",
        score=1,
        metadata={"place_id": "place-1", "name": "Place One", "cost": 20},
    )


def run_checkpoint_idempotency_drill() -> dict:
    saver = build_in_memory_checkpointer()
    planner = _CountingPlanner()
    retriever = InMemoryRetriever([_evidence()])
    config = {"configurable": {"thread_id": "tenant-a:user-a:thread-a"}}
    first_graph = build_agentic_travel_graph(
        retriever=retriever,
        planner=planner,
        checkpointer=saver,
        interrupt_after=["generate"],
    )
    interrupted = first_graph.invoke({"request": TravelRequest(query="故宫门票和开放时间")}, config)
    next_before_resume = list(first_graph.get_state(config).next)
    rebuilt_graph = build_agentic_travel_graph(
        retriever=retriever,
        planner=planner,
        checkpointer=saver,
        interrupt_after=["generate"],
    )
    resumed = rebuilt_graph.invoke(None, config)
    next_after_resume = list(rebuilt_graph.get_state(config).next)

    inner = _CountingPlanner()
    receipts: InMemoryReceiptStore[Itinerary] = InMemoryReceiptStore()
    idempotent = IdempotentPlanner(
        inner,
        receipt_store=receipts,
        execution_scope="tenant-a:user-a:thread-a",
        planner_version="demo-v1",
    )
    request = TravelRequest(query="故宫门票")
    first_output = idempotent.generate(request, [_evidence()])
    replayed_output = idempotent.generate(request, [_evidence()])

    try:
        broken_graph = build_agentic_travel_graph(
            retriever=retriever,
            planner=DemoPlanner(),
            checkpointer=_BrokenSaver(),
        )
        broken_graph.invoke(
            {"request": TravelRequest(query="故宫门票")},
            {"configurable": {"thread_id": "broken-thread"}},
        )
        checkpoint_failure_closed = False
        checkpoint_error_type = None
    except Exception as exc:
        checkpoint_failure_closed = True
        checkpoint_error_type = type(exc).__name__

    checks = {
        "interrupted_after_generate": (
            interrupted["status"] == "generated" and next_before_resume == ["validate"]
        ),
        "rebuilt_graph_resumed_to_completion": (
            resumed["status"] == "completed" and next_after_resume == []
        ),
        "planner_not_repeated_on_resume": planner.calls == 1,
        "completed_receipt_replayed": (
            first_output == replayed_output
            and first_output is not replayed_output
            and inner.calls == 1
            and idempotent.replay_count == 1
        ),
        "checkpoint_outage_fails_closed": checkpoint_failure_closed,
        "checkpoint_error_payload_redacted": checkpoint_error_type == "ConnectionError",
    }
    return {
        "experiment": "stage7c-checkpoint-resume-and-idempotency-drill",
        "configuration_sha256": hashlib.sha256(
            b"checkpoint-v1|interrupt_after=generate|receipt-v1"
        ).hexdigest(),
        "checks": checks,
        "metrics": {
            "check_pass_rate": sum(checks.values()) / len(checks),
            "logical_resume_success_rate": float(
                resumed["status"] == "completed" and planner.calls == 1
            ),
            "duplicate_side_effect_prevention_rate": float(inner.calls == 1),
            "checkpoint_outage_safe_failure_rate": float(checkpoint_failure_closed),
        },
        "diagnostics": {
            "planner_calls_across_resume": planner.calls,
            "idempotent_planner_executions": idempotent.execution_count,
            "idempotent_planner_replays": idempotent.replay_count,
            "checkpoint_error_type": checkpoint_error_type,
        },
        "limitations": [
            "InMemorySaver validates logical resume but does not survive OS process loss.",
            "In-memory receipts do not provide cross-process uniqueness or durable recovery.",
            "A crash after an external side effect but before receipt commit remains ambiguous.",
        ],
    }
