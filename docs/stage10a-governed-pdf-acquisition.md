# Stage 10A: governed official-PDF acquisition

## Outcome

Stage 10A adds four official Beijing travel/visitor PDF sources and a safe acquisition boundary before
introducing layout or OCR dependencies. It reuses Stage 8 conditional fetching and immutable snapshot
publication rather than creating a second ungoverned downloader.

The registry includes a Beijing municipal-government route guide, two Palace Museum visitor guides,
and a Chaoyang district-government guide. Each record stores the exact HTTPS host, authority,
parser-profile hint, content scopes, and response-size budget. Raw PDFs are referenced, not
redistributed.

## Data flow

```text
governed source registry
  -> exact HTTPS-host policy
  -> bounded conditional fetch
  -> response size and MIME checks
  -> PDF magic + complete EOF + active-content + optional digest checks
  -> immutable content-addressed raw snapshot
  -> future parser quarantine (Stage 10B)
  -> future isolated index build and promotion (Stage 10C)
```

## Selected technology and why

- Existing `httpx` transport: one timeout/retry/redirect policy instead of a PDF-only network path.
- Pydantic registry: URLs, hosts, authority, parser hint, and byte budgets fail during configuration
  loading rather than midway through an index build.
- SHA-256 snapshot identity: parsing can be reproduced against exact bytes even if the official URL
  later changes.
- Git-ignored raw workspace: keeps third-party binaries and partial downloads out of source control.

PyMuPDF and MinerU are intentionally not added in 10A. Fetch admission must be measurable before a
large parser dependency is trusted; 10B will compare text extraction and layout/OCR routing behind a
common typed contract.

## Controlled evaluation

Run:

```bash
travelmind eval-pdf-ingestion --root . \
  --output evals/results/stage10a_pdf_ingestion_v1.json
```

The deterministic drill covers ten contracts: registry validity, valid capture, snapshot
deduplication, exact-host rejection, MIME spoofing, missing magic, truncation, active content, digest
mismatch, and oversize rejection. All ten pass; rejected-payload admission is zero.

## Real-source observation

During development, the 9.9 MB Beijing municipal-government route PDF responded but transferred too
slowly for the bounded local operation. The partial 348 KB transfer was quarantined and created no
snapshot. Three other hosts failed TLS establishment from the development environment. These events
are dependency observations, not parser-quality results; the source registry remains usable from
other networks without weakening certificate checks.

## Claim boundary

Stage 10A proves source governance and PDF-specific byte admission on controlled payloads. It does not
yet prove that a real complex PDF was parsed correctly, that OCR works, or that PDF knowledge improves
retrieval or answer quality. Those claims require Stages 10B–10D.
