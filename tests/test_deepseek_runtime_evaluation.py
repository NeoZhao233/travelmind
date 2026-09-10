import json
from pathlib import Path
from typing import Any

from travelmind.agentic.llm_provider import LLMUsage, StructuredLLMResult
from travelmind.evaluation.deepseek_runtime_runner import run_deepseek_runtime_experiment

ROOT = Path(__file__).resolve().parents[1]


def _initial_steps(query: str) -> list[dict[str, Any]]:
    return [
        {
            "step_id": "search_candidates",
            "kind": "retrieve",
            "tool_name": "candidate_search",
            "arguments": {"query": query},
            "depends_on": [],
        },
        {
            "step_id": "primary_availability",
            "kind": "check_availability",
            "tool_name": "availability",
            "arguments": {"place_id": "forbidden-city"},
            "depends_on": ["search_candidates"],
        },
        {
            "step_id": "primary_booking",
            "kind": "check_booking",
            "tool_name": "booking",
            "arguments": {"place_id": "forbidden-city"},
            "depends_on": ["primary_availability"],
        },
        {
            "step_id": "primary_travel_time",
            "kind": "estimate_travel_time",
            "tool_name": "travel_time",
            "arguments": {
                "origin_place_id": "hotel",
                "destination_place_id": "forbidden-city",
            },
            "depends_on": ["primary_booking"],
        },
    ]


def _fallback_steps() -> list[dict[str, Any]]:
    return [
        {
            "step_id": "fallback_availability",
            "kind": "check_availability",
            "tool_name": "availability",
            "arguments": {"place_id": "national-museum"},
            "depends_on": [],
        },
        {
            "step_id": "fallback_travel_time",
            "kind": "estimate_travel_time",
            "tool_name": "travel_time",
            "arguments": {
                "origin_place_id": "hotel",
                "destination_place_id": "national-museum",
            },
            "depends_on": ["fallback_availability"],
        },
    ]


class ContractProvider:
    def complete_json(self, **kwargs: Any) -> StructuredLLMResult:
        payload = json.loads(kwargs["user_prompt"])
        steps = _fallback_steps() if payload["previous_plan"] else _initial_steps(payload["query"])
        return StructuredLLMResult(
            data={"reason": "Follow the bounded evidence plan.", "steps": steps},
            model="fake-deepseek",
            usage=LLMUsage(prompt_tokens=100, completion_tokens=80, total_tokens=180),
            latency_ms=25,
            provider_attempts=1,
        )


class InvalidButFallbackProvider:
    def complete_json(self, **kwargs: Any) -> StructuredLLMResult:
        del kwargs
        return StructuredLLMResult(
            data={
                "reason": "Invent an unavailable place.",
                "steps": [
                    {
                        "step_id": "invented",
                        "kind": "check_availability",
                        "tool_name": "availability",
                        "arguments": {"place_id": "invented-place"},
                    }
                ],
            },
            model="fake-deepseek",
            latency_ms=25,
            provider_attempts=1,
        )


def test_equal_quality_paid_candidate_is_not_selected_without_measured_lift() -> None:
    report = run_deepseek_runtime_experiment(ROOT, ContractProvider())

    assert report["metrics"]["deterministic_contract_pass_rate"] == 1
    assert report["metrics"]["deepseek_fallback_inclusive_contract_pass_rate"] == 1
    assert report["metrics"]["deepseek_accepted_plan_rate"] == 1
    assert report["metrics"]["deepseek_strict_plan_rate"] == 1
    assert report["metrics"]["fallback_rate"] == 0
    assert report["metrics"]["completed_observation_reuse_rate"] == 1
    assert report["metrics"]["contract_pass_lift"] == 0
    assert report["selection"]["status"] == "baseline_retained"
    assert report["selection"]["gates"]["positive_measured_contract_lift"] is False


def test_fallback_success_does_not_hide_invalid_model_plans() -> None:
    report = run_deepseek_runtime_experiment(ROOT, InvalidButFallbackProvider())

    assert report["metrics"]["deepseek_fallback_inclusive_contract_pass_rate"] == 1
    assert report["metrics"]["deepseek_accepted_plan_rate"] == 0
    assert report["metrics"]["fallback_rate"] == 1
    assert report["metrics"]["post_provider_validation_failure_count"] > 0
    assert report["selection"]["status"] == "baseline_retained"
