# Stage 4 final report

## Selected pipeline

```text
typed mandatory context
  -> scoped optional memory
  -> value-aware deduplication and conflict policy
  -> critical-fact extractive compression
  -> coverage-aware evidence selection
  -> 768-token envelope (192 output reserve + 64 safety margin)
  -> DeepSeek structured grounded answer
```

Prompt rendering includes only model-useful document ID, source type, and authority metadata. Full
URLs and internal aspect labels remain available for provenance and selection but do not consume
model context.

## Evidence-level result

On 15 retrieval seed queries, refined coverage uses 511.3 estimated input tokens on average versus
1520.7 unbounded. Relevant-document recall is 0.944, expected-aspect coverage is 1.000, and citation
provenance readiness is 1.000. Local context construction averages about 2.9 ms.

## Real DeepSeek answer A/B

Seven answer cases compare the same model, temperature, output schema, and query set.

| Metric | Unbounded | Refined coverage |
| --- | ---: | ---: |
| Task success | 0.857 | 1.000 |
| Required-term coverage | 0.857 | 1.000 |
| Citation precision | 0.857 | 1.000 |
| Citation recall | 0.857 | 1.000 |
| Abstention accuracy | 0.857 | 1.000 |
| Fallback rate | 0.143 | 0.000 |
| Total tokens | 6589 | 3605 |
| Mean successful-call latency | 1294.9 ms | 1205.2 ms |

The selected pipeline reduces provider tokens by 45.3%, improves the measured quality metrics, and
removes the observed output failure. The sample is small, project-authored, and seen during metric
debugging, so resume language must say “pilot A/B” rather than generalize to production traffic.

## Negative experiments and corrections retained

- v1 exposed an `evidence:` citation-prefix protocol mismatch.
- v2 exposed structured-output validation and long-context truncation failures.
- v3 achieved perfect refined-context citations but revealed two over-specified reference labels.
- v4 uses the frozen corrected label set and passes the final gate.

Old reports remain in `evals/results`; the v1 label set is retained as
`evals/datasets/context_answer_seed_v1.jsonl`. This preserves the error-analysis trail instead of
rewriting history.

## Final limitations

- Seven answer cases and 15 retrieval cases are not statistically significant.
- Reference-term matching can undercount valid paraphrases.
- Document-level citation correctness is weaker than sentence-level entailment.
- The answer set needs independent authorship, blind review, and repeated runs.
- Memory uses a reference in-process store; Redis/PostgreSQL integration is not yet claimed.
