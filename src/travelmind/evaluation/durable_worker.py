from __future__ import annotations

import argparse
import json
from pathlib import Path

from travelmind.agentic.builder import build_agentic_travel_graph
from travelmind.execution import (
    IdempotentPlanner,
    SqliteItineraryReceiptStore,
    open_sqlite_checkpointer,
)
from travelmind.planner.demo import DemoPlanner
from travelmind.retrieval.base import InMemoryRetriever
from travelmind.schemas import Evidence, TravelRequest


class _CountingPlanner(DemoPlanner):
    def __init__(self) -> None:
        self.calls = 0

    def generate(self, request, evidence):
        self.calls += 1
        return super().generate(request, evidence)


def _evidence() -> Evidence:
    return Evidence(
        id="complete-evidence",
        content="官方门票票价、开放时间、预约规则、入口交通与无障碍设施。",
        source_url="https://example.invalid/durable",
        source_type="official",
        score=1,
        metadata={"place_id": "place-1", "name": "Place One", "cost": 20},
    )


def _checkpoint(mode: str, database: Path) -> dict:
    planner = _CountingPlanner()
    config = {"configurable": {"thread_id": "tenant-a:user-a:durable-thread"}}
    with open_sqlite_checkpointer(database) as saver:
        graph = build_agentic_travel_graph(
            retriever=InMemoryRetriever([_evidence()]),
            planner=planner,
            checkpointer=saver,
            interrupt_after=["generate"],
        )
        if mode == "checkpoint-prepare":
            result = graph.invoke({"request": TravelRequest(query="故宫门票和开放时间")}, config)
        else:
            result = graph.invoke(None, config)
        next_nodes = list(graph.get_state(config).next)
    return {
        "mode": mode,
        "status": result["status"],
        "planner_calls_in_process": planner.calls,
        "next_nodes": next_nodes,
    }


def _receipt(database: Path) -> dict:
    planner = _CountingPlanner()
    with SqliteItineraryReceiptStore(database) as receipts:
        wrapper = IdempotentPlanner(
            planner,
            receipt_store=receipts,
            execution_scope="tenant-a:user-a:durable-thread",
            planner_version="demo-v1",
        )
        wrapper.generate(TravelRequest(query="故宫门票"), [_evidence()])
    return {
        "mode": "receipt-run",
        "planner_calls_in_process": planner.calls,
        "executions": wrapper.execution_count,
        "replays": wrapper.replay_count,
    }


def main() -> None:
    parser = argparse.ArgumentParser()
    parser.add_argument(
        "mode",
        choices=["checkpoint-prepare", "checkpoint-resume", "receipt-run"],
    )
    parser.add_argument("database", type=Path)
    args = parser.parse_args()
    result = (
        _receipt(args.database)
        if args.mode == "receipt-run"
        else _checkpoint(args.mode, args.database)
    )
    print(json.dumps(result, ensure_ascii=False))


if __name__ == "__main__":
    main()
