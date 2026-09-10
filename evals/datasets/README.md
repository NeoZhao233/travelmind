# Retrieval evaluation datasets

`retrieval_seed.jsonl` is the Stage 1 pilot set. Its 15 queries are balanced across five diagnostic
categories and use document-level graded relevance. All current rows were reviewed by the project
owner, which proves the evaluation plumbing but does not eliminate single-annotator bias.

Future versions should add paraphrases, hard negatives, no-answer cases, date-relative questions,
geographic diversity, and a second annotator. Dataset versions must remain fixed while retrieval
components are compared.

`e2e_planning_seed.manifest.json` governs the Stage 5 end-to-end cases without rewriting their task
labels. It freezes a 3/2 development/test partition, pins the source SHA-256, records authorship and
review state, and supports leakage checks. All five labels are currently project-authored; the two
test cases are neither independently reviewed nor blind.
