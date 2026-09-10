from __future__ import annotations

import hashlib
import tempfile
from datetime import UTC, datetime
from pathlib import Path

from travelmind.ingestion import IndexBuildRejectedError, VersionedIndexPublisher


def _validate(records: list[dict]) -> None:
    identifiers = [record.get("id") for record in records]
    if not identifiers or any(not identity for identity in identifiers):
        raise ValueError("missing record identity")
    if len(identifiers) != len(set(identifiers)):
        raise ValueError("duplicate record identity")


def run_index_publish_drill() -> dict:
    now = datetime(2026, 9, 9, tzinfo=UTC)
    with tempfile.TemporaryDirectory(prefix="travelmind-index-") as directory:
        root = Path(directory)
        publisher = VersionedIndexPublisher(root)
        snapshot_v1 = publisher.capture_snapshot(
            source_id="official-place",
            source_url="https://example.invalid/place",
            fetched_at=now,
            content=b"official source version one",
        )
        duplicate = publisher.capture_snapshot(
            source_id="official-place-copy",
            source_url="https://example.invalid/place",
            fetched_at=now,
            content=b"official source version one",
        )
        first = publisher.publish(
            [{"id": "place-v1", "name": "Place"}],
            snapshots=[snapshot_v1],
            created_at=now,
            validator=_validate,
        )
        try:
            publisher.publish(
                [{"name": "invalid without id"}],
                snapshots=[snapshot_v1],
                created_at=now,
                validator=_validate,
            )
            invalid_rejected = False
        except IndexBuildRejectedError:
            invalid_rejected = True
        current_after_rejection = publisher.current_manifest()
        records_after_rejection = publisher.current_records()

        snapshot_v2 = publisher.capture_snapshot(
            source_id="official-place",
            source_url="https://example.invalid/place",
            fetched_at=now,
            content=b"official source version two",
        )
        second = publisher.publish(
            [{"id": "place-v2", "name": "Place Updated"}],
            snapshots=[snapshot_v2],
            created_at=now,
            validator=_validate,
        )
        publisher.rollback(first.build_id)
        records_after_rollback = publisher.current_records()
        snapshot_files = list((root / "snapshots").glob("*.raw"))
        quarantine_entries = list((root / "quarantine").iterdir())
        owner_only = all(
            path.stat().st_mode & 0o777 == 0o600 for path in [*snapshot_files, root / "CURRENT"]
        )

    checks = {
        "identical_content_deduplicated": (
            snapshot_v1.content_sha256 == duplicate.content_sha256 and len(snapshot_files) == 2
        ),
        "changed_content_created_new_snapshot": (
            snapshot_v1.content_sha256 != snapshot_v2.content_sha256
        ),
        "invalid_build_quarantined": invalid_rejected and len(quarantine_entries) == 1,
        "rejection_preserved_previous_build": (
            current_after_rejection == first
            and records_after_rejection == [{"id": "place-v1", "name": "Place"}]
        ),
        "valid_update_promoted": second.build_id != first.build_id,
        "rollback_restored_previous_records": (
            records_after_rollback == [{"id": "place-v1", "name": "Place"}]
        ),
        "control_and_snapshot_files_owner_only": owner_only,
    }
    return {
        "experiment": "stage8a-versioned-index-atomic-publish-drill",
        "configuration_sha256": hashlib.sha256(
            b"snapshot-sha256|validate-stage-quarantine|atomic-current|rollback"
        ).hexdigest(),
        "checks": checks,
        "metrics": {
            "check_pass_rate": sum(checks.values()) / len(checks),
            "invalid_publish_block_rate": float(invalid_rejected),
            "previous_version_preservation_rate": float(
                checks["rejection_preserved_previous_build"]
            ),
            "rollback_success_rate": float(checks["rollback_restored_previous_records"]),
            "snapshot_deduplication_rate": float(checks["identical_content_deduplicated"]),
        },
        "limitations": [
            "The reference publisher targets a local filesystem, not object storage.",
            "It does not yet fetch HTTP sources or validate parser-specific schemas.",
            "Atomic rename assumes staging and published builds share one filesystem.",
            "Production needs retention, signing, access control, and multi-writer coordination.",
        ],
    }
