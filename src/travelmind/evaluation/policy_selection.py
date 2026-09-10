from __future__ import annotations

from typing import Any


def select_agentic_policies(
    *,
    baseline: dict[str, Any],
    candidate: dict[str, Any] | None,
    max_fallback_rate: float = 0.05,
) -> dict[str, Any]:
    """Apply conservative Stage 3E gates; absence of evidence keeps the baseline."""

    if candidate is None:
        return {
            "status": "baseline_retained",
            "router": "RuleBasedQueryRouter",
            "grader": "CoverageEvidenceGrader",
            "rewriter": "MissingAspectQueryRewriter",
            "reason_codes": ["candidate_not_evaluated"],
        }

    baseline_router = baseline["routing_metrics"]["test"]["accuracy"]
    baseline_grader = baseline["grading_metrics"]["test"]["f1"]
    candidate_router = candidate["routing_metrics"]["test"]["accuracy"]
    candidate_grader = candidate["grading_metrics"]["test"]["f1"]
    component_telemetry = candidate["telemetry"]["by_component"]
    router_calls = component_telemetry["query_router"]["calls"]
    grader_calls = component_telemetry["evidence_grader"]["calls"]
    router_fallback_rate = component_telemetry["query_router"]["failures"] / router_calls
    grader_fallback_rate = component_telemetry["evidence_grader"]["failures"] / grader_calls
    router_selected = (
        candidate_router >= baseline_router + 0.10 and router_fallback_rate <= max_fallback_rate
    )
    grader_selected = (
        candidate_grader >= baseline_grader + 0.05 and grader_fallback_rate <= max_fallback_rate
    )
    return {
        "status": "candidate_evaluated",
        "router": "LLMQueryRouter" if router_selected else "RuleBasedQueryRouter",
        "grader": "LLMEvidenceGrader" if grader_selected else "CoverageEvidenceGrader",
        "rewriter": "MissingAspectQueryRewriter",
        "gates": {
            "max_fallback_rate": max_fallback_rate,
            "router_minimum_absolute_lift": 0.10,
            "grader_minimum_absolute_f1_lift": 0.05,
        },
        "observed": {
            "router_absolute_lift": candidate_router - baseline_router,
            "grader_absolute_f1_lift": candidate_grader - baseline_grader,
            "router_fallback_rate": router_fallback_rate,
            "grader_fallback_rate": grader_fallback_rate,
        },
        "reason_codes": [
            "rewriter_requires_trajectory_evaluation",
            *([] if router_selected else ["router_gate_failed"]),
            *([] if grader_selected else ["grader_gate_failed"]),
        ],
    }
