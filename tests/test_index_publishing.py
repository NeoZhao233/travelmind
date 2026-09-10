from datetime import UTC, datetime

import pytest

from travelmind.ingestion import IndexBuildRejectedError, VersionedIndexPublisher

NOW = datetime(2026, 9, 9, tzinfo=UTC)


def _accept(records) -> None:
    if not records or any("id" not in record for record in records):
        raise ValueError("invalid records")


def test_raw_snapshots_are_content_addressed_and_immutable(tmp_path) -> None:
    publisher = VersionedIndexPublisher(tmp_path)

    first = publisher.capture_snapshot(
        source_id="official-place",
        source_url="https://example.invalid/place",
        fetched_at=NOW,
        content=b"version-one",
    )
    duplicate = publisher.capture_snapshot(
        source_id="official-place",
        source_url="https://example.invalid/place",
        fetched_at=NOW,
        content=b"version-one",
    )
    changed = publisher.capture_snapshot(
        source_id="official-place",
        source_url="https://example.invalid/place",
        fetched_at=NOW,
        content=b"version-two",
    )

    assert first.content_sha256 == duplicate.content_sha256
    assert first.content_sha256 != changed.content_sha256
    assert len(list((tmp_path / "snapshots").glob("*.raw"))) == 2
    assert all(path.stat().st_mode & 0o777 == 0o600 for path in tmp_path.glob("snapshots/*"))


def test_invalid_build_is_quarantined_without_replacing_current(tmp_path) -> None:
    publisher = VersionedIndexPublisher(tmp_path)
    snapshot = publisher.capture_snapshot(
        source_id="official-place",
        source_url="https://example.invalid/place",
        fetched_at=NOW,
        content=b"source",
    )
    accepted = publisher.publish(
        [{"id": "v1"}], snapshots=[snapshot], created_at=NOW, validator=_accept
    )

    with pytest.raises(IndexBuildRejectedError, match="ValueError"):
        publisher.publish(
            [{"missing": "id"}],
            snapshots=[snapshot],
            created_at=NOW,
            validator=_accept,
        )

    assert publisher.current_manifest() == accepted
    assert publisher.current_records() == [{"id": "v1"}]
    assert len(list((tmp_path / "quarantine").iterdir())) == 1


def test_publish_and_rollback_only_point_to_complete_builds(tmp_path) -> None:
    publisher = VersionedIndexPublisher(tmp_path)
    snapshot = publisher.capture_snapshot(
        source_id="official-place",
        source_url="https://example.invalid/place",
        fetched_at=NOW,
        content=b"source",
    )
    first = publisher.publish(
        [{"id": "v1"}], snapshots=[snapshot], created_at=NOW, validator=_accept
    )
    second = publisher.publish(
        [{"id": "v2"}], snapshots=[snapshot], created_at=NOW, validator=_accept
    )

    assert publisher.current_manifest() == second
    assert publisher.current_records() == [{"id": "v2"}]
    restored = publisher.rollback(first.build_id)

    assert restored == first
    assert publisher.current_records() == [{"id": "v1"}]
    assert (tmp_path / "CURRENT").stat().st_mode & 0o777 == 0o600


def test_missing_snapshot_reference_and_path_traversal_fail_closed(tmp_path) -> None:
    publisher = VersionedIndexPublisher(tmp_path)
    snapshot = publisher.capture_snapshot(
        source_id="official-place",
        source_url="https://example.invalid/place",
        fetched_at=NOW,
        content=b"source",
    )
    (tmp_path / "snapshots" / f"{snapshot.content_sha256}.raw").unlink()

    with pytest.raises(ValueError, match="missing source snapshot"):
        publisher.publish([{"id": "v1"}], snapshots=[snapshot], created_at=NOW, validator=_accept)
    with pytest.raises(ValueError, match="SHA-256"):
        publisher.rollback("../../outside")


def test_current_artifact_corruption_is_detected(tmp_path) -> None:
    publisher = VersionedIndexPublisher(tmp_path)
    snapshot = publisher.capture_snapshot(
        source_id="official-place",
        source_url="https://example.invalid/place",
        fetched_at=NOW,
        content=b"source",
    )
    manifest = publisher.publish(
        [{"id": "v1"}], snapshots=[snapshot], created_at=NOW, validator=_accept
    )
    artifact = tmp_path / "builds" / manifest.build_id / "records.jsonl"
    artifact.write_text('{"id":"tampered"}\n')

    with pytest.raises(ValueError, match="integrity"):
        publisher.current_records()
