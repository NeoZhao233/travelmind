import pytest

from travelmind.retrieval.fusion import reciprocal_rank_fusion


def test_rrf_rewards_items_present_in_multiple_rankings() -> None:
    fused = reciprocal_rank_fusion([["a", "b", "c"], ["b", "d", "a"]])
    assert fused[0][0] == "b"
    assert {item for item, _ in fused} == {"a", "b", "c", "d"}


def test_rrf_rejects_non_positive_k() -> None:
    with pytest.raises(ValueError, match="positive"):
        reciprocal_rank_fusion([["a"]], k=0)
