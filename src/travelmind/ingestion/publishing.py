from __future__ import annotations

import hashlib
import json
import os
import re
import shutil
from collections.abc import Callable
from datetime import datetime
from pathlib import Path
from typing import Any
from uuid import uuid4

from pydantic import BaseModel, Field


class IndexBuildRejectedError(RuntimeError):
    """A staged build failed validation and was not promoted."""


class SnapshotReceipt(BaseModel):
    source_id: str = Field(min_length=1)
    source_url: str = Field(min_length=1)
    fetched_at: datetime
    content_sha256: str = Field(pattern=r"^[0-9a-f]{64}$")
    byte_count: int = Field(ge=0)


class IndexBuildManifest(BaseModel):
    schema_version: int = 1
    build_id: str = Field(pattern=r"^[0-9a-f]{64}$")
    created_at: datetime
    artifact_sha256: str = Field(pattern=r"^[0-9a-f]{64}$")
    snapshot_hashes: list[str]
    record_count: int = Field(ge=0)


class VersionedIndexPublisher:
    """Content-addressed snapshots plus validate-before-atomic-promotion builds."""

    def __init__(self, root: Path) -> None:
        self.root = root.resolve()
        self.snapshots = self.root / "snapshots"
        self.staging = self.root / "staging"
        self.builds = self.root / "builds"
        self.quarantine = self.root / "quarantine"
        for directory in (
            self.snapshots,
            self.staging,
            self.builds,
            self.quarantine,
        ):
            directory.mkdir(parents=True, exist_ok=True)

    def capture_snapshot(
        self,
        *,
        source_id: str,
        source_url: str,
        fetched_at: datetime,
        content: bytes,
    ) -> SnapshotReceipt:
        digest = hashlib.sha256(content).hexdigest()
        destination = self.snapshots / f"{digest}.raw"
        if destination.exists():
            if destination.read_bytes() != content:
                raise RuntimeError("snapshot digest collision")
        else:
            _atomic_write(destination, content)
        return SnapshotReceipt(
            source_id=source_id,
            source_url=source_url,
            fetched_at=fetched_at,
            content_sha256=digest,
            byte_count=len(content),
        )

    def publish(
        self,
        records: list[dict[str, Any]],
        *,
        snapshots: list[SnapshotReceipt],
        created_at: datetime,
        validator: Callable[[list[dict[str, Any]]], None],
    ) -> IndexBuildManifest:
        if not snapshots:
            raise ValueError("an index build requires at least one source snapshot")
        for snapshot in snapshots:
            if not (self.snapshots / f"{snapshot.content_sha256}.raw").is_file():
                raise ValueError("index build references a missing source snapshot")
        artifact = _canonical_jsonl(records)
        artifact_hash = hashlib.sha256(artifact).hexdigest()
        snapshot_hashes = sorted({item.content_sha256 for item in snapshots})
        identity = json.dumps([artifact_hash, snapshot_hashes], separators=(",", ":")).encode()
        build_id = hashlib.sha256(identity).hexdigest()
        manifest = IndexBuildManifest(
            build_id=build_id,
            created_at=created_at,
            artifact_sha256=artifact_hash,
            snapshot_hashes=snapshot_hashes,
            record_count=len(records),
        )
        stage = self.staging / f"{build_id}-{uuid4().hex}"
        stage.mkdir(mode=0o700)
        _atomic_write(stage / "records.jsonl", artifact)
        _atomic_write(
            stage / "manifest.json",
            manifest.model_dump_json(indent=2).encode(),
        )
        try:
            validator(records)
        except Exception as exc:
            rejected = self.quarantine / stage.name
            os.replace(stage, rejected)
            raise IndexBuildRejectedError(f"index build rejected by {type(exc).__name__}") from exc

        destination = self.builds / build_id
        if destination.exists():
            shutil.rmtree(stage)
        else:
            os.replace(stage, destination)
        self._promote(build_id)
        return manifest

    def current_manifest(self) -> IndexBuildManifest | None:
        pointer = self.root / "CURRENT"
        if not pointer.exists():
            return None
        build_id = pointer.read_text(encoding="ascii").strip()
        _validate_build_id(build_id)
        manifest = IndexBuildManifest.model_validate_json(
            (self.builds / build_id / "manifest.json").read_bytes()
        )
        if manifest.build_id != build_id:
            raise ValueError("active pointer and manifest identity do not match")
        return manifest

    def current_records(self) -> list[dict[str, Any]]:
        manifest = self.current_manifest()
        if manifest is None:
            return []
        path = self.builds / manifest.build_id / "records.jsonl"
        artifact = path.read_bytes()
        if hashlib.sha256(artifact).hexdigest() != manifest.artifact_sha256:
            raise ValueError("active index artifact failed integrity validation")
        return [json.loads(line) for line in artifact.decode().splitlines() if line]

    def rollback(self, build_id: str) -> IndexBuildManifest:
        _validate_build_id(build_id)
        manifest_path = self.builds / build_id / "manifest.json"
        if not manifest_path.is_file():
            raise FileNotFoundError("rollback build does not exist")
        manifest = IndexBuildManifest.model_validate_json(manifest_path.read_bytes())
        self._promote(manifest.build_id)
        return manifest

    def _promote(self, build_id: str) -> None:
        _validate_build_id(build_id)
        if not (self.builds / build_id / "manifest.json").is_file():
            raise FileNotFoundError("cannot promote incomplete build")
        _atomic_write(self.root / "CURRENT", f"{build_id}\n".encode("ascii"))


def _canonical_jsonl(records: list[dict[str, Any]]) -> bytes:
    lines = [
        json.dumps(record, ensure_ascii=False, sort_keys=True, separators=(",", ":"))
        for record in records
    ]
    return ("\n".join(lines) + ("\n" if lines else "")).encode()


def _validate_build_id(build_id: str) -> None:
    if re.fullmatch(r"[0-9a-f]{64}", build_id) is None:
        raise ValueError("build ID must be a SHA-256 digest")


def _atomic_write(destination: Path, content: bytes) -> None:
    temporary = destination.with_name(f".{destination.name}.{uuid4().hex}.tmp")
    try:
        with temporary.open("xb") as handle:
            handle.write(content)
            handle.flush()
            os.fsync(handle.fileno())
        temporary.chmod(0o600)
        os.replace(temporary, destination)
    finally:
        temporary.unlink(missing_ok=True)
