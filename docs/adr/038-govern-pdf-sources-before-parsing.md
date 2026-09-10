# ADR 038: Govern PDF sources before adding complex parsers

## Status

Accepted.

## Decision

TravelMind registers exact official HTTPS PDF URLs and their trust metadata before parsing them.
Raw third-party PDFs are downloaded into the ignored workspace and captured by content hash; they are
not redistributed in Git. Admission checks response size, MIME, PDF magic and EOF, active-content
markers, and an optional pinned digest before a snapshot can exist.

Text-native and layout/OCR parsing remain the next boundary. A parser is never allowed to fetch its
own arbitrary URL or publish directly into the active retrieval index.

## Why

- PDF parsers operate on untrusted binary input and have a larger attack surface than JSON records.
- Content-type alone is spoofable, while magic alone cannot detect a truncated transfer.
- Exact host allowlists reduce SSRF and redirect surprises.
- Content-addressed snapshots make later extraction and index builds reproducible.
- Keeping raw PDFs out of Git avoids presenting third-party documents as project-owned artifacts.

## Rejected alternatives

- **Commit all PDFs:** easier offline demos, but poor provenance/licensing hygiene and repository size.
- **Let MinerU or PyMuPDF download URLs:** mixes trust, network, and parsing boundaries.
- **Accept any document that starts with `%PDF`:** admits truncated and active-content payloads.
- **Require one permanent URL hash in the source registry:** official publishers may replace a file;
  a newly observed hash should be reviewed and versioned rather than silently accepted or permanently
  blocking every legitimate update.

## Failure behavior

A transport, TLS, size, MIME, magic, EOF, active-content, or digest failure produces no snapshot and
cannot affect the active index. An existing validated index remains available. Diagnostics expose only
typed failure classes rather than response bodies or local content.

## Interview questions

- Why is PDF ingestion a security boundary rather than merely a parser choice?
- Why keep source references in Git but raw PDFs outside it?
- Why validate both MIME and magic/EOF?
- What can byte-marker scanning not prove about PDF safety?
