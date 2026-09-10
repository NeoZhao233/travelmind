from __future__ import annotations

import hashlib
import importlib.util
import json
import os
import subprocess
import sys
import tempfile
from pathlib import Path


class DurableWorkerError(RuntimeError):
    """A sanitized durable-checkpoint subprocess failure."""


def _worker(mode: str, database: Path) -> dict:
    environment = dict(os.environ)
    environment["LANGGRAPH_STRICT_MSGPACK"] = "true"
    completed = subprocess.run(
        [
            sys.executable,
            "-m",
            "travelmind.evaluation.durable_worker",
            mode,
            str(database),
        ],
        capture_output=True,
        text=True,
        timeout=15,
        env=environment,
        check=False,
    )
    if completed.returncode != 0:
        raise DurableWorkerError(f"durable worker failed with exit code {completed.returncode}")
    try:
        return json.loads(completed.stdout.strip().splitlines()[-1])
    except (IndexError, json.JSONDecodeError) as exc:
        raise DurableWorkerError("durable worker returned invalid output") from exc


def run_durable_checkpoint_drill() -> dict:
    if importlib.util.find_spec("langgraph.checkpoint.sqlite") is None:
        raise ModuleNotFoundError("langgraph-checkpoint-sqlite is not installed")
    with tempfile.TemporaryDirectory(prefix="travelmind-durable-") as directory:
        root = Path(directory)
        checkpoint_database = root / "checkpoints.sqlite"
        receipt_database = root / "receipts.sqlite"
        checkpoint_prepare = _worker("checkpoint-prepare", checkpoint_database)
        checkpoint_resume = _worker("checkpoint-resume", checkpoint_database)
        receipt_first = _worker("receipt-run", receipt_database)
        receipt_second = _worker("receipt-run", receipt_database)
        checkpoint_mode = checkpoint_database.stat().st_mode & 0o777
        receipt_mode = receipt_database.stat().st_mode & 0o777

    checks = {
        "first_process_persisted_validate_as_next": (
            checkpoint_prepare["status"] == "generated"
            and checkpoint_prepare["planner_calls_in_process"] == 1
            and checkpoint_prepare["next_nodes"] == ["validate"]
        ),
        "second_process_resumed_without_planner": (
            checkpoint_resume["status"] == "completed"
            and checkpoint_resume["planner_calls_in_process"] == 0
            and checkpoint_resume["next_nodes"] == []
        ),
        "first_process_committed_receipt": (
            receipt_first["planner_calls_in_process"] == 1
            and receipt_first["executions"] == 1
            and receipt_first["replays"] == 0
        ),
        "second_process_replayed_receipt": (
            receipt_second["planner_calls_in_process"] == 0
            and receipt_second["executions"] == 0
            and receipt_second["replays"] == 1
        ),
        "checkpoint_file_owner_only": checkpoint_mode == 0o600,
        "receipt_file_owner_only": receipt_mode == 0o600,
    }
    return {
        "experiment": "stage7c2-durable-cross-process-resume-and-receipt-drill",
        "configuration_sha256": hashlib.sha256(
            b"sqlite-checkpoint-v1|sqlite-receipt-v1|strict-msgpack"
        ).hexdigest(),
        "checks": checks,
        "metrics": {
            "check_pass_rate": sum(checks.values()) / len(checks),
            "cross_process_resume_success_rate": float(
                checks["second_process_resumed_without_planner"]
            ),
            "cross_process_receipt_replay_rate": float(checks["second_process_replayed_receipt"]),
            "owner_only_file_mode_rate": (
                int(checks["checkpoint_file_owner_only"]) + int(checks["receipt_file_owner_only"])
            )
            / 2,
        },
        "process_results": {
            "checkpoint_prepare": checkpoint_prepare,
            "checkpoint_resume": checkpoint_resume,
            "receipt_first": receipt_first,
            "receipt_second": receipt_second,
        },
        "limitations": [
            "SQLite is for local/small synchronous workloads, not multi-instance production.",
            "The drill uses sequential processes and does not establish concurrent write capacity.",
            "Expired in-progress receipts fail closed and require operator reconciliation.",
        ],
    }
