from travelmind.evaluation.policy_selection import select_agentic_policies

BASELINE = {
    "routing_metrics": {"test": {"accuracy": 0.5}},
    "grading_metrics": {"test": {"f1": 0.6}},
}


def test_missing_candidate_retains_deterministic_stack() -> None:
    result = select_agentic_policies(baseline=BASELINE, candidate=None)

    assert result["status"] == "baseline_retained"
    assert result["router"] == "RuleBasedQueryRouter"
    assert result["reason_codes"] == ["candidate_not_evaluated"]


def test_candidate_must_beat_quality_and_reliability_gates() -> None:
    candidate = {
        "routing_metrics": {"test": {"accuracy": 0.8}},
        "grading_metrics": {"test": {"f1": 0.8}},
        "telemetry": {
            "by_component": {
                "query_router": {"calls": 10, "failures": 2},
                "evidence_grader": {"calls": 10, "failures": 2},
            }
        },
    }

    result = select_agentic_policies(baseline=BASELINE, candidate=candidate)

    assert result["router"] == "RuleBasedQueryRouter"
    assert result["grader"] == "CoverageEvidenceGrader"
    assert "router_gate_failed" in result["reason_codes"]


def test_passing_candidate_selects_only_evaluated_router_and_grader() -> None:
    candidate = {
        "routing_metrics": {"test": {"accuracy": 0.8}},
        "grading_metrics": {"test": {"f1": 0.8}},
        "telemetry": {
            "by_component": {
                "query_router": {"calls": 100, "failures": 1},
                "evidence_grader": {"calls": 100, "failures": 1},
            }
        },
    }

    result = select_agentic_policies(baseline=BASELINE, candidate=candidate)

    assert result["router"] == "LLMQueryRouter"
    assert result["grader"] == "LLMEvidenceGrader"
    assert result["rewriter"] == "MissingAspectQueryRewriter"
    assert result["reason_codes"] == ["rewriter_requires_trajectory_evaluation"]
