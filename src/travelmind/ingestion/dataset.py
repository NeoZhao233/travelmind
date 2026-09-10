import json
from collections import Counter, defaultdict
from pathlib import Path
from typing import TypeVar

from pydantic import BaseModel

from travelmind.domain.models import (
    DatasetSummary,
    FactRecord,
    PlaceRecord,
    RetrievalExample,
    SourceDocument,
)
from travelmind.ingestion.chunking import chunk_documents

ModelT = TypeVar("ModelT", bound=BaseModel)


def load_jsonl(path: Path, model: type[ModelT]) -> list[ModelT]:
    if not path.is_file():
        raise FileNotFoundError(f"Dataset file does not exist: {path}")

    records: list[ModelT] = []
    for line_number, raw_line in enumerate(path.read_text(encoding="utf-8").splitlines(), start=1):
        line = raw_line.strip()
        if not line:
            continue
        try:
            records.append(model.model_validate_json(line))
        except (ValueError, json.JSONDecodeError) as exc:
            raise ValueError(f"Invalid {model.__name__} at {path}:{line_number}: {exc}") from exc
    return records


def _index_unique(records: list[ModelT], attribute: str) -> dict[str, ModelT]:
    indexed: dict[str, ModelT] = {}
    for record in records:
        identifier = str(getattr(record, attribute))
        if identifier in indexed:
            raise ValueError(f"Duplicate {attribute}: {identifier}")
        indexed[identifier] = record
    return indexed


def _validate_intent_clusters(examples: list[RetrievalExample]) -> None:
    clustered = [example for example in examples if example.intent_id is not None]
    if not clustered:
        return
    if len(clustered) != len(examples):
        raise ValueError("clustered retrieval datasets require intent_id on every example")
    normalized_queries = ["".join(example.query.lower().split()) for example in examples]
    if len(normalized_queries) != len(set(normalized_queries)):
        raise ValueError("clustered retrieval dataset contains duplicate normalized queries")

    by_intent: dict[str, list[RetrievalExample]] = defaultdict(list)
    for example in examples:
        by_intent[example.intent_id or example.query_id].append(example)
    for intent_id, rows in by_intent.items():
        if len(rows) != 3:
            raise ValueError(f"intent {intent_id} must contain exactly three paraphrases")
        if len({row.paraphrase_id for row in rows}) != 3 or any(
            row.paraphrase_id is None for row in rows
        ):
            raise ValueError(f"intent {intent_id} requires three unique paraphrase IDs")
        if len({row.evaluation_split for row in rows}) != 1:
            raise ValueError(f"intent {intent_id} leaks across evaluation splits")
        if len({row.query_type for row in rows}) != 1:
            raise ValueError(f"intent {intent_id} mixes query types")
        judgments = {
            (
                tuple(sorted(row.relevant_documents.items())),
                row.should_abstain,
                tuple(row.expected_place_ids),
            )
            for row in rows
        }
        if len(judgments) != 1:
            raise ValueError(f"intent {intent_id} has inconsistent relevance judgments")


def validate_retrieval_dataset(root: Path, retrieval_path: Path) -> DatasetSummary:
    root = root.resolve()
    retrieval_path = retrieval_path.resolve()
    if not retrieval_path.is_relative_to(root):
        raise ValueError("retrieval dataset path must stay inside the project root")
    places = load_jsonl(root / "data/seed/places.jsonl", PlaceRecord)
    documents = load_jsonl(root / "data/seed/documents.jsonl", SourceDocument)
    facts = load_jsonl(root / "data/seed/facts.jsonl", FactRecord)
    examples = load_jsonl(retrieval_path, RetrievalExample)
    _validate_intent_clusters(examples)

    place_by_id = _index_unique(places, "place_id")
    document_by_id = _index_unique(documents, "document_id")
    _index_unique(facts, "fact_id")
    _index_unique(examples, "query_id")

    for document in documents:
        if document.place_id not in place_by_id:
            raise ValueError(
                f"Document {document.document_id} references unknown place {document.place_id}"
            )

    for fact in facts:
        if fact.place_id not in place_by_id:
            raise ValueError(f"Fact {fact.fact_id} references unknown place {fact.place_id}")
        source = document_by_id.get(fact.document_id)
        if source is None:
            raise ValueError(f"Fact {fact.fact_id} references unknown document {fact.document_id}")
        if source.place_id != fact.place_id:
            raise ValueError(f"Fact {fact.fact_id} place does not match source document place")

    fact_types_by_place: dict[str, set[str]] = defaultdict(set)
    for fact in facts:
        fact_types_by_place[fact.place_id].add(fact.fact_type.value)

    for example in examples:
        unknown_documents = set(example.relevant_documents) - document_by_id.keys()
        if unknown_documents:
            raise ValueError(
                f"Query {example.query_id} references unknown documents: "
                f"{sorted(unknown_documents)}"
            )
        unknown_places = set(example.expected_place_ids) - place_by_id.keys()
        if unknown_places:
            raise ValueError(
                f"Query {example.query_id} references unknown places: {sorted(unknown_places)}"
            )
        available_fact_types = {
            fact_type
            for place_id in example.expected_place_ids
            for fact_type in fact_types_by_place[place_id]
        }
        missing_fact_types = {
            fact_type.value
            for fact_type in example.expected_fact_types
            if fact_type.value not in available_fact_types
        }
        if missing_fact_types:
            raise ValueError(
                f"Query {example.query_id} expects unavailable fact types: "
                f"{sorted(missing_fact_types)}"
            )

    chunks = chunk_documents(documents)
    chunk_ids = [chunk.chunk_id for chunk in chunks]
    if len(chunk_ids) != len(set(chunk_ids)):
        raise ValueError("Chunk IDs must be unique")

    query_type_counts = Counter(example.query_type.value for example in examples)
    split_counts = Counter(example.evaluation_split for example in examples)
    intent_ids = {example.intent_id or example.query_id for example in examples}
    return DatasetSummary(
        places=len(places),
        documents=len(documents),
        facts=len(facts),
        chunks=len(chunks),
        retrieval_examples=len(examples),
        reviewed_examples=sum(example.reviewed for example in examples),
        query_types=dict(query_type_counts),
        intent_clusters=len(intent_ids),
        abstention_examples=sum(example.should_abstain for example in examples),
        evaluation_splits=dict(split_counts),
    )


def validate_seed_dataset(root: Path) -> DatasetSummary:
    return validate_retrieval_dataset(
        root,
        root.resolve() / "evals/datasets/retrieval_seed.jsonl",
    )
