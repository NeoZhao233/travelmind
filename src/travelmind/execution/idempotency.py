from __future__ import annotations

import copy
import hashlib
import json
import sqlite3
import threading
import time
from collections.abc import Callable
from pathlib import Path
from typing import Generic, Protocol, TypeVar
from uuid import uuid4

from travelmind.planner.base import Planner
from travelmind.schemas import Evidence, Itinerary, TravelRequest

T = TypeVar("T")


class IdempotencyInProgressError(RuntimeError):
    """The same operation is already running and was not duplicated."""


class AbandonedReceiptError(RuntimeError):
    """An expired in-progress receipt needs reconciliation before retry."""


class ItineraryReceiptStore(Protocol):
    def execute(self, key: str, operation: Callable[[], Itinerary]) -> tuple[Itinerary, bool]: ...


def build_idempotency_key(
    *,
    scope: str,
    operation: str,
    payload: object,
) -> str:
    if not scope.strip() or not operation.strip():
        raise ValueError("idempotency scope and operation must be non-empty")
    canonical = json.dumps(
        payload,
        ensure_ascii=False,
        sort_keys=True,
        separators=(",", ":"),
    )
    return hashlib.sha256(f"{scope}|{operation}|{canonical}".encode()).hexdigest()


class InMemoryReceiptStore(Generic[T]):
    """Atomic single-process receipts; durable production storage needs a unique constraint."""

    def __init__(self) -> None:
        self._completed: dict[str, T] = {}
        self._in_progress: set[str] = set()
        self._lock = threading.Lock()

    def execute(self, key: str, operation: Callable[[], T]) -> tuple[T, bool]:
        with self._lock:
            if key in self._completed:
                return copy.deepcopy(self._completed[key]), True
            if key in self._in_progress:
                raise IdempotencyInProgressError("idempotent operation is already running")
            self._in_progress.add(key)
        try:
            result = operation()
        except Exception:
            with self._lock:
                self._in_progress.discard(key)
            raise
        with self._lock:
            self._completed[key] = copy.deepcopy(result)
            self._in_progress.discard(key)
        return result, False


class SqliteItineraryReceiptStore:
    """Durable local receipts with atomic claims and fail-closed abandoned leases."""

    def __init__(
        self,
        path: Path,
        *,
        lease_seconds: float = 300,
        clock: Callable[[], float] = time.time,
    ) -> None:
        if lease_seconds <= 0:
            raise ValueError("receipt lease must be positive")
        self.path = path.resolve()
        self.path.parent.mkdir(parents=True, exist_ok=True)
        self._connection = sqlite3.connect(
            self.path,
            check_same_thread=False,
            timeout=5,
        )
        self._connection.execute("PRAGMA journal_mode=WAL")
        self._connection.execute("PRAGMA busy_timeout=5000")
        self._connection.execute(
            """
            CREATE TABLE IF NOT EXISTS itinerary_receipts (
                receipt_key TEXT PRIMARY KEY,
                status TEXT NOT NULL CHECK(status IN ('in_progress', 'completed')),
                owner_id TEXT NOT NULL,
                acquired_at REAL NOT NULL,
                result_json TEXT
            )
            """
        )
        self._connection.commit()
        self.path.chmod(0o600)
        self._lease_seconds = lease_seconds
        self._clock = clock
        self._lock = threading.Lock()

    def close(self) -> None:
        self._connection.close()

    def __enter__(self) -> SqliteItineraryReceiptStore:
        return self

    def __exit__(self, exc_type, exc_value, traceback) -> None:
        del exc_type, exc_value, traceback
        self.close()

    def execute(
        self,
        key: str,
        operation: Callable[[], Itinerary],
    ) -> tuple[Itinerary, bool]:
        owner_id = uuid4().hex
        acquired_at = self._clock()
        with self._lock:
            self._connection.execute("BEGIN IMMEDIATE")
            row = self._connection.execute(
                "SELECT status, acquired_at, result_json FROM itinerary_receipts "
                "WHERE receipt_key = ?",
                (key,),
            ).fetchone()
            if row is not None:
                self._connection.commit()
                status, previous_acquired_at, result_json = row
                if status == "completed":
                    assert result_json is not None
                    return Itinerary.model_validate_json(result_json), True
                if acquired_at - float(previous_acquired_at) > self._lease_seconds:
                    raise AbandonedReceiptError("expired receipt requires operator reconciliation")
                raise IdempotencyInProgressError("idempotent operation is already running")
            self._connection.execute(
                "INSERT INTO itinerary_receipts "
                "(receipt_key, status, owner_id, acquired_at, result_json) "
                "VALUES (?, 'in_progress', ?, ?, NULL)",
                (key, owner_id, acquired_at),
            )
            self._connection.commit()
        try:
            result = operation()
        except Exception:
            with self._lock:
                self._connection.execute(
                    "DELETE FROM itinerary_receipts WHERE receipt_key = ? "
                    "AND owner_id = ? AND status = 'in_progress'",
                    (key, owner_id),
                )
                self._connection.commit()
            raise
        with self._lock:
            cursor = self._connection.execute(
                "UPDATE itinerary_receipts SET status = 'completed', result_json = ? "
                "WHERE receipt_key = ? AND owner_id = ? AND status = 'in_progress'",
                (result.model_dump_json(), key, owner_id),
            )
            self._connection.commit()
            if cursor.rowcount != 1:
                raise AbandonedReceiptError("receipt ownership changed before commit")
        return result, False


class IdempotentPlanner:
    def __init__(
        self,
        planner: Planner,
        *,
        receipt_store: ItineraryReceiptStore,
        execution_scope: str,
        planner_version: str,
    ) -> None:
        if not planner_version.strip():
            raise ValueError("planner_version must be non-empty")
        self._planner = planner
        self._receipts = receipt_store
        self._scope = execution_scope
        self._version = planner_version
        self.execution_count = 0
        self.replay_count = 0
        self._counter_lock = threading.Lock()

    def generate(self, request: TravelRequest, evidence: list[Evidence]) -> Itinerary:
        payload = {
            "planner_version": self._version,
            "request": request.model_dump(mode="json"),
            "evidence": [
                {
                    "id": item.id,
                    "content_sha256": hashlib.sha256(item.content.encode()).hexdigest(),
                }
                for item in evidence
            ],
        }
        key = build_idempotency_key(
            scope=self._scope,
            operation="planner.generate",
            payload=payload,
        )

        def execute() -> Itinerary:
            with self._counter_lock:
                self.execution_count += 1
            return self._planner.generate(request, evidence)

        result, replayed = self._receipts.execute(key, execute)
        if replayed:
            with self._counter_lock:
                self.replay_count += 1
        return result
