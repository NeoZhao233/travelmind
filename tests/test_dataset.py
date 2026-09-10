from pathlib import Path

import pytest

from travelmind.domain.models import PlaceRecord
from travelmind.ingestion.dataset import load_jsonl, validate_seed_dataset

PROJECT_ROOT = Path(__file__).resolve().parents[1]


def test_stage1_seed_dataset_is_valid_and_reviewed() -> None:
    summary = validate_seed_dataset(PROJECT_ROOT)

    assert summary.places == 5
    assert summary.documents == 14
    assert summary.facts == 22
    assert summary.chunks == 14
    assert summary.retrieval_examples == 15
    assert summary.reviewed_examples == summary.retrieval_examples
    assert summary.query_types == {
        "semantic": 3,
        "exact": 3,
        "metadata": 3,
        "temporal": 3,
        "multi_constraint": 3,
    }


def test_jsonl_error_includes_file_and_line(tmp_path: Path) -> None:
    path = tmp_path / "places.jsonl"
    path.write_text(
        '{"place_id":"valid-place","name":"Valid","city":"Beijing",'
        '"categories":["museum"],"official_url":"https://example.com"}\n'
        '{"place_id":"INVALID ID"}\n',
        encoding="utf-8",
    )

    with pytest.raises(ValueError, match=r"places\.jsonl:2"):
        load_jsonl(path, PlaceRecord)
