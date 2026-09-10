# Seed corpus

This directory contains manually reviewed, paraphrased records derived from official venue or
government pages. It is a development and evaluation seed, not a complete travel database.

- `places.jsonl`: stable entity metadata.
- `documents.jsonl`: source sections with authority and freshness metadata.
- `facts.jsonl`: typed facts for future filters and deterministic constraints.

Dynamic values such as prices, booking rules, and opening hours must not be treated as permanently
true. Preserve collection timestamps, refresh before production use, and fail closed when a hard
constraint cannot be verified.
