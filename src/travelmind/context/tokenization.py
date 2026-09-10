from __future__ import annotations

import math
import re
from typing import Protocol


class TokenEstimator(Protocol):
    name: str

    def estimate(self, text: str) -> int: ...


class HeuristicTokenEstimator:
    """Conservative mixed Chinese/ASCII estimate; not a model tokenizer."""

    name = "heuristic-cjk1-ascii4-v1"
    _ascii_word = re.compile(r"[A-Za-z0-9_]+")

    def estimate(self, text: str) -> int:
        ascii_tokens = sum(
            max(1, math.ceil(len(match.group()) / 4)) for match in self._ascii_word.finditer(text)
        )
        without_ascii = self._ascii_word.sub("", text)
        non_whitespace = sum(not char.isspace() for char in without_ascii)
        return max(1, ascii_tokens + non_whitespace)


class FallbackTokenEstimator:
    """Use a model-aware estimator when available and degrade to the heuristic."""

    def __init__(self, primary: TokenEstimator, fallback: TokenEstimator | None = None) -> None:
        self.primary = primary
        self.fallback = fallback or HeuristicTokenEstimator()
        self.degraded = False
        self.name = f"{primary.name}-fallback-{self.fallback.name}"

    def estimate(self, text: str) -> int:
        try:
            return self.primary.estimate(text)
        except Exception:
            self.degraded = True
            return self.fallback.estimate(text)
