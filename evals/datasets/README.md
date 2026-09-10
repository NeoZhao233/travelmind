# Retrieval evaluation datasets

`retrieval_seed.jsonl` is the Stage 1 pilot set. Its 15 queries are balanced across five diagnostic
categories and use document-level graded relevance. All current rows were reviewed by the project
owner, which proves the evaluation plumbing but does not eliminate single-annotator bias.

Future versions should add paraphrases, hard negatives, no-answer cases, date-relative questions,
geographic diversity, and a second annotator. Dataset versions must remain fixed while retrieval
components are compared.

`retrieval_benchmark_v2.jsonl` is the Stage 12 draft expansion: 105 queries, 35 intent clusters,
five balanced query types, 30 no-answer examples, and an intent-isolated 45/60 development/test
split. Three paraphrases share one `intent_id` and never cross splits. Its labels are Codex-authored
and deliberately remain `reviewed=false`; the committed generator makes that provenance explicit.
Schema validity and bootstrap intervals do not substitute for independent relevance review.

`runtime_failure_matrix_v2.jsonl` contains 34 deterministic fault-injection contracts spanning four
tool positions and six failure modes. It measures retry/replan/safe-stop path coverage, not the
probability of recovery from production incidents.

`e2e_planning_seed.manifest.json` governs the Stage 5 end-to-end cases without rewriting their task
labels. It freezes a 3/2 development/test partition, pins the source SHA-256, records authorship and
review state, and supports leakage checks. All five labels are currently project-authored; the two
test cases are neither independently reviewed nor blind.
