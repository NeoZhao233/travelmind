import hashlib
import math
import re
import unicodedata

from travelmind.domain.models import Chunk, SourceDocument

_SENTENCE_BOUNDARY = re.compile(r"(?<=[。！？!?])")
_WHITESPACE = re.compile(r"[\t\r\f\v ]+")


def normalize_text(text: str) -> str:
    """Normalize Unicode and horizontal whitespace while preserving paragraph boundaries."""

    normalized = unicodedata.normalize("NFKC", text)
    lines = [_WHITESPACE.sub(" ", line).strip() for line in normalized.splitlines()]
    return "\n".join(line for line in lines if line)


def _split_oversized_unit(text: str, max_chars: int) -> list[str]:
    if len(text) <= max_chars:
        return [text]

    sentences = [part.strip() for part in _SENTENCE_BOUNDARY.split(text) if part.strip()]
    if len(sentences) == 1:
        return [text[start : start + max_chars] for start in range(0, len(text), max_chars)]

    units: list[str] = []
    current = ""
    for sentence in sentences:
        candidate = f"{current}{sentence}"
        if current and len(candidate) > max_chars:
            units.append(current)
            current = sentence
        else:
            current = candidate
    if current:
        units.append(current)
    return units


def chunk_document(document: SourceDocument, *, max_chars: int = 500) -> list[Chunk]:
    """Create stable, paragraph-aware chunks without model-dependent tokenization."""

    if max_chars < 100:
        raise ValueError("max_chars must be at least 100")

    content = normalize_text(document.content)
    paragraphs = [paragraph.strip() for paragraph in content.split("\n") if paragraph.strip()]
    units = [
        unit for paragraph in paragraphs for unit in _split_oversized_unit(paragraph, max_chars)
    ]

    packed: list[str] = []
    current = ""
    for unit in units:
        candidate = unit if not current else f"{current}\n{unit}"
        if current and len(candidate) > max_chars:
            packed.append(current)
            current = unit
        else:
            current = candidate
    if current:
        packed.append(current)

    chunks: list[Chunk] = []
    for ordinal, chunk_text in enumerate(packed):
        digest = hashlib.sha256(f"{document.document_id}\x00{chunk_text}".encode()).hexdigest()[:16]
        chunks.append(
            Chunk(
                chunk_id=f"{document.document_id}-{digest}",
                document_id=document.document_id,
                place_id=document.place_id,
                ordinal=ordinal,
                content=chunk_text,
                char_count=len(chunk_text),
                token_estimate=max(1, math.ceil(len(chunk_text) / 2)),
                metadata={
                    "title": document.title,
                    "section": document.section,
                    "authority": document.authority.value,
                    "freshness": document.freshness.value,
                    "source_url": str(document.source_url),
                    "collected_at": document.collected_at.isoformat(),
                },
            )
        )
    return chunks


def chunk_documents(documents: list[SourceDocument], *, max_chars: int = 500) -> list[Chunk]:
    return [
        chunk for document in documents for chunk in chunk_document(document, max_chars=max_chars)
    ]
