from collections import defaultdict
from collections.abc import Hashable, Sequence
from typing import TypeVar

T = TypeVar("T", bound=Hashable)


def reciprocal_rank_fusion(
    rankings: Sequence[Sequence[T]], *, k: int = 60
) -> list[tuple[T, float]]:
    """Fuse ranked lists without assuming comparable raw relevance scores."""

    if k < 1:
        raise ValueError("k must be positive")

    scores: dict[T, float] = defaultdict(float)
    for ranking in rankings:
        seen: set[T] = set()
        for rank, item in enumerate(ranking, start=1):
            if item in seen:
                continue
            seen.add(item)
            scores[item] += 1 / (k + rank)

    return sorted(scores.items(), key=lambda pair: (-pair[1], str(pair[0])))
