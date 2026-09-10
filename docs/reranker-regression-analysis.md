# Why the reranker regressed: evidence and hypotheses

## Observed result

The BGE cross-encoder did not fail operationally: all 15 calls succeeded. It changed ranking in a
way that reduced aggregate Recall@3 from 0.922 to 0.878 and NDCG@3 from 0.930 to 0.912, while mean
local latency rose from 2.56ms to 230.12ms.

The correct interpretation is not “rerankers are bad.” The result shows a mismatch between this
general reranker's scoring objective and this project's evidence-selection objective.

## Root-cause analysis

### 1. Semantic relevance is not hard-constraint satisfaction

The largest regression is `海淀区的皇家园林景点门票信息`. RRF ranked the Summer Palace ticket
document first. The cross-encoder promoted a broad Summer Palace description and moved the ticket
document to rank 8.

The broad description is semantically close to “皇家园林景点,” but it does not answer the requested
fact type, “门票.” A generic relevance model can reward topical similarity without enforcing
district, category, price, booking, or opening-hour constraints. These constraints need typed
filtering/validation or a grader trained to distinguish fact types.

### 2. Independent pair scoring does not optimize evidence-set coverage

Each candidate receives an independent query-document score. The model does not know whether the
top-k set already contains a description, ticket rule, opening time, and counter-evidence. It can
therefore fill several positions with topically similar descriptions while dropping a less fluent
but necessary fact section.

Travel planning often needs a *set* of complementary evidence, not ten interchangeable relevant
passages. Recall and coverage can decline even when each selected item looks individually plausible.

### 3. The evaluation labels include supporting and counter-evidence

For the Monday, low-budget, no-reservation query, labels include the best option plus lower-grade
evidence explaining why alternatives fail. The reranker successfully promoted the best option and
improved multi-constraint Recall@3, but a pointwise model has no explicit objective to retain all
comparison evidence. Recommendation relevance and reasoning-evidence coverage are different tasks.

### 4. Replacing the RRF order discarded useful consensus

RRF rewards documents supported by lexical and dense channels. Full cross-encoder replacement
throws away that consensus prior. A diagnostic fusion of the RRF and reranker rankings raised
Recall@3 to 0.944, but reduced Recall@1, MRR@3, and NDCG@3. This confirms that the two rankings contain
complementary signals, while also showing that an untuned second fusion is not a safe default.

### 5. Input enrichment did not solve the objective mismatch

Diagnostic-only ablations on the same 15 queries set produced:

| Reranker input | Recall@3 | MRR@3 | NDCG@3 |
| --- | ---: | ---: | ---: |
| Chunk content only | 0.878 | 0.933 | 0.924 |
| Place + title + section + content | 0.822 | 0.933 | 0.902 |
| Current enriched input including tags | 0.878 | 0.933 | 0.912 |

Adding metadata text can introduce repeated topical tokens and make a broad description appear even
more relevant. Structured constraints should not be flattened into text and assumed to remain hard
constraints.

### 6. The pilot set magnifies individual failures

The metadata group contains three queries. One catastrophic miss changes group Recall@3 by 0.333
and aggregate Recall@3 by 0.044. The failure is real for this case, but the dataset is too small to
estimate general behavior or tune a router safely.

## Diagnostic routing result and leakage warning

An oracle that used the ground-truth `query_type` to skip reranking for metadata queries reached
Recall@3 0.944 and NDCG@3 0.989. This is **not a valid model result**: using evaluation labels to
choose the path is target leakage.

It produces a testable Stage 3 hypothesis: classify query intent without labels, route hard-
constraint/fact lookup through structured validation, and use expensive semantic reranking only
where a held-out set shows benefit.

## Engineering decision

- Keep Hybrid RRF as the default.
- Keep the reranker adapter and its fallback tests for future model comparison.
- Do not tune routing, fusion weights, or thresholds on the 15-query pilot.
- Expand data and create development/held-out splits before another selection decision.
- In Stage 3, separate query intent, fact-type coverage, and evidence-set sufficiency rather than
  asking one relevance score to solve all three.

## Interview summary

“The cross-encoder was operationally healthy but optimized pointwise semantic relevance, while the
planner needed hard-constraint matching and complementary evidence coverage. It helped multi-
constraint recommendation ranking but displaced a ticket fact with a broad attraction description.
Input-text changes did not fix this, and an oracle routing result was explicitly rejected as label
leakage. Therefore RRF stayed default and the finding became the motivation for typed routing and
evidence grading in Agentic RAG.”
