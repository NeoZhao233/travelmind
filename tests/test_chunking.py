from datetime import UTC, datetime

import pytest

from travelmind.domain.models import SourceDocument
from travelmind.ingestion.chunking import chunk_document, normalize_text


def make_document(content: str) -> SourceDocument:
    return SourceDocument(
        document_id="test-document",
        place_id="test-place",
        title="Test",
        section="Section",
        content=content,
        source_url="https://example.com/source",
        authority="official_operator",
        freshness="static",
        collected_at=datetime.now(UTC),
    )


def test_normalize_text_preserves_paragraphs_and_normalizes_width() -> None:
    assert normalize_text("ＡＢＣ   第一段\n\n第二段\t内容") == "ABC 第一段\n第二段 内容"


def test_chunk_ids_are_stable_for_same_document_and_content() -> None:
    document = make_document(
        "第一段包含足够长度的测试内容，用来验证稳定标识。\n第二段继续提供内容。"
    )
    first = chunk_document(document, max_chars=100)
    second = chunk_document(document, max_chars=100)

    assert [chunk.chunk_id for chunk in first] == [chunk.chunk_id for chunk in second]
    assert all(chunk.document_id == document.document_id for chunk in first)


def test_chunker_splits_oversized_content_and_rejects_tiny_limit() -> None:
    document = make_document("这是一个用于切分测试的句子。" * 20)

    chunks = chunk_document(document, max_chars=100)

    assert len(chunks) > 1
    assert all(chunk.char_count <= 100 for chunk in chunks)
    with pytest.raises(ValueError, match="at least 100"):
        chunk_document(document, max_chars=99)
