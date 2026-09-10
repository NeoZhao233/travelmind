import math

import pytest

from travelmind.retrieval.embeddings import DenseEmbeddingError, validate_vector


def test_vector_validation_accepts_finite_nonzero_vector() -> None:
    validate_vector([0.5, -0.2], dimension=2, label="test")


@pytest.mark.parametrize(
    ("vector", "message"),
    [
        ([1.0], "dimension"),
        ([0.0, 0.0], "all-zero"),
        ([math.nan, 1.0], "non-finite"),
    ],
)
def test_vector_validation_rejects_invalid_output(
    vector: list[float],
    message: str,
) -> None:
    with pytest.raises(DenseEmbeddingError, match=message):
        validate_vector(vector, dimension=2, label="test")
