from travelmind.domain.models import Chunk, PlaceRecord, SourceDocument


def build_searchable_text(
    place: PlaceRecord,
    document: SourceDocument,
    chunk: Chunk,
) -> str:
    """Build the shared text representation used by sparse and dense baselines."""

    return " ".join(
        [
            place.name,
            place.city,
            place.district or "",
            " ".join(place.categories),
            document.title,
            document.section,
            " ".join(document.tags),
            chunk.content,
        ]
    )
