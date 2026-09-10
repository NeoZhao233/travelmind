#!/usr/bin/env python3
"""Build the deterministic Stage 12 runtime fault matrix."""

from __future__ import annotations

import argparse
import json
from pathlib import Path
from typing import Any


def fault(tool: str, place: str | None, occurrence: int, mode: str) -> dict[str, Any]:
    return {"tool_name": tool, "place_id": place, "occurrence": occurrence, "mode": mode}


def repeated_faults(tool: str, place: str | None, mode: str) -> list[dict[str, Any]]:
    return [fault(tool, place, 1, mode), fault(tool, place, 2, mode)]


def case(
    name: str,
    faults: list[dict[str, Any]],
    *,
    requires_replan: bool,
    recoverable: bool,
    replans: int,
    calls: int,
    final_place: str | None,
) -> dict[str, Any]:
    return {
        "case_id": name,
        "faults": faults,
        "requires_replan": requires_replan,
        "recoverable": recoverable,
        "expected_status": "completed" if recoverable else "failed",
        "expected_replans": replans,
        "expected_tool_calls": calls,
        "expected_final_place": final_place,
        "reviewed": False,
    }


P = "forbidden-city"
F = "national-museum"

CASES = [
    case(
        "matrix-healthy",
        [],
        requires_replan=False,
        recoverable=True,
        replans=0,
        calls=4,
        final_place=P,
    ),
    case(
        "retry-search-timeout",
        [fault("candidate_search", None, 1, "timeout")],
        requires_replan=False,
        recoverable=True,
        replans=0,
        calls=5,
        final_place=P,
    ),
    case(
        "retry-availability-connection",
        [fault("availability", P, 1, "connection")],
        requires_replan=False,
        recoverable=True,
        replans=0,
        calls=5,
        final_place=P,
    ),
    case(
        "retry-booking-timeout",
        [fault("booking", P, 1, "timeout")],
        requires_replan=False,
        recoverable=True,
        replans=0,
        calls=5,
        final_place=P,
    ),
    case(
        "retry-travel-connection",
        [fault("travel_time", P, 1, "connection")],
        requires_replan=False,
        recoverable=True,
        replans=0,
        calls=5,
        final_place=P,
    ),
    case(
        "replan-search-permission",
        [fault("candidate_search", None, 1, "permission")],
        requires_replan=True,
        recoverable=True,
        replans=1,
        calls=3,
        final_place=F,
    ),
    case(
        "replan-search-runtime",
        [fault("candidate_search", None, 1, "runtime")],
        requires_replan=True,
        recoverable=True,
        replans=1,
        calls=3,
        final_place=F,
    ),
    case(
        "replan-search-invalid-output",
        [fault("candidate_search", None, 1, "invalid_output")],
        requires_replan=True,
        recoverable=True,
        replans=1,
        calls=3,
        final_place=F,
    ),
    case(
        "replan-search-insufficient",
        [fault("candidate_search", None, 1, "insufficient_evidence")],
        requires_replan=True,
        recoverable=True,
        replans=1,
        calls=3,
        final_place=F,
    ),
    case(
        "replan-availability-permission",
        [fault("availability", P, 1, "permission")],
        requires_replan=True,
        recoverable=True,
        replans=1,
        calls=4,
        final_place=F,
    ),
    case(
        "replan-availability-runtime",
        [fault("availability", P, 1, "runtime")],
        requires_replan=True,
        recoverable=True,
        replans=1,
        calls=4,
        final_place=F,
    ),
    case(
        "replan-availability-invalid",
        [fault("availability", P, 1, "invalid_output")],
        requires_replan=True,
        recoverable=True,
        replans=1,
        calls=4,
        final_place=F,
    ),
    case(
        "replan-booking-permission",
        [fault("booking", P, 1, "permission")],
        requires_replan=True,
        recoverable=True,
        replans=1,
        calls=5,
        final_place=F,
    ),
    case(
        "replan-booking-runtime",
        [fault("booking", P, 1, "runtime")],
        requires_replan=True,
        recoverable=True,
        replans=1,
        calls=5,
        final_place=F,
    ),
    case(
        "replan-booking-invalid",
        [fault("booking", P, 1, "invalid_output")],
        requires_replan=True,
        recoverable=True,
        replans=1,
        calls=5,
        final_place=F,
    ),
    case(
        "replan-travel-permission",
        [fault("travel_time", P, 1, "permission")],
        requires_replan=True,
        recoverable=True,
        replans=1,
        calls=6,
        final_place=F,
    ),
    case(
        "replan-travel-runtime",
        [fault("travel_time", P, 1, "runtime")],
        requires_replan=True,
        recoverable=True,
        replans=1,
        calls=6,
        final_place=F,
    ),
    case(
        "replan-travel-invalid",
        [fault("travel_time", P, 1, "invalid_output")],
        requires_replan=True,
        recoverable=True,
        replans=1,
        calls=6,
        final_place=F,
    ),
    case(
        "replan-search-timeout-exhausted",
        repeated_faults("candidate_search", None, "timeout"),
        requires_replan=True,
        recoverable=True,
        replans=1,
        calls=4,
        final_place=F,
    ),
    case(
        "replan-availability-connection-exhausted",
        repeated_faults("availability", P, "connection"),
        requires_replan=True,
        recoverable=True,
        replans=1,
        calls=5,
        final_place=F,
    ),
    case(
        "replan-booking-timeout-exhausted",
        repeated_faults("booking", P, "timeout"),
        requires_replan=True,
        recoverable=True,
        replans=1,
        calls=6,
        final_place=F,
    ),
    case(
        "replan-travel-timeout-exhausted",
        repeated_faults("travel_time", P, "timeout"),
        requires_replan=True,
        recoverable=True,
        replans=1,
        calls=7,
        final_place=F,
    ),
    case(
        "recover-booking-then-fallback-availability-timeout",
        [fault("booking", P, 1, "permission"), fault("availability", F, 1, "timeout")],
        requires_replan=True,
        recoverable=True,
        replans=1,
        calls=6,
        final_place=F,
    ),
    case(
        "recover-booking-then-fallback-travel-timeout",
        [fault("booking", P, 1, "permission"), fault("travel_time", F, 1, "timeout")],
        requires_replan=True,
        recoverable=True,
        replans=1,
        calls=6,
        final_place=F,
    ),
    case(
        "recover-travel-then-fallback-availability-connection",
        [fault("travel_time", P, 1, "runtime"), fault("availability", F, 1, "connection")],
        requires_replan=True,
        recoverable=True,
        replans=1,
        calls=7,
        final_place=F,
    ),
    case(
        "recover-travel-then-fallback-travel-timeout",
        [fault("travel_time", P, 1, "runtime"), fault("travel_time", F, 1, "timeout")],
        requires_replan=True,
        recoverable=True,
        replans=1,
        calls=7,
        final_place=F,
    ),
    case(
        "stop-primary-and-fallback-availability",
        [fault("availability", P, 1, "permission"), fault("availability", F, 1, "permission")],
        requires_replan=True,
        recoverable=False,
        replans=1,
        calls=3,
        final_place=None,
    ),
    case(
        "stop-booking-and-fallback-invalid-availability",
        [fault("booking", P, 1, "permission"), fault("availability", F, 1, "invalid_output")],
        requires_replan=True,
        recoverable=False,
        replans=1,
        calls=4,
        final_place=None,
    ),
    case(
        "stop-primary-and-fallback-travel",
        [fault("travel_time", P, 1, "runtime"), fault("travel_time", F, 1, "permission")],
        requires_replan=True,
        recoverable=False,
        replans=1,
        calls=6,
        final_place=None,
    ),
    case(
        "stop-primary-and-fallback-invalid-travel",
        [
            fault("travel_time", P, 1, "invalid_output"),
            fault("travel_time", F, 1, "invalid_output"),
        ],
        requires_replan=True,
        recoverable=False,
        replans=1,
        calls=6,
        final_place=None,
    ),
    case(
        "stop-invalid-booking-and-fallback-travel",
        [fault("booking", P, 1, "invalid_output"), fault("travel_time", F, 1, "runtime")],
        requires_replan=True,
        recoverable=False,
        replans=1,
        calls=5,
        final_place=None,
    ),
    case(
        "stop-invalid-primary-travel-and-fallback-availability",
        [fault("travel_time", P, 1, "invalid_output"), fault("availability", F, 1, "permission")],
        requires_replan=True,
        recoverable=False,
        replans=1,
        calls=5,
        final_place=None,
    ),
    case(
        "stop-booking-and-fallback-retry-exhausted",
        [fault("booking", P, 1, "permission"), *repeated_faults("availability", F, "timeout")],
        requires_replan=True,
        recoverable=False,
        replans=1,
        calls=5,
        final_place=None,
    ),
    case(
        "stop-travel-and-fallback-retry-exhausted",
        [fault("travel_time", P, 1, "permission"), *repeated_faults("travel_time", F, "timeout")],
        requires_replan=True,
        recoverable=False,
        replans=1,
        calls=7,
        final_place=None,
    ),
]


def main() -> None:
    parser = argparse.ArgumentParser()
    parser.add_argument(
        "--output",
        type=Path,
        default=Path("evals/datasets/runtime_failure_matrix_v2.jsonl"),
    )
    args = parser.parse_args()
    args.output.parent.mkdir(parents=True, exist_ok=True)
    args.output.write_text(
        "".join(json.dumps(row, separators=(",", ":")) + "\n" for row in CASES),
        encoding="utf-8",
    )
    print(f"wrote {len(CASES)} runtime failure cases to {args.output}")


if __name__ == "__main__":
    main()
