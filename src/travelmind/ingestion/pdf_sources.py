from __future__ import annotations

import hashlib
import re
from collections.abc import Callable
from datetime import datetime
from pathlib import Path
from typing import Literal
from urllib.parse import urlsplit

from pydantic import BaseModel, Field, model_validator

from travelmind.ingestion.fetching import (
    CachedSource,
    ConditionalSourceFetcher,
    FetchDiagnostics,
    HttpxSourceTransport,
    SourceFetchPolicy,
    SourceResponseRejectedError,
    SourceTransport,
)
from travelmind.ingestion.publishing import SnapshotReceipt, VersionedIndexPublisher

PdfAuthority = Literal["government", "official_operator"]
PdfParserProfile = Literal["text_first", "layout_ocr"]


class PdfSourceSpec(BaseModel):
    source_id: str = Field(pattern=r"^[a-z0-9][a-z0-9-]{2,79}$")
    title: str = Field(min_length=1)
    source_url: str = Field(min_length=1)
    allowed_host: str = Field(min_length=1)
    authority: PdfAuthority
    parser_profile: PdfParserProfile
    content_scopes: list[str] = Field(min_length=1)
    maximum_response_bytes: int = Field(default=30_000_000, ge=1, le=50_000_000)
    expected_sha256: str | None = Field(default=None, pattern=r"^[0-9a-f]{64}$")

    @model_validator(mode="after")
    def validate_source_boundary(self) -> PdfSourceSpec:
        parsed = urlsplit(self.source_url)
        try:
            port = parsed.port
        except ValueError as exc:
            raise ValueError("PDF source URL has an invalid port") from exc
        if (
            parsed.scheme != "https"
            or parsed.hostname is None
            or parsed.hostname.lower() != self.allowed_host.lower()
            or parsed.username is not None
            or parsed.password is not None
            or port not in (None, 443)
        ):
            raise ValueError("PDF source URL must match its exact HTTPS host boundary")
        return self


class PdfSourceRegistry(BaseModel):
    schema_version: int = 1
    sources: list[PdfSourceSpec] = Field(min_length=1)

    @model_validator(mode="after")
    def validate_unique_ids(self) -> PdfSourceRegistry:
        identifiers = [source.source_id for source in self.sources]
        if len(identifiers) != len(set(identifiers)):
            raise ValueError("PDF source IDs must be unique")
        return self

    def get(self, source_id: str) -> PdfSourceSpec:
        for source in self.sources:
            if source.source_id == source_id:
                return source
        raise KeyError(f"unknown PDF source ID: {source_id}")


class PdfPayloadMetadata(BaseModel):
    content_sha256: str = Field(pattern=r"^[0-9a-f]{64}$")
    byte_count: int = Field(gt=0)
    pdf_version: str = Field(pattern=r"^[0-9]\.[0-9]$")


class PdfDownloadResult(BaseModel):
    source_id: str
    snapshot: SnapshotReceipt
    payload: PdfPayloadMetadata
    diagnostics: FetchDiagnostics


class PdfPayloadRejectedError(SourceResponseRejectedError):
    """A response looked like a PDF source but failed PDF-specific admission."""


_ACTIVE_CONTENT_MARKERS = (b"/JavaScript", b"/JS", b"/Launch", b"/EmbeddedFile")


def load_pdf_source_registry(path: Path) -> PdfSourceRegistry:
    return PdfSourceRegistry.model_validate_json(path.read_bytes())


def validate_pdf_payload(
    content: bytes,
    *,
    content_type: str,
    maximum_response_bytes: int,
    expected_sha256: str | None = None,
) -> PdfPayloadMetadata:
    normalized_type = content_type.split(";", 1)[0].strip().lower()
    if normalized_type not in {"application/pdf", "application/octet-stream"}:
        raise PdfPayloadRejectedError("PDF payload content type is not admitted")
    if not content or len(content) > maximum_response_bytes:
        raise PdfPayloadRejectedError("PDF payload size is outside its admitted boundary")
    header = re.search(rb"%PDF-([0-9]\.[0-9])", content[:1024])
    if header is None:
        raise PdfPayloadRejectedError("PDF payload magic header is missing")
    if b"%%EOF" not in content[-8192:]:
        raise PdfPayloadRejectedError("PDF payload appears truncated because EOF is missing")
    if any(marker in content for marker in _ACTIVE_CONTENT_MARKERS):
        raise PdfPayloadRejectedError("PDF payload contains disallowed active content")
    digest = hashlib.sha256(content).hexdigest()
    if expected_sha256 is not None and digest != expected_sha256:
        raise PdfPayloadRejectedError("PDF payload does not match its pinned digest")
    return PdfPayloadMetadata(
        content_sha256=digest,
        byte_count=len(content),
        pdf_version=header.group(1).decode("ascii"),
    )


class PdfSourceDownloader:
    def __init__(
        self,
        publisher: VersionedIndexPublisher,
        *,
        now: Callable[[], datetime],
        transport: SourceTransport | None = None,
        sleeper: Callable[[float], None] | None = None,
    ) -> None:
        self._publisher = publisher
        self._now = now
        self._transport = transport or HttpxSourceTransport()
        self._sleeper = sleeper

    def download(
        self,
        source: PdfSourceSpec,
        cached: CachedSource | None = None,
    ) -> PdfDownloadResult:
        policy = SourceFetchPolicy(
            allowed_hosts=frozenset({source.allowed_host}),
            freshness_class="static",
            fresh_ttl_seconds=86_400,
            maximum_stale_seconds=2_592_000,
            timeout_seconds=20,
            maximum_attempts=3,
            backoff_base_seconds=0.5,
            backoff_cap_seconds=2,
            maximum_response_bytes=source.maximum_response_bytes,
            allowed_content_types=frozenset({"application/pdf", "application/octet-stream"}),
        )
        options = {"now": self._now}
        if self._sleeper is not None:
            options["sleeper"] = self._sleeper
        fetcher = ConditionalSourceFetcher(self._transport, policy, **options)
        fetched = fetcher.fetch(source.source_url, cached)
        payload = validate_pdf_payload(
            fetched.source.content,
            content_type=fetched.source.content_type,
            maximum_response_bytes=source.maximum_response_bytes,
            expected_sha256=source.expected_sha256,
        )
        snapshot = self._publisher.capture_snapshot(
            source_id=source.source_id,
            source_url=source.source_url,
            fetched_at=fetched.source.captured_at,
            content=fetched.source.content,
        )
        if snapshot.content_sha256 != payload.content_sha256:
            raise RuntimeError("PDF validation and snapshot digests disagree")
        return PdfDownloadResult(
            source_id=source.source_id,
            snapshot=snapshot,
            payload=payload,
            diagnostics=fetched.diagnostics,
        )
