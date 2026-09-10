from __future__ import annotations

import tempfile
from datetime import UTC, datetime
from pathlib import Path

from pydantic import ValidationError

from travelmind.ingestion.fetching import FetchResponse
from travelmind.ingestion.pdf_sources import (
    PdfPayloadRejectedError,
    PdfSourceDownloader,
    PdfSourceSpec,
    load_pdf_source_registry,
    validate_pdf_payload,
)
from travelmind.ingestion.publishing import VersionedIndexPublisher

_NOW = datetime(2026, 9, 10, tzinfo=UTC)
_PDF = b"%PDF-1.7\n1 0 obj\n<< /Type /Catalog >>\nendobj\n%%EOF\n"


class _ScriptedTransport:
    def __init__(self, outcome) -> None:
        self.outcome = outcome

    def send(self, request):
        if isinstance(self.outcome, Exception):
            raise self.outcome
        return self.outcome


def _source(**updates) -> PdfSourceSpec:
    values = {
        "source_id": "official-guide",
        "title": "Official guide",
        "source_url": "https://official.example/guide.pdf",
        "allowed_host": "official.example",
        "authority": "government",
        "parser_profile": "text_first",
        "content_scopes": ["route"],
    }
    values.update(updates)
    return PdfSourceSpec.model_validate(values)


def _rejected(content: bytes, content_type: str = "application/pdf", **options) -> bool:
    try:
        validate_pdf_payload(
            content,
            content_type=content_type,
            maximum_response_bytes=options.pop("maximum_response_bytes", 1_000_000),
            **options,
        )
    except PdfPayloadRejectedError:
        return True
    return False


def run_pdf_ingestion_drill(project_root: Path) -> dict:
    registry = load_pdf_source_registry(project_root / "data/sources/pdf_sources.json")
    with tempfile.TemporaryDirectory(prefix="travelmind-pdf-ingestion-") as directory:
        publisher = VersionedIndexPublisher(Path(directory))
        downloader = PdfSourceDownloader(
            publisher,
            now=lambda: _NOW,
            transport=_ScriptedTransport(
                FetchResponse(200, {"content-type": "application/pdf"}, _PDF)
            ),
            sleeper=lambda _: None,
        )
        first = downloader.download(_source())
        second = downloader.download(_source())
        snapshot_count = len(list(publisher.snapshots.glob("*.raw")))

        try:
            _source(source_url="https://attacker.example/guide.pdf")
            host_boundary_rejected = False
        except ValidationError:
            host_boundary_rejected = True

        checks = {
            "official_registry_valid": len(registry.sources) == 4,
            "valid_pdf_captured": first.snapshot.content_sha256 == first.payload.content_sha256,
            "snapshot_deduplicated": snapshot_count == 1
            and first.snapshot.content_sha256 == second.snapshot.content_sha256,
            "host_boundary_rejected": host_boundary_rejected,
            "spoofed_mime_rejected": _rejected(_PDF, "text/html"),
            "missing_magic_rejected": _rejected(b"not-pdf%%EOF"),
            "truncated_payload_rejected": _rejected(_PDF.removesuffix(b"%%EOF\n")),
            "active_content_rejected": _rejected(_PDF.replace(b"endobj", b"/JavaScript endobj")),
            "digest_mismatch_rejected": _rejected(_PDF, expected_sha256="0" * 64),
            "oversized_payload_rejected": _rejected(_PDF, maximum_response_bytes=len(_PDF) - 1),
        }
    cases = [{"check": name, "passed": passed} for name, passed in checks.items()]
    passed_count = sum(checks.values())
    rejected_checks = [passed for name, passed in checks.items() if name.endswith("rejected")]
    return {
        "experiment": "pdf-source-admission-v1",
        "stage": "10A",
        "configuration": {
            "registered_official_sources": len(registry.sources),
            "raw_pdf_distribution": "source-reference-only",
            "network_required": False,
        },
        "cases": cases,
        "metrics": {
            "checks": len(checks),
            "check_pass_rate": passed_count / len(checks),
            "rejected_payload_admission_rate": 0.0 if all(rejected_checks) else 1.0,
            "snapshot_deduplication_rate": 1.0 if checks["snapshot_deduplicated"] else 0.0,
        },
        "status": "passed" if passed_count == len(checks) else "failed",
        "claim_boundary": (
            "Deterministic admission and snapshot drill; no live-source availability, "
            "PDF text extraction, OCR, or retrieval-quality claim."
        ),
    }
