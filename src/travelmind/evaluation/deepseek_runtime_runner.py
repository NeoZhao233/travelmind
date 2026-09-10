from __future__ import annotations

import hashlib
from collections import Counter
from pathlib import Path
from typing import Any

from travelmind.agentic.llm_provider import StructuredLLMProvider
from travelmind.evaluation.runtime_multistep_runner import (
    load_runtime_multistep_cases,
    run_runtime_multistep_case,
)
from travelmind.runtime.llm_planner import (
    RUNTIME_PLANNER_PROMPT_VERSION,
    LLMRuntimePlanner,
    RuntimePlannerTelemetry,
)
from travelmind.runtime.policies import DeterministicMultiStepRuntimePlanner


def _contract_pass(row: dict[str, Any], variant: str) -> bool:
    outcome = row[variant]
    return bool(
        outcome["status"] == row["expected_status"]
        and outcome["replans"] == row["expected_replans"]
        and outcome["final_place"] == row["expected_final_place"]
        and outcome["tool_calls"] == row["expected_tool_calls"]
    )


def _candidate_contract_pass(row: dict[str, Any]) -> bool:
    outcome = row["deepseek"]
    return bool(
        outcome["status"] == row["expected_status"]
        and outcome["replans"] == row["expected_replans"]
        and outcome["final_place"] == row["expected_final_place"]
        and outcome["tool_calls"] <= row["expected_tool_calls"] + 1
        and outcome["calls_by_tool"]["candidate_search"] == 1
    )


def run_deepseek_runtime_experiment(
    root: Path,
    provider: StructuredLLMProvider,
) -> dict[str, Any]:
    root = root.resolve()
    dataset = root / "evals/datasets/runtime_multistep_seed.jsonl"
    cases = load_runtime_multistep_cases(dataset)
    telemetry = RuntimePlannerTelemetry()
    fallback = DeterministicMultiStepRuntimePlanner(
        origin_place_id="hotel",
        primary_place_id="forbidden-city",
        fallback_place_id="national-museum",
    )
    candidate = LLMRuntimePlanner(
        provider,
        fallback,
        allowed_place_ids={"forbidden-city", "national-museum"},
        origin_place_id="hotel",
        primary_place_id="forbidden-city",
        fallback_place_id="national-museum",
        telemetry=telemetry,
    )
    rows = []
    for case in cases:
        call_start = len(telemetry.calls)
        deterministic = run_runtime_multistep_case(case, max_replans=1)
        deepseek = run_runtime_multistep_case(
            case,
            max_replans=1,
            runtime_planner=candidate,
        )
        rows.append(
            {
                **case.model_dump(mode="json"),
                "deterministic": deterministic,
                "deepseek": deepseek,
                "planner_calls": [
                    item.model_dump(mode="json") for item in telemetry.calls[call_start:]
                ],
            }
        )

    calls = telemetry.calls
    successful = [call for call in calls if call.candidate_success]
    fallback_calls = [call for call in calls if call.fallback_used]
    candidate_contract_rate = sum(_candidate_contract_pass(row) for row in rows) / len(rows)
    deterministic_contract_rate = sum(
        _contract_pass(row, "deterministic") for row in rows
    ) / len(rows)
    revised = [row for row in rows if row["deepseek"]["replans"] > 0]
    unrecoverable = [row for row in rows if not row["recoverable"]]
    metrics = {
        "deterministic_contract_pass_rate": deterministic_contract_rate,
        "deepseek_fallback_inclusive_contract_pass_rate": candidate_contract_rate,
        "contract_pass_lift": candidate_contract_rate - deterministic_contract_rate,
        "deepseek_accepted_plan_rate": len(successful) / len(calls) if calls else 0,
        "deepseek_strict_plan_rate": (
            sum(call.candidate_success and call.normalized_step_count == 0 for call in calls)
            / len(calls)
            if calls
            else 0
        ),
        "argument_normalization_rate": (
            sum(call.normalized_step_count > 0 for call in calls) / len(calls)
            if calls
            else 0
        ),
        "fallback_rate": len(fallback_calls) / len(calls) if calls else 0,
        "post_provider_validation_failure_count": sum(
            not call.candidate_success and call.model is not None for call in calls
        ),
        "candidate_failures_by_reason": dict(
            Counter(call.reason_code or "UNKNOWN" for call in calls if not call.candidate_success)
        ),
        "completed_observation_reuse_rate": (
            sum(row["deepseek"]["retrieval_reused"] for row in revised) / len(revised)
            if revised
            else 0
        ),
        "unrecoverable_safe_stop_rate": sum(
            row["deepseek"]["safe_stop"] for row in unrecoverable
        )
        / len(unrecoverable),
        "total_tokens": sum(call.total_tokens for call in calls),
        "mean_candidate_latency_ms": (
            sum(call.latency_ms or 0 for call in successful) / len(successful)
            if successful
            else None
        ),
    }
    gates = {
        "no_contract_regression": candidate_contract_rate >= deterministic_contract_rate,
        "positive_measured_contract_lift": candidate_contract_rate > deterministic_contract_rate,
        "accepted_plan_rate_at_least_85pct": metrics["deepseek_accepted_plan_rate"] >= 0.85,
        "argument_normalization_rate_at_most_25pct": (
            metrics["argument_normalization_rate"] <= 0.25
        ),
        "fallback_rate_at_most_15pct": metrics["fallback_rate"] <= 0.15,
        "completed_observation_reuse_preserved": (
            metrics["completed_observation_reuse_rate"] == 1
        ),
        "unrecoverable_case_still_fails_closed": metrics["unrecoverable_safe_stop_rate"] == 1,
        "mean_latency_at_most_5000ms": (
            metrics["mean_candidate_latency_ms"] is not None
            and metrics["mean_candidate_latency_ms"] <= 5000
        ),
    }
    selected = all(gates.values())
    return {
        "schema_version": 1,
        "experiment": "stage11-deepseek-runtime-replanner-v1",
        "dataset_sha256": hashlib.sha256(dataset.read_bytes()).hexdigest(),
        "configuration": {
            "cases": len(cases),
            "reviewed_cases": sum(case.reviewed for case in cases),
            "prompt_version": RUNTIME_PLANNER_PROMPT_VERSION,
            "response_format": "json_object",
            "thinking": "disabled",
        },
        "metrics": metrics,
        "selection": {
            "status": "candidate_selected" if selected else "baseline_retained",
            "gates": gates,
        },
        "cases": rows,
        "planner_calls": [item.model_dump(mode="json") for item in calls],
        "limitations": [
            "The four project-authored cases are not independently reviewed.",
            "Fallback-inclusive success is reported separately from raw model-plan success.",
            "Fixture tools isolate planning behavior and do not measure live tool reliability.",
        ],
    }
