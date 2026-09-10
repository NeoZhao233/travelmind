# Stage 8C: typed parsing, conflict resolution, and incremental fact indexing

## Typed parser boundary

External parsers return candidates, not trusted domain records. `TypedSourceParser` validates the
document and facts through Pydantic, then enforces cross-record invariants:

- fact IDs are unique inside the batch;
- every fact references the parsed document and same place;
- the parsed source URL matches the snapshotted URL;
- raw bytes still match the snapshot SHA-256 before the parser runs.

Failure writes only snapshot hash, parser version, and exception type to an owner-only quarantine
receipt. Raw content remains in the immutable snapshot store and exception messages do not enter
diagnostics.

## Conflict policy

A semantic fact key hashes place, fact type, unit, qualifiers, and validity interval; it excludes
value and source identity so competing values meet in one group. Resolution first groups equivalent
values, then compares the strongest representative of each distinct value:

1. higher source authority wins;
2. equal authority uses newer observation;
3. equal precedence with different values remains unresolved and is not served.

Equivalent-value grouping fixed a measured bug: two official records agreeing on 30 and one guide
reporting 20 previously caused the official duplicates to be compared with each other, hiding the
real conflict. The regression test now requires the official value to win.

Only evidence that already passed Stage 8B freshness admission should enter resolution. Otherwise an
obsolete high-authority source could incorrectly beat a current lower-authority observation.

## Incremental update

`IncrementalFactIndex` replaces one source document as an atomic copy-on-write transaction. It removes
that source's old facts, identifies the union of old and new semantic keys, and recomputes only those
keys. A byte-identical typed batch is a no-op. Fact-ID collision or resolver failure occurs before the
new dictionaries are committed, so previous serving state remains intact.

## Evaluation

All eight integrated checks passed. Parser quarantine, conflict policy, no-op detection, and failed
update preservation each scored 1.000. Changing one of two semantic keys produced an incremental
recompute ratio of 0.500.

```bash
travelmind eval-incremental-ingestion --root . \
  --output evals/results/stage8c_incremental_ingestion_v1.json
```

This proves a deterministic in-memory reference algorithm. It does not prove Qdrant/Elasticsearch
partial update behavior, real HTML parser robustness, concurrent writers, or user-facing handling of
unresolved facts.
