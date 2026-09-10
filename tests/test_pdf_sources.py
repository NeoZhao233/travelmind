from datetime import UTC, datetime
from pathlib import Path

import pytest
from pydantic import ValidationError

from travelmind.ingestion import FetchResponse, VersionedIndexPublisher
from travelmind.ingestion.pdf_sources import (
    PdfPayloadRejectedError,
    PdfSourceDownloader,
    PdfSourceRegistry,
    PdfSourceSpec,
    load_pdf_source_registry,
    validate_pdf_payload,
)

NOW = datetime(2026, 9, 10, tzinfo=UTC)
PDF = b"%PDF-1.7\n1 0 obj\n<< /Type /Catalog >>\nendobj\n%%EOF\n"


class ScriptedTransport:
    def __init__(self, outcomes) -> None:
        self.outcomes = list(outcomes)

    def send(self, request):
        outcome = self.outcomes.pop(0)
        if isinstance(outcome, Exception):
            raise outcome
        return outcome


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


def test_project_pdf_registry_is_valid_and_uses_exact_https_hosts() -> None:
    root = Path(__file__).resolve().parents[1]
    registry = load_pdf_source_registry(root / "data/sources/pdf_sources.json")

    assert len(registry.sources) == 4
    assert {source.authority for source in registry.sources} <= {
        "government",
        "official_operator",
    }


def test_registry_rejects_duplicate_ids_and_source_host_mismatch() -> None:
    source = _source()
    with pytest.raises(ValidationError, match="unique"):
        PdfSourceRegistry(sources=[source, source])
    with pytest.raises(ValidationError, match="host boundary"):
        _source(source_url="https://attacker.example/guide.pdf")
    with pytest.raises(ValidationError, match="host boundary"):
        _source(source_url="http://official.example/guide.pdf")


def test_valid_pdf_is_captured_as_content_addressed_snapshot(tmp_path) -> None:
    downloader = PdfSourceDownloader(
        VersionedIndexPublisher(tmp_path),
        now=lambda: NOW,
        transport=ScriptedTransport([FetchResponse(200, {"content-type": "application/pdf"}, PDF)]),
        sleeper=lambda _: None,
    )

    result = downloader.download(_source())

    assert result.payload.pdf_version == "1.7"
    assert result.snapshot.content_sha256 == result.payload.content_sha256
    assert result.diagnostics.mode == "network_200"
    assert len(list((tmp_path / "snapshots").glob("*.raw"))) == 1


@pytest.mark.parametrize(
    ("content", "content_type", "message"),
    [
        (b"not a PDF%%EOF", "application/pdf", "magic"),
        (PDF.removesuffix(b"%%EOF\n"), "application/pdf", "truncated"),
        (PDF.replace(b"endobj", b"/JavaScript endobj"), "application/pdf", "active"),
        (PDF, "text/html", "content type"),
    ],
)
def test_pdf_specific_admission_rejects_spoofed_truncated_and_active_payloads(
    content, content_type, message
) -> None:
    with pytest.raises(PdfPayloadRejectedError, match=message):
        validate_pdf_payload(
            content,
            content_type=content_type,
            maximum_response_bytes=1_000_000,
        )


def test_rejected_pdf_creates_no_snapshot(tmp_path) -> None:
    downloader = PdfSourceDownloader(
        VersionedIndexPublisher(tmp_path),
        now=lambda: NOW,
        transport=ScriptedTransport(
            [FetchResponse(200, {"content-type": "application/pdf"}, b"%PDF-1.7 partial")]
        ),
        sleeper=lambda _: None,
    )

    with pytest.raises(PdfPayloadRejectedError, match="truncated"):
        downloader.download(_source())

    assert list((tmp_path / "snapshots").glob("*.raw")) == []
