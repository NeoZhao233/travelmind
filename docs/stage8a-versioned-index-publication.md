# Stage 8A: versioned snapshots and atomic index publication

## Problem

A RAG index must not become partially visible when fetching, parsing, embedding, or validation fails.
Overwriting the active collection in place also removes the evidence needed to reproduce an answer
or roll back a bad parser/index build.

## Design

The local reference pipeline separates four states:

```text
raw response -> content-addressed snapshot
                         |
                         v
                 isolated staging build
                    | validation
              reject|          |accept
                    v          v
              quarantine   immutable build
                                  |
                           atomic CURRENT switch
```

- Raw bytes are stored by SHA-256. Identical bytes reuse one immutable snapshot; changed bytes create
  a new identity even if the URL is unchanged.
- Records are serialized canonically and written with a manifest containing build ID, artifact hash,
  snapshot hashes, timestamp, and record count.
- Validation runs before publication. Failure moves the complete staged directory to quarantine and
  raises a sanitized typed error.
- Publication atomically replaces a small `CURRENT` pointer only after the build manifest exists.
- Rollback changes that pointer to a previous complete immutable build; it does not rebuild data.
- Build IDs are validated as SHA-256 digests before path resolution, referenced snapshots must exist,
  and the active artifact hash is rechecked on read so traversal and silent corruption fail closed.

## Failure boundaries

`os.replace` is atomic only when source and destination are on the same filesystem. This local
implementation is not a distributed index transaction. Qdrant/Elasticsearch deployment should use a
versioned collection plus alias swap, while object storage should use immutable object keys and a
conditional metadata update.

An abrupt loss after moving a build but before switching `CURRENT` leaves an unused complete build,
not a partial active index. Loss after the atomic switch leaves either the previous or new pointer.
Production still needs startup reconciliation for orphan staging/build directories.

## Evaluation

The controlled drill passed all seven checks. Invalid publication blocking, previous-version
preservation, rollback, and snapshot deduplication rates were each 1.000. The result proves local
filesystem semantics on fixtures, not remote object-store or vector-database behavior.

```bash
travelmind eval-index-publishing --root . \
  --output evals/results/stage8a_index_publish_v1.json
```
