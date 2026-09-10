# Human calibration annotations

`judge_calibration_seed_v1.json` contains seven source-variant-blinded answers. Fill only:

- `human_scores` with four integer scores from 1 to 5;
- `annotator_id` with a stable pseudonymous identifier;
- optional `annotation_notes` for ambiguity or label disputes.

Do not change query, response, case ID, candidate ID, source hashes, or rubric version. Use
`docs/stage6c-judge-calibration.md` as the scoring guide. A second annotator should work from a clean
copy without seeing the first annotator's scores. The current file is intentionally unlabeled and no
LLM judge result may be claimed until every item has a human label.
