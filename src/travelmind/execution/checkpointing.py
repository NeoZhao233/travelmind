import sqlite3
from collections.abc import Iterator
from contextlib import contextmanager
from pathlib import Path

from langgraph.checkpoint.memory import InMemorySaver
from langgraph.checkpoint.serde.jsonplus import JsonPlusSerializer

_TRAVELMIND_MSGPACK_ALLOWLIST = [
    ("travelmind.agentic.models", "EvidenceAssessment"),
    ("travelmind.agentic.models", "QueryIntent"),
    ("travelmind.agentic.models", "RoutingDecision"),
    ("travelmind.agentic.models", "TrajectoryEvent"),
    ("travelmind.schemas", "Activity"),
    ("travelmind.schemas", "ConstraintViolation"),
    ("travelmind.schemas", "DayPlan"),
    ("travelmind.schemas", "Evidence"),
    ("travelmind.schemas", "Itinerary"),
    ("travelmind.schemas", "TravelConstraints"),
    ("travelmind.schemas", "TravelRequest"),
]


def build_in_memory_checkpointer() -> InMemorySaver:
    """Build a strict-type logical-resume saver; it is not process-durable."""

    return InMemorySaver(serde=_serializer())


def _serializer() -> JsonPlusSerializer:
    return JsonPlusSerializer(
        allowed_msgpack_modules=_TRAVELMIND_MSGPACK_ALLOWLIST,
    )


@contextmanager
def open_sqlite_checkpointer(path: Path) -> Iterator[object]:
    """Open a durable local checkpointer with strict types and bounded lock waits."""

    from langgraph.checkpoint.sqlite import SqliteSaver

    resolved = path.resolve()
    resolved.parent.mkdir(parents=True, exist_ok=True)
    connection = sqlite3.connect(resolved, check_same_thread=False, timeout=5)
    try:
        connection.execute("PRAGMA journal_mode=WAL")
        connection.execute("PRAGMA busy_timeout=5000")
        saver = SqliteSaver(connection, serde=_serializer())
        saver.setup()
        resolved.chmod(0o600)
        yield saver
    finally:
        connection.close()
