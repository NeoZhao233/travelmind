from pathlib import Path
from typing import Any

from travelmind.evaluation.deepseek_runner import run_deepseek_policy_experiment

ROOT = Path(__file__).resolve().parents[1]


class FailingProvider:
    def complete_json(self, **kwargs: Any) -> Any:
        del kwargs
        raise TimeoutError("secret provider message")


def test_deepseek_evaluator_reports_fallback_instead_of_faking_llm_success() -> None:
    report = run_deepseek_policy_experiment(ROOT, FailingProvider())

    assert report["telemetry"]["calls"] == 26
    assert report["telemetry"]["successful_calls"] == 0
    assert report["telemetry"]["fallback_rate"] == 1
    assert all(item["fallback"] for item in report["routing_cases"])
    assert "secret" not in str(report)
