# External PDF source registry

`pdf_sources.json` lists official documents that may be fetched into the ignored `data/raw/`
workspace. Raw third-party PDFs are not redistributed in Git. A successful fetch is admitted only
after exact HTTPS-host, response-size, MIME/magic, complete-EOF, active-content, and optional digest
checks, then captured as an immutable content-addressed snapshot.

The documents provide static cultural, route, and visitor-guide context. They must not override newer
official HTML facts for prices, opening hours, booking rules, closures, or other dynamic constraints.

List the registry with:

```bash
travelmind list-pdf-sources --root .
```

Fetch one source with:

```bash
travelmind fetch-pdf-source beijing-top-summer-routes-2025 --root .
```

Network availability is not an indexing success condition. A timeout, invalid certificate, truncated
file, or rejected payload produces no snapshot and cannot replace the active retrieval index.
