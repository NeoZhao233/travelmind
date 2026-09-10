from pathlib import Path

import pytest

from travelmind.evaluation.live_agentic_runner import run_live_agentic_experiment

ROOT = Path(__file__).resolve().parents[1]


def test_live_agentic_runner_rejects_invalid_limit_before_model_loading() -> None:
    with pytest.raises(ValueError, match="limit must be positive"):
        run_live_agentic_experiment(ROOT, limit=0)
