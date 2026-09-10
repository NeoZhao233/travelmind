import importlib.util
import sqlite3

import pytest

from travelmind.evaluation.durable_checkpoint_runner import run_durable_checkpoint_drill
from travelmind.execution import AbandonedReceiptError, SqliteItineraryReceiptStore
from travelmind.planner.demo import DemoPlanner
from travelmind.schemas import Evidence, TravelRequest

pytestmark = pytest.mark.skipif(
    importlib.util.find_spec("langgraph.checkpoint.sqlite") is None,
    reason="checkpoint extra is not installed",
)


def test_sqlite_checkpoint_and_receipts_survive_new_processes() -> None:
    report = run_durable_checkpoint_drill()

    assert report["metrics"] == {
        "check_pass_rate": 1,
        "cross_process_resume_success_rate": 1,
        "cross_process_receipt_replay_rate": 1,
        "owner_only_file_mode_rate": 1,
    }
    assert all(report["checks"].values())


def test_durable_drill_reports_missing_optional_dependency(monkeypatch) -> None:
    monkeypatch.setattr(
        "travelmind.evaluation.durable_checkpoint_runner.importlib.util.find_spec",
        lambda name: None,
    )

    with pytest.raises(ModuleNotFoundError, match="langgraph-checkpoint-sqlite"):
        run_durable_checkpoint_drill()


def _itinerary():
    evidence = Evidence(
        id="durable-evidence",
        content="官方门票、开放时间与预约规则。",
        source_url="https://example.invalid/durable",
        source_type="official",
        score=1,
        metadata={"place_id": "place-1", "name": "Place One", "cost": 20},
    )
    return DemoPlanner().generate(TravelRequest(query="故宫门票"), [evidence])


def test_sqlite_receipt_releases_owned_claim_after_operation_failure(tmp_path) -> None:
    database = tmp_path / "receipts.sqlite"
    calls = 0

    def fail_once():
        nonlocal calls
        calls += 1
        raise RuntimeError("provider failed before returning a result")

    with SqliteItineraryReceiptStore(database) as store:
        with pytest.raises(RuntimeError, match="provider failed"):
            store.execute("retryable", fail_once)
        result, replayed = store.execute("retryable", _itinerary)

    assert result.days
    assert replayed is False
    assert calls == 1


def test_sqlite_receipt_fails_closed_for_expired_in_progress_claim(tmp_path) -> None:
    database = tmp_path / "receipts.sqlite"
    with SqliteItineraryReceiptStore(database):
        pass
    with sqlite3.connect(database) as connection:
        connection.execute(
            "INSERT INTO itinerary_receipts "
            "(receipt_key, status, owner_id, acquired_at, result_json) "
            "VALUES (?, 'in_progress', ?, ?, NULL)",
            ("abandoned", "dead-worker", 0),
        )

    operation_called = False

    def unsafe_retry():
        nonlocal operation_called
        operation_called = True
        return _itinerary()

    with SqliteItineraryReceiptStore(
        database,
        lease_seconds=10,
        clock=lambda: 20,
    ) as store:
        with pytest.raises(AbandonedReceiptError, match="reconciliation"):
            store.execute("abandoned", unsafe_retry)

    assert operation_called is False
