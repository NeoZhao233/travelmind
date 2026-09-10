# Interview question backlog

Questions are added when the corresponding code is implemented. Answers must point to code,
tests, traces, or experiment results instead of relying on generic definitions.

## Architecture

- Why does this project need LangGraph rather than a linear chain?
- Why start with a single controlled workflow rather than multiple agents?
- Which decisions belong to an LLM and which belong to deterministic code?
- How is graph state kept serializable and small?
- How are retries bounded, and which nodes must be idempotent?

## Retrieval

- Which travel queries fail with dense-only retrieval?
- Why can dense and BM25 scores not be added directly?
- Why was RRF selected, and how was its constant tuned?
- How are ground-truth relevant documents labeled?
- Does a higher retrieval recall improve itinerary quality?
- How is stale or contradictory evidence handled?
- Derive or explain the BM25 score: what do IDF, `k1`, and `b` control?
- Why use positive-IDF BM25 rather than plain TF-IDF?
- Why does Chinese lexical retrieval require an explicit tokenization choice?
- Why does the baseline combine Chinese unigrams and bigrams rather than relying on Jieba?
- Why are place metadata and document fields included in searchable text?
- How are multiple chunks aggregated to a document-level ranking?
- What is the failure case behind “进/入口、出/离开”, and which component should address it?
- Which metadata constraints are safe as prefilters, and which should remain post-retrieval checks?
- Why can strict prefiltering improve P@1 and NDCG but reduce Recall@10?
- How are unsupported filters exposed instead of silently ignored?
- Why was `BAAI/bge-small-zh-v1.5` selected instead of BGE-base, BGE-M3, or a hosted API?
- Why is the Chinese retrieval instruction added to queries but not passages?
- Why FastEmbed/ONNX instead of a full SentenceTransformers/PyTorch serving stack?
- Why is the embedding provider injected instead of using Qdrant's implicit inference directly?
- Why use cosine similarity, and can a cosine score be negative?
- Why are zero, NaN, infinite, and wrong-dimension vectors rejected before indexing?
- How do model ID, dependency lock, and cached-artifact hash protect different layers of reproducibility?
- Why did dense improve Recall@3 but reduce MRR@3 and Recall@10?
- Which query types improved with dense retrieval and which regressed?
- Why should Qdrant local-mode latency not be presented as production latency?
- How will dense failure degrade to BM25 without hiding a chronic outage?
- Why run sparse and dense concurrently instead of sequentially?
- What exactly happens on sparse-only failure, dense-only failure, and dual failure?
- Why is a thread-level timeout not sufficient to stop a stuck provider request?
- Which channel details are safe to log, and why are exception messages omitted?
- Why does the current hybrid path reject metadata filters?
- Why add a cross-encoder after RRF rather than at the same time?
- Why was the implemented cross-encoder rejected from the default path?
- How can a reranker improve multi-constraint queries while reducing aggregate quality?
- Why can a reranker not recover a relevant document absent from its candidate set?
- Which licensing issue affected the multilingual reranker alternatives?

## Data and ingestion

- Why use JSONL for the seed corpus instead of a database dump or CSV?
- Why separate stable place entities, source documents, and typed facts?
- Why keep normalized facts if the RAG corpus already contains the same information?
- Why label relevance at document-section level instead of chunk level?
- What do relevance grades 1, 2, and 3 mean, and which metrics consume them?
- Why is official source authority not enough to guarantee correctness?
- How do `static`, `seasonal`, and `dynamic` freshness classes affect runtime behavior?
- What happens when two official sources conflict or one has no update timestamp?
- Why does ingestion reject timestamps without timezones?
- How are duplicate IDs, orphan references, and cross-place facts detected before indexing?
- Why start with manually curated summaries rather than a crawler?
- How would you make crawling idempotent and avoid publishing a partially refreshed corpus?
- Why choose character-based structure-aware chunking as the baseline?
- Why is the current token count called an estimate rather than a measured value?
- How would you compare overlap, token windows, parent-child, and semantic chunking fairly?
- Why can chunk overlap inflate recall or waste reranker/context budget?
- Why are content-derived chunk IDs useful, and what happens after a text correction?
- Is 15 single-annotator queries enough? What is the expansion and agreement plan?

## Context engineering

- What information does each node see, and why?
- How is the context token budget allocated?
- What is compressed, and what must never be summarized away?
- How do short-term graph state and long-term user memory differ?

## Evaluation

- What is the simplest baseline?
- Which metrics are deterministic and which use an LLM judge?
- How is an LLM judge calibrated against human labels?
- How are quality gains balanced against latency and token cost?
- What failure cases caused an architecture change?
- How do Precision@k, Recall@k, MRR@k, and NDCG@k differ?
- Why does NDCG use the 1–3 relevance grades while recall treats all positive grades as relevant?
- Why is P@k divided by `k` even when the retriever returns fewer than `k` results?
- Why are duplicate document IDs removed before scoring?
- Why are abstention examples excluded from recall and measured separately?
- How does the dataset fingerprint prevent invalid experiment comparisons?
- Why are the current BM25 metrics not yet suitable as resume claims?
- Why should parameters be tuned on a development split and evaluated once on held-out data?

## Reliability and graceful degradation

- What happens when the primary LLM times out or returns invalid structured output?
- Which failures are safe to retry, and how are duplicate side effects prevented?
- How are exponential backoff, jitter, timeouts, and maximum attempts configured?
- What happens when dense retrieval, sparse retrieval, or the reranker is unavailable?
- Can stale cached opening hours be used, and how is staleness shown to the user?
- Which failures should degrade gracefully and which must fail closed?
- What happens if PostgreSQL, Redis, Qdrant, or LangSmith is unavailable?
- How does the graph resume after a process crash, and which state is checkpointed?
- How are partial results represented without misleading the user?
- How do you test timeout, malformed output, dependency outage, and retry exhaustion?
- What metrics indicate that a fallback path is being used too frequently?
- How would you prevent a retry storm during a downstream outage?
- Why can a distribution appear installed but still be non-importable?
- Why does local development use an editable install while deployment should not?
- Why can a non-editable local package remain stale even when dependency synchronization passes?

## Current implementation checkpoints

- The first graph uses injected Retriever and Planner protocols so providers can be changed in
  ablation experiments without rewriting orchestration.
- Retrieval retries are explicitly bounded and covered by a test.
- Exhausted retrieval retries return an explicit failure reason instead of fabricating evidence.
- Budget, inclusion, exclusion, and time-overlap checks are deterministic and independently
  testable; they are not delegated to an LLM.
- The demo adapters are deliberately labeled as placeholders and produce no claimed metrics.
- Stage 0 validates package import and CLI startup in addition to unit tests and static analysis;
  an existing `.venv` directory alone is not considered a healthy environment.
- Stage 1 validates 5 places, 14 source documents, 22 facts, 14 current chunks, and 15 reviewed
  retrieval examples. These counts prove the data contract, not retrieval quality.
- Document-level labels isolate retrieval experiments from chunk-ID changes; expected fact types
  additionally detect evaluation questions unsupported by the structured fact set.
- Source authority and freshness are modeled separately, so an official but stale opening time does
  not silently become a valid hard constraint.
- The 500-character chunker is a deterministic baseline and has no claimed advantage until Stage 2
  runs an ablation.
- Stage 2A records two real BM25 reports. Pure lexical retrieval achieved Recall@3 0.856 and
  Recall@10 1.000 on the 15-query pilot; supported prefilters raised P@1 from 0.867 to 0.933 while
  reducing Recall@10 to 0.956. The repository explicitly limits the interpretation of these values.
- The evaluator reports per-query and per-query-type errors, making multi-constraint Recall@3 0.444
  a visible target for dense/hybrid retrieval rather than hiding it inside an aggregate score.
- Stage 2B runs the real 512-dimensional Chinese BGE model through Qdrant. Dense Recall@3 is 0.900
  versus BM25's 0.856, while dense MRR@3 is lower at 0.900 versus 0.933. Exact-query Recall@1 rises
  to 1.000 and multi-constraint Recall@3 to 0.667, but semantic Recall@1 falls to 0.500.
- Dense experiment reports record FastEmbed 0.8.0, the versioned model ID, query instruction,
  registered sources, and the cached model artifact fingerprint. The normal unit suite uses a fake
  embedder and never downloads model weights.
- Stage 2C executes BM25 and dense retrieval concurrently and fuses only document ranks. On the
  same pilot fingerprint, RRF achieved P@1 0.933, Recall@3 0.922, MRR@3 0.956, and NDCG@3 0.930;
  all exceed both unfiltered single-channel rows on those cutoffs, while the small dataset limits
  the claim.
- Hybrid diagnostics record 15 healthy hybrid queries in the measured run. Separate injected tests
  prove sparse-only fallback, timeout fallback, dual-failure behavior, and error-text redaction.

## Stage 2C answer anchors

**Why RRF instead of adding scores?** BM25 and cosine scores are not calibrated and do not share a
scale. RRF consumes rank positions, rewards agreement between channels, and gives a deterministic
baseline before learned fusion. Raw scores remain metadata for analysis, not fusion inputs.

**How was `k=60` chosen?** It is a conventional baseline constant, not a tuned optimum. The current
15-query set has no development/test split, so tuning it here would overfit. The honest next step is
to expand labels, tune on development data, and report once on held-out data.

**What if one retriever fails?** The response uses the surviving ranking, changes mode to
`sparse_only` or `dense_only`, and records the failed component and fallback. If both fail, it raises
`HybridRetrievalError` so the graph cannot manufacture evidence. Fallback rate must be alerted on;
degraded availability is not normal success.

**Why parallel execution?** The channels have no dependency on each other, so sequential execution
adds their latencies. With concurrency, normal latency approaches the slower branch plus fusion
overhead. The local implementation uses two bounded threads because both adapters are blocking;
an async service should use async clients or a bounded worker pool.

**Does the timeout cancel a stuck request?** No. `Future.cancel()` cannot terminate a Python thread
that is already running. The orchestration deadline prevents that result from delaying the current
response, while provider-native connection/read/inference deadlines prevent resource leakage.

**Why reject hybrid filters for now?** BM25 implements typed prefilters while the dense channel does
not yet enforce the identical semantics. Filtering only one branch would create a misleading
contract and could reintroduce excluded evidence through the other branch. The CLI fails explicitly
until both channels share filter behavior.

**What did Hybrid actually improve?** On the fixed pilot, Recall@3 moved from 0.856 (BM25) and 0.900
(dense) to 0.922; MRR@3 moved to 0.956. The remaining multi-constraint Recall@3 is 0.778. These are
debugging signals on 15 single-annotator queries, not production or resume-grade guarantees.

## Stage 2D answer anchors

**Why add the cross-encoder after RRF?** A bi-encoder independently embeds query and document,
which is efficient for candidate generation; a cross-encoder jointly attends to the pair, which is
more expressive but much more expensive. Applying it only to ten RRF candidates bounds cost and
makes its incremental effect measurable.

**Why choose BGE reranker base?** It supports Chinese, has an MIT license, works through the pinned
FastEmbed/ONNX runtime, and represents a serious multilingual candidate. The smaller registered
MiniLM choices are English-oriented, while the Jina multilingual alternative has a non-commercial
license and similar one-gigabyte scale.

**Why was it not enabled by default?** On the same fingerprint, Recall@3 fell from 0.922 to 0.878,
MRR@3 from 0.956 to 0.933, and NDCG@3 from 0.930 to 0.912. Mean local latency rose from 2.56ms to
230.12ms. P@1 merely stayed flat. Shipping it would add cost and a failure domain for worse measured
behavior.

**Was the experiment entirely negative?** No. Multi-constraint Recall@3 rose from 0.778 to 0.889,
but metadata Recall@3 fell from 1.000 to 0.667. This points toward typed constraint handling or
routing, not a blanket conclusion that rerankers are harmful.

**What happens if reranking fails?** The wrapper validates score count and finiteness. An exception,
invalid score, or deadline preserves the original RRF order and records reranker degradation.
Startup provisioning failure aborts the explicitly reranked experiment so it cannot emit a report
misrepresented as a successful reranker run.

**Why did a healthy reranker still hurt?** Its pointwise semantic score is not a hard-constraint or
set-coverage objective. It promoted a broad royal-garden description over the requested ticket
section and could not preserve complementary comparison evidence. Changing text enrichment did not
repair the mismatch. The detailed evidence is in `docs/reranker-regression-analysis.md`.

**Why not use the query-type result to route immediately?** The promising “skip metadata reranking”
number used ground-truth evaluation labels, so it is an oracle upper bound and would be target
leakage if reported as system quality. Stage 3 must predict intent from request data and validate it
on a held-out split.

## Stage 3A answer anchors

**Why is this Agentic RAG rather than a fixed RAG pipeline?** Retrieval results are graded against
request-specific evidence aspects. The graph conditionally generates, rewrites and retries, or
fails. The runtime path therefore depends on state, while termination remains bounded and visible.

**Why LangGraph instead of a loop inside one function?** The retry cycle, node inputs, transitions,
and terminal states are explicit. Policy dependencies stay injectable, trajectory events align with
node boundaries, and later checkpoint recovery has stable resume points.

**Why are the first router, grader, and rewriter deterministic?** They provide reproducible
baselines and failure fallbacks. An LLM policy added next must improve route, sufficiency, or rewrite
recovery metrics enough to justify tokens, latency, and invalid-output risk.

**Why not store chain-of-thought in graph state?** It is verbose, unstable, privacy-sensitive, and
not required for control. The state stores selected intent, reason codes, coverage, missing aspects,
attempts, and sanitized error types—enough to evaluate decisions without persisting hidden reasoning.

**Why independently execute rewrites?** Concatenating queries can cause token interference and loses
attribution. Independent rankings can retrieve different evidence and be fused with RRF. Deduplication
and a four-query cap bound cost and prevent decomposition explosion.

**What happens if evidence never becomes sufficient?** The graph stops after the configured attempt
budget, reports the missing aspects, and does not call the planner. Availability is not allowed to
turn into unsupported generation.

## Stage 3A implementation checkpoint

- The Agentic graph records route, evidence assessment, rewrite count, retrieval attempts,
  trajectory events, degraded components, and sanitized dependency failures.
- Evidence grading distinguishes admission, hours, booking, route, and accessibility coverage and
  requires a trusted source category.
- Missing evidence can recover on a second retrieval; exhausted attempts terminate explicitly.
- Multi-Query retrieval executes variants independently, caps fanout at four, and fuses rankings
  rather than concatenating query text.
- The 69-test suite includes Router, Grader, Rewriter, Retriever, and per-query failure injection.
- No route-accuracy or rewrite-lift number is claimed yet because a separate reviewed trajectory
  dataset and held-out split do not exist.

## Stage 3B policy-evaluation answer anchors

**Why not reuse retrieval relevance labels to evaluate the Router and Grader?** Retrieval labels
answer which documents are relevant. A Router label answers which control strategy the request
needs, while a Grader label answers whether a particular evidence set covers the request. Reusing
one target for all three creates label leakage and can reward the wrong behavior.

**What did the first policy baseline reveal?** `rule-v1` routing reached 70% on 10 development cases
but 0% on five test cases. Evidence sufficiency reached 100% development accuracy but 60% test
accuracy. The dominant error was lexical brittleness: unseen paraphrases such as entering through a
door, leaving from the north, or asking about a time of day did not activate the intended aspect.
Location and attraction-type filters were also missing from the routing constraint model.

**Why keep such a poor result?** It is the untuned control baseline and an error taxonomy. Deleting
or overwriting it would hide the exact weaknesses the next policy must beat. A useful experiment
preserves regressions and negative results, as the reranker ablation already demonstrated.

**Can you claim the test score is a reliable generalization estimate?** No. The split is fixed and
the evaluation code does not train on test rows, but all labels were authored inside the project
and have not been independently reviewed. It proves evaluation plumbing and exposes failures; it
does not support a production-quality accuracy claim.

**What would you optimize next?** First enlarge and independently review the dataset. Then tune only
on development cases, freeze a new policy version, and evaluate once on an untouched test set. For
LLM policies, compare quality lift against token cost, latency, invalid structured output, and the
deterministic fallback activation rate.

## Stage 3C trajectory-evaluation answer anchors

**How do you know Agentic RAG helped rather than the retriever randomly returning better results?**
The first control experiment scripts identical per-attempt evidence using validated real document
IDs. Direct RAG sees step one; Agentic RAG may conditionally reach step two. This isolates the causal
effect of grading, rewriting, and retry. A separate live Hybrid RRF experiment is still required for
end-to-end validity.

**What improvement and cost did you observe?** On seven draft control cases, task success increased
from 42.9% to 85.7%, and all three recoverable cases completed. Average retrieval calls increased
from 1.00 to 1.57. The sample is too small for a general quality claim.

**Did Agentic RAG make the system safe?** No. Both paths had a 14.3% unsupported-generation rate
because the deterministic Grader missed a time-of-day paraphrase and treated irrelevant trusted
evidence as sufficient. Retry fixes missing evidence only when insufficiency is detected; the Grader
is therefore a shared safety-critical boundary.

**Why report safe abstention separately from task success?** Abstaining on unavailable evidence is
safe, but abstaining when a bounded second attempt could recover evidence is still a task failure.
Combining them would make a system that refuses everything look artificially strong.

## Stage 3C.2 live-Hybrid answer anchors

**Did the Agentic lift survive on the real Hybrid retriever?** No. Both Direct and Agentic paths had
a 93.3% supported completion rate on the 15-query seed. Agentic added 13.3% Hybrid calls, about 39.8%
mean latency, and about 113% p95 latency without improving support coverage.

**Why did the controlled experiment improve but the live experiment did not?** Controlled cases
intentionally contain recoverable second-step evidence. The current Hybrid baseline already solves
14 of 15 live seed queries at top 3. The remaining accessibility request points to evidence absent
from the corpus, so rewriting cannot recover it. Capability and opportunity frequency are different
questions and need separate experiments.

**Why not simply retry more times?** More retries cannot retrieve facts that were never ingested.
They increase latency and load while creating more chances for irrelevant evidence to be accepted.
The correct fallback is bounded abstention plus a data-coverage signal for the ingestion pipeline.

**Is “no lift” a failed project result?** No. It prevents an unjustified Agentic claim and identifies
the actual bottleneck: corpus coverage and Grader quality. The next LLM policy must beat a strong
Direct Hybrid baseline under a frozen evaluation contract rather than merely making the graph more
complex.

## Stage 3D/3E DeepSeek answer anchors

**Why use direct HTTP instead of LangChain or the OpenAI SDK?** DeepSeek exposes an OpenAI-compatible
endpoint, and the project already depends on `httpx`. Three narrow JSON policy calls do not require a
larger abstraction. The provider remains behind a protocol, so changing SDKs does not affect graph or
domain code.

**Does JSON mode guarantee safe structured output?** No. It improves JSON syntax, but the response
may be empty or truncated and values can violate the domain contract. Every response therefore goes
through envelope checks, JSON parsing, Pydantic validation, and semantic consistency checks.

**What happens on timeout, rate limit, or invalid output?** Timeout and official transient statuses
429/500/503 retry once within the provider budget. Exhaustion or invalid output raises a sanitized
typed error; LangGraph records only the error type and uses the deterministic component.

**Why not switch all three policies to DeepSeek after integration succeeds?** Integration success is
not quality evidence. Router and Grader have separate accuracy/F1 gates and a fallback-rate ceiling.
Rewriter additionally needs trajectory recovery evidence. A mixed stack is expected if only one
component justifies its cost.

**What happened in the first real DeepSeek run?** Thinking was enabled by default while the Router
had a 220-token output cap. All 15 Router calls were rejected as truncated and the overall fallback
rate was 76.9%. Disabling thinking produced valid structured output for all 26 calls and cut mean
successful-call latency from about 2.55 seconds to below one second.

**What is the final Stage 3 policy selection?** Two repeated v3 runs gave Router test accuracy 1.000,
Grader test F1 0.667, and 0% fallback. The Router passed; the Grader only tied the deterministic
baseline and failed the lift gate; the Rewriter lacked real trajectory evidence. The selected
API-enabled profile is therefore LLM Router plus deterministic Grader and Rewriter.

**Can you put 100% Router accuracy on the resume?** Only with a strong pilot qualifier. It is five
test cases, project-authored, non-blind, and observed during prompt iteration. The honest claim is
that a versioned A/B and component gate selected the Router on the seed, followed by a plan for an
independently reviewed held-out set.

## Stage 4A/4B context-engineering answer anchors

**Why build a ContextTrace before optimizing prompts?** Without per-item token and admission traces,
token reduction cannot be attributed and missing evidence looks like a model failure. The trace
records decisions without copying sensitive prompt content.

**Why not use the model's maximum context window?** Maximum capacity is not a target. Larger context
increases input cost and distraction, and it can hide poor evidence selection. The project chooses a
task envelope through a recall-versus-token sweep.

**Why is 768 selected?** After removing full URLs and internal aspect labels from model-visible
metadata, 768 became the smallest configuration preserving all mandatory items and at least 0.9
mean relevant-document recall: 0.922 with 66.4% estimated-token reduction.

**Why not use `tiktoken` for exact counts?** DeepSeek tokenization is not guaranteed to match an
OpenAI tokenizer. A mismatched tokenizer gives false precision. Stage 4B uses a conservative named
heuristic, safety margin, and explicit degradation; provider usage will later calibrate it.

**What if mandatory context does not fit?** Fail before the model call and preserve the original
request. Silently truncating system instructions or hard constraints is a safety failure, not a
graceful degradation.

**What did fixed budgeting hurt?** Multi-constraint evidence coverage. Rank-order packing spends the
budget on the first few documents even when they duplicate one aspect. This measured loss motivates
Stage 4C coverage-aware packing rather than increasing the budget blindly.

## Stage 4C coverage-aware packing answer anchors

**What exactly is coverage-aware packing?** It is a deterministic marginal-utility selector. Each
candidate retains its retrieval priority and receives a bounded bonus for requested fact aspects it
would newly cover. The resulting order still goes through the same token cap, clip, and drop logic.

**How do you avoid evaluation-label leakage?** Requested aspects come only from the runtime query and
hard filters. Candidate aspects come from typed facts produced by ingestion. `expected_fact_types`
and relevance judgments are read only after selection to calculate metrics.

**Why not use MMR?** Embedding diversity measures semantic distance, not whether admission,
opening-hours, booking, route, and accessibility constraints are covered. MMR remains a possible
retrieval ablation, while this layer optimizes explicit travel-domain evidence coverage.

**Why not let an LLM choose the evidence?** An LLM selector may handle language better, but adds
latency, token cost, nondeterminism, and another failure boundary. The deterministic policy provides
a measurable baseline and can later serve as fallback for an LLM selector.

**Why is the coverage bonus bounded?** Pure coverage maximization can promote a low-ranked document
with broad or incorrect tags. Combining `retrieval_priority + 10 * marginal_gain` retains relevance
pressure; the per-case recall-regression count is the release gate.

**What improved?** At the selected 768 envelope, expected-aspect coverage rose from 0.967 to 1.000,
overall relevant-document recall from 0.922 to 0.944, and multi-constraint recall from 0.778 to
0.889, with one improved case and zero regressions.

## Stage 4F final-selection answer anchors

**Why should source URLs not be in the prompt?** The model cites stable document IDs; full URLs are
needed for provenance display, not reasoning. Rendering them consumed budget and caused useful
evidence to be clipped. Keeping them in typed metadata but outside the prompt reduced the selected
envelope from 1024 to 768.

**What was the final real A/B result?** On seven pilot cases, refined coverage improved task success,
required-fact coverage, citation precision/recall, and abstention accuracy from 0.857 to 1.000,
reduced fallback from 0.143 to zero, and cut total tokens from 6589 to 3605 (45.3%).

**Why did unbounded context fail more often?** More evidence encouraged longer structured answers;
one call exceeded the fixed output contract. The compact path focused the model on sufficient
evidence and had zero fallback. This is an observed pilot mechanism, not a universal causal claim.

**Did you tune the evaluation after seeing results?** Yes, and retained the audit trail. Early runs
found a citation-prefix mismatch and two over-specified reference requirements. The v1 labels and
v1-v3 reports remain stored; v4 is the corrected final pilot. Therefore the set is not blind and the
result must not be presented as held-out production performance.

**Why is citation precision not enough?** A model could cite only one safe claim and omit requested
facts. The gate therefore combines task success, fact coverage, citation precision, citation recall,
abstention accuracy, fallback rate, tokens, and latency.

**What if aspect inference or metadata fails?** With no usable aspect signal, marginal gains are zero
and ordering falls back exactly to retrieval priority. Mandatory preservation and tokenizer fallback
remain inherited from Stage 4B.

**Why report both aspect coverage and document recall?** Aspect coverage alone is gameable: an
irrelevant but broadly tagged document can score well. Recall alone misses duplicated fact types.
The two metrics protect different failure modes and must be interpreted together.

## Stage 4D evidence-refinement answer anchors

**Why deduplicate after retrieval instead of only in the index?** Multi-query retrieval and multiple
sources can return overlapping evidence even with a clean index. Runtime dedup saves prompt budget,
while index-time validation still prevents duplicate records from entering one snapshot.

**How do you stop near-duplicate matching from deleting different numbers?** Claims sharing a
`fact_key` but carrying different structured values bypass deduplication regardless of text
similarity. They are routed to conflict handling. A test specifically covers otherwise nearly
identical `17:00` and `18:00` sentences.

**Why doesn't the newest source always win?** Freshness cannot substitute for authority. The policy
first compares source authority, then uses a strictly newer observation only within equal authority.
A newly published travel blog cannot silently override an official operator.

**What if two official sources disagree and have equal timestamps?** Both claims are retained and the
trace marks `unresolved`. For opening time, booking, price, or feasibility, downstream generation
must expose uncertainty, refresh, or abstain rather than invent a winner.

**Why extractive compression instead of LLM summarization?** Extraction cannot introduce a new claim
and remains available during provider outages. It preserves original sentences, numbers, exceptions,
and provenance. LLM compression can later be evaluated for additional reduction and fluency.

**What did the controlled evaluation show?** All seven expected refinement decisions passed;
extractive compression preserved four of four deliberately late critical facts versus zero of four
for head truncation, while total estimated evidence tokens fell 42.4%. These are controlled stress
cases, not a natural-traffic production claim.

**What are the main limitations?** Lexical similarity misses paraphrases, conflict quality depends
on trustworthy metadata, and extractive text is less fluent. Each limitation defines a future
candidate component, while the deterministic implementation remains the fallback.

## Stage 4E memory-isolation answer anchors

**What is the difference between LangGraph state, a checkpointer, and user memory?** Graph state is
the data for one execution. A checkpointer persists it so an interrupted run can resume. User memory
supports future conversational context and preferences. They require different retention, access,
consent, schema migration, and deletion policies.

**How do you prevent one user's memory from reaching another user?** Every short-term operation
requires a validated `(tenant_id, user_id, thread_id)` tuple; preferences require `(tenant_id,
user_id)`. There is no global fallback lookup. Tests attempt cross-thread, cross-user, and
cross-tenant reads and measure a zero leakage rate.

**Why are preferences user-scoped but history thread-scoped?** A consented preference such as pace
can help across trips, while raw discussion about one trip should not silently enter another.
Current request values still override preferences.

**Why not automatically extract and save everything the user likes?** Inference can be wrong and
users may not expect persistence. The baseline requires explicit consent and allowlisted typed keys;
natural-language preference extraction is not yet implemented.

**What happens when Redis is unavailable?** Reads return an empty snapshot with a degradation flag,
so planning continues stateless. Writes return `persisted=false`. The system must never claim that
memory was saved. The current pilot proves this contract with an in-memory adapter; it does not claim
Redis network behavior has been tested.

**Why does deletion failure behave differently from read failure?** Stateless reads preserve safe
availability. If deletion fails, telling the user that data was forgotten would be false. Deletion
therefore raises a typed error and requires retry or operator remediation.

**How do retries avoid duplicate memory?** `turn_id` is an idempotency key. Replaying the same write
replaces that turn rather than appending a duplicate. Preference timestamps also prevent an older,
late-arriving event from overwriting a newer value.

**Why not use vector memory immediately?** The current long-term data is a small exact preference
map, where typed lookup, override, and deletion are more reliable. Semantic memory becomes useful for
large unstructured histories, but needs separate relevance, privacy, and deletion evaluation.

**What does the evaluation prove?** Fourteen controlled probes pass with zero cross-scope leakage and
1.0 lifecycle, privacy, and outage accuracy. It proves the reference semantics, not Redis ACLs,
distributed consistency, encryption, or production-scale concurrency.

## Stage 5A deterministic-constraint answer anchors

**Why not ask DeepSeek to validate the itinerary?** The model is useful for proposing and explaining,
but hard checks need exact, repeatable behavior. Cost arithmetic, interval comparison, closures, and
booking confirmation stay in deterministic Python, so the safety boundary also works during an LLM
outage.

**Why recompute total cost instead of checking `estimated_total_cost`?** That aggregate may be wrong
or model-generated. The validator sums activity line items plus explicit non-activity cost, reports
any mismatch, and compares the recomputed value with the budget. A fabricated low total therefore
cannot bypass the constraint.

**What does fail closed mean here?** Missing, unsourced, unknown, or stale availability does not
become “open.” The affected activity receives a distinct violation and must be refreshed, replaced,
or omitted. Other well-supported activities can still survive later partial repair.

**Why distinguish missing, unknown, stale, and closed?** Their recovery actions differ: fetch a
record, verify status, refresh it, or choose another place. One generic invalid code would make both
observability and local repair weaker.

**Why use timezone-aware datetimes and half-open intervals?** Aware timestamps avoid ambiguous
cross-zone comparison. Half-open intervals `[start, end)` allow one activity to end exactly when the
next starts while still catching real overlap.

**Why not introduce a constraint solver now?** Stage 5A validates one candidate and does not yet have
a global candidate graph or stable objective weights. Stage 5B first defines places, travel-time
edges, and explainable scoring; CP-SAT can then be evaluated against a greedy baseline rather than
added as architecture decoration.

**What did Stage 5A measure?** Ten versioned controlled scenarios reached 1.000 exact violation-set
accuracy, safety-case detection, and clean-case pass rate. The set is project-authored and tests
logic contracts only; it does not establish live-source freshness or production quality.

**What was the Stage 5A boundary?** At that checkpoint travel time was not yet validated, and
availability used fixtures rather than live adapters. Stage 5B subsequently added deterministic
travel feasibility; live availability and route adapters remain Stage 7 work.

## Stage 5B candidate-planning answer anchors

**Why build a greedy planner before CP-SAT?** It gives a cheap, deterministic, explainable baseline.
Without it, a solver adds architectural complexity but there is no evidence that global optimization
improves the actual scenarios. The same dataset can later measure feasibility, utility, latency, and
fallback differences.

**Does the greedy planner guarantee the best itinerary?** No. It chooses the highest-utility feasible
next activity, so an early choice can block a better later combination. The project explicitly calls
it a baseline and retains this limitation rather than describing heuristic output as optimal.

**How is the score explainable?** Every selection stores separate required-place, retrieval,
interest-match, travel-penalty, and cost-penalty components. The user-facing explanation can use
those fields without exposing hidden chain-of-thought.

**Why does a required place get a large bonus instead of only being validated at the end?** End-only
validation would often waste limited day capacity on optional places. The bounded `1000` bonus makes
required places dominate within known component ranges, while the validator still independently
detects an unscheduled required place.

**Why are travel edges directed?** A-to-B and B-to-A may differ because of transfers, one-way routes,
entrances, or traffic. Treating the matrix as symmetric can manufacture feasibility.

**How do transfer buffers work?** The scheduler and validator both add the same configurable minimum
buffer to sourced travel duration. A plan cannot pass merely because two timestamps leave exactly
the optimistic API estimate between them.

**What if the outbound route exists but the return route does not?** The candidate is skipped. Stage
5B checks that the traveler can return to the day's origin before admitting an activity, and records
`return_travel_unavailable` rather than stranding the plan.

**What if the map API fails?** Missing, unknown, unsourced, or stale travel edges are not converted
to zero minutes. The affected candidate is skipped; the deterministic trace exposes the dependency
failure. A future adapter may use a fresh cached value under a documented TTL, but not an unbounded
stale estimate.

**What did Stage 5B measure?** Five controlled scenarios reached 1.000 expected-outcome exact match,
1.000 unsafe-admission-free rate, and 1.000 decision-trace coverage. These prove fixture behavior,
not route quality on live traffic or global optimality.

## Stage 5C bounded-repair answer anchors

**Why local repair instead of regenerating the whole itinerary?** Most violations have a small blast
radius. Recomputing a total, removing one excluded activity, or replanning one closed day preserves
valid user choices, reduces provider calls, and avoids introducing failures into safe days.

**How does the system decide repair scope?** It maps machine-readable violation codes to explicit
actions. Global arithmetic gets an arithmetic fix, exclusions and budget get targeted removals, and
operational or travel failures replan their tagged day. Unsupported structural violations do not
enter the retry loop.

**Why use LangGraph for repair instead of a Python `while` loop?** The value is explicit state and
bounded transitions, not visual decoration. Attempts, violations, modified days, fallback use, and
node outcomes become checkpointable and auditable. A simple loop remains possible, but would have
to rebuild those semantics as the workflow expands.

**Who decides whether repair succeeded?** The independent deterministic validator. Neither an LLM
nor the repair policy can mark its own candidate valid; every change returns to the validation node.

**What prevents an infinite reflection loop?** `max_repair_attempts` defaults to two and must be
positive. After exhaustion the graph returns `failed` with the remaining violations. A violation
with no registered safe repair strategy fails immediately with zero repair calls.

**What if an LLM repairer times out?** The interface is injected, so exceptions activate the
deterministic day repairer. State records only component and exception type. The controlled outage
case recovered successfully without including the provider payload in the trace.

**How do you prove unaffected days stayed unchanged?** The evaluation snapshots the typed second day
of a two-day trip, repairs a closure on day one, and compares the serialized result. Preservation was
1.000 on the controlled probe. This is a narrow contract test, not a production distribution claim.

**Can the modification metric be gamed by attempted no-op repairs?** No. A day enters
`modified_days` only if the before and after typed serialization differs. The impossible repair case
uses two attempts but correctly reports no modified day.

**What did Stage 5C measure?** Seven controlled cases reached 1.000 exact expected outcome,
repairable-case success, safe-failure accuracy, unaffected-day preservation, and outage recovery.
Mean repair attempts were 0.857 because valid and unsupported cases correctly avoided work.

**What remained at the Stage 5C boundary?** A real LLM candidate and the full retrieval-to-plan
pipeline had not yet been compared. Stage 5D subsequently evaluated quality, token cost, latency,
fallback rate, and regression cases on the same versioned set.

## Stage 5D end-to-end and planner-selection answer anchors

**What does the complete planning path now include?** Real local Hybrid RRF retrieval, typed evidence
enrichment, the selected 768-token refined context, a provenance-linked candidate plane, candidate
planning, independent hard validation, and bounded local repair.

**Why did the first end-to-end baseline fall to 0.8 task success?** It treated the Stage 4 QA prompt
as the only candidate source. The 768 envelope packed two documents and removed valid multi-day
candidates before the planner saw them. The planner cannot recover an upstream omission.

**How did you fix that without returning to unbounded context?** Raw narrative text remains bounded,
while a separate structured candidate plane retains every retrieved place-linked record and its
provenance. The model sees compact typed candidate fields; deterministic scheduling sees the same
grounded candidates. Offline success returned to 1.0 without increasing the narrative envelope.

**Is the candidate plane a way to bypass RAG grounding?** No. A catalog entry is eligible only when
retrieval produced place-linked evidence, and activities retain those evidence IDs. It separates
representation from provenance; it does not allow invented places.

**Why did DeepSeek v1 fall back 80% of the time?** The interface demanded a complete permutation,
but four outputs were sensible shortlists. Diagnostics showed missing known IDs but zero unknown IDs
and no schema failures. The contract disagreed with the task semantics.

**What was wrong with the first telemetry?** Post-provider schema failures discarded the successful
response usage, undercounting total tokens as 843. The corrected diagnostic run retained usage for
invalid outputs and measured 4443 tokens. Failed output validation still costs money and latency.

**How did v2 reduce fallback without weakening safety?** It accepts a nonempty shortlist containing
only unique known IDs. Omitted candidates are appended by deterministic retrieval order; duplicates
or unknown IDs still activate fallback. Hard feasibility never moved into the LLM.

**Why was DeepSeek still rejected after fallback reached zero?** Its final place sequences were
identical to the deterministic baseline: task and hard metrics tied, expected-place hit rate tied at
0.933, and lift was zero. It added 4475 tokens and about 877 ms per call, so it failed the frozen
minimum-lift gate.

**Why add expected-place precision after the run?** Recall alone can reward stuffing extra places.
Precision exposed that issue, but it is explicitly post-hoc and cannot be presented as a predeclared
selection gate. It was 0.850 for both variants and did not change the rejection.

**Can you claim the deterministic planner is generally better than DeepSeek?** No. The honest claim
is that DeepSeek did not justify selection on five project-authored, non-blind pilot cases. A harder,
independently reviewed soft-preference set may produce a different result.

## Stage 6A/6B evaluation-governance answer anchors

**Why is there a test split if it is not blind?** The split still prevents routine prompt and
parameter tuning against every case, but it does not eliminate author exposure or label bias. The
manifest therefore reports `test_is_blind: false`; it is regression plumbing, not benchmark proof.

**What is the difference between frozen, held-out, independently reviewed, and blind?** Frozen means
the rows do not change during a comparison. Held-out means they are not used for fitting or tuning.
Independent review means someone other than the author checked the labels. Blind additionally means
the developer did not see the evaluation cases before freezing the system. These properties are not
interchangeable.

**Why separate the governance manifest from the task dataset?** Split and review metadata can evolve
without pretending the task labels changed. The report hashes both artifacts, so a changed label or
a changed governance claim remains detectable and attributable.

**How is data leakage checked?** The validator rejects duplicate case IDs and cross-split collisions
of normalized query text or a deterministic scenario fingerprint built from constraints and expected
places. Semantic near-duplicate detection remains future work and should be manually reviewed.

**Why use multiple error codes instead of one root cause?** A retrieval miss can cause empty context,
no candidates, and eventual task failure. One forced label destroys propagation evidence. The audit
stores observable symptoms; a human uses traces to decide causality.

**Why can task success be 1.0 while the error audit still finds issues?** The task gate only requires
a valid plan and a minimum number of expected hits. The audit additionally shows partial expected
coverage and extra selections. This prevents a coarse success threshold from hiding optimization
opportunities.

**Is `unexpected_selection` a real model error?** Not necessarily. The expected-place list is not
exhaustive, so an extra recommendation may be useful. It is a diagnostic signal for review, not an
automatic correctness failure or selection gate.

**Why not start Stage 6 with LLM-as-Judge?** Without human calibration, judge scores add another model
opinion rather than ground truth. Exact constraints, fallback, schema, provenance, cost, and latency
stay deterministic; a judge is reserved for subjective qualities after rubric labels exist.

**What did the first governed audit reveal?** Both deterministic and DeepSeek variants kept 1.0 task
and constraint success on the 3/2 split. Test expected-place hit rate was 0.833, and both variants had
the same two extra-selection and one partial-coverage diagnostics. It reinforces that DeepSeek added
cost without measured differentiation on this pilot.

## Stage 6C Judge-calibration answer anchors

**Why not replace exact metrics with LLM-as-Judge?** A Judge is useful for clarity, actionability,
coherence, and nuanced preference fit. It is weaker than code for budget arithmetic, time overlap,
schema validity, citation identity, fallback, tokens, and latency, so those remain deterministic.

**How do you prevent self-evaluation bias?** The Judge does not receive source variant or model
identity, and its output is compared with human rubric labels rather than accepted as truth. A future
stronger study should also use independent annotators and a judge model family different from the
candidate model family.

**Why call the Judge three times at temperature zero?** Provider and model execution can still vary.
Repeats expose instability. They are aggregated once per candidate for human agreement metrics and
therefore do not falsely increase the number of independent examples.

**Why use weighted kappa as well as MAE?** MAE measures distance but ignores agreement expected by
chance. Quadratic-weighted kappa fits ordered 1–5 scores and penalizes a four-point miss more than a
one-point miss. Within-one agreement remains easier to interpret, so the gate requires all three.

**What if the Judge fails its gate?** Its scores are excluded from release decisions; deterministic
metrics continue working. The failed report is retained for prompt/rubric error analysis rather than
silently adjusting thresholds on the test set.

**What is the current Stage 6C result?** A 21-call reference-only run completed with zero fallback and
0.857 repeat consistency, but all four dimensions failed agreement/kappa gates. Reference labels are
AI-assisted rather than human-verified, and the Judge lacked evidence text. Judge v1 is rejected; v2
needs evidence-aware quality-stratified development data and a separate held-out set.

**Why did the Judge fail despite stable structured output?** Schema validity measures interface
reliability, not scoring validity. It repeatedly misunderstood the single-choice accessibility query
and once changed a correct inner-garden answer from all 5s to all 1s while claiming an explicitly
present exception was missing. Agreement metrics exposed errors that JSON validation could not.

**Why not improve the prompt and rerun these seven cases until it passes?** That would tune on the
calibration test and convert the gate into a target. The v1 failures guide a new development set; the
next claim must be evaluated once on separately frozen held-out examples.

## Stage 6D regression-gate answer anchors

**Why is the gate profile separate from code?** A candidate implementation should not quietly relax
its own acceptance criteria. The versioned profile pins the exact baseline audit hash, so changing
the baseline or threshold becomes a visible review decision.

**Why check development and test independently?** An aggregate can improve by winning on tuned cases
while regressing on the frozen partition. Both splits must preserve task, validity, constraint,
required-place, and expected-place metrics.

**Why does a paid component need positive lift if it does not regress?** Tokens and latency are not
free, and the provider adds timeout, rate-limit, schema, privacy, and availability risks. Equal output
quality is therefore negative system value unless another predeclared benefit is demonstrated.

**Why is expected-place precision excluded?** It was added post-hoc and the expected set is not
exhaustive. Promoting it into a frozen gate after seeing results would be metric selection leakage.

**What happens in CI when a gate fails?** The command still writes a complete diagnostic report, then
exits with status 1. Engineers can inspect every expected and actual value; rejection is not hidden as
an infrastructure crash.

**What did Stage 6D measure?** The deterministic variant passed 17/17 checks. DeepSeek passed safety,
quality floors, fallback, token, and latency ceilings but failed the paid-lift check: 895 tokens per
case, about 877 ms mean provider latency, and zero expected-place hit-rate lift.

## Stage 7A observability answer anchors

**Why not log the prompt and response for debugging?** They can contain personal preferences,
locations, credentials accidentally pasted by users, copyrighted evidence, and provider payloads.
The trace stores counts, reason codes, timing, model-safe error types, dataset IDs, and hashes; raw
content needs a separate opt-in, access-controlled retention policy.

**How do you correlate one request across components?** A generated 32-hex trace ID enters every
pipeline event and the final typed result. Monotonic sequence numbers expose locally missing or
reordered events. This correlation ID is not reused as an authentication or idempotency key.

**What happens if the telemetry backend is down?** Sink exceptions are swallowed at the telemetry
boundary, not by business components. Planning continues, but `telemetry_degraded=true` prevents the
run from being described as fully healthy. Export outage should have a separate local counter/alert.

**Why use an attribute allowlist instead of a denylist?** New sensitive fields are easy to forget in
a denylist. With an allowlist, unknown attributes are dropped by default and a drop count signals
instrumentation mismatch without persisting the value.

**Why not integrate LangSmith or OpenTelemetry directly?** Their exporters are useful, but the domain
contract should not depend on one vendor. An injected sink allows an OTLP, LangSmith, local JSON, or
test adapter while keeping redaction semantics consistent.

**What did the Stage 7A drill prove?** Three injected scenarios achieved 1.0 business completion,
zero canary leakage, 1.0 available-sink trace integrity, 1.0 telemetry-outage survival, and 1.0
retrieval-fallback visibility. It proves the contract on fixtures, not remote delivery or SLO scale.

## Stage 7B resilience answer anchors

**Why is retry not enough?** Retry assumes a fault is short. During a sustained outage, every request
repeats load and waits for the same failure. The circuit breaker opens after a bounded threshold,
rejects calls quickly, and permits one half-open recovery probe after a cooldown.

**Which errors open the circuit?** Only configured transient provider-health failures such as timeout
and connection errors. Authentication, invalid request, schema validation, and other request-specific
failures should be surfaced and fixed; counting them as outage signals can open the circuit incorrectly.

**Why allow one half-open probe?** Letting all waiting traffic retry simultaneously creates a thundering
herd. One probe tests recovery; success closes and resets the circuit, while failure reopens it.

**When can stale cache be used?** Any configured evidence can be served inside its fresh TTL during a
dependency fault. After that, only explicitly allowlisted static evidence is admitted until a hard
maximum age. Dynamic opening, booking, price, weather, and route facts fail closed.

**Why hash query cache keys?** Raw queries can contain personal plans or pasted secrets and are unsafe
as Redis keys or metrics labels. A canonicalized SHA-256 key supports lookup without exposing text.
Hashing is pseudonymization, not encryption; cached values still need access controls.

**Does a circuit breaker enforce timeout?** No. It decides whether a call may begin and reacts after a
failure. A stuck call still needs provider-native connect/read/pool/total deadlines; Python thread
cancellation is not a reliable substitute.

**Should circuit state be global?** Not automatically. A process-local breaker may send too many total
probes across replicas; a global breaker can let one tenant or region suppress healthy traffic for
others. Scope must match the dependency, tenant isolation, and failure domain.

**What did Stage 7B prove?** Eight controlled transitions passed, including fast-fail provider-call
avoidance, stale dynamic rejection, bounded static availability, and half-open recovery. The test uses
an in-memory cache and injected timeouts, so it does not claim Redis or network behavior.

## Stage 7C checkpoint/idempotency answer anchors

**What does LangGraph checkpointing solve?** It persists observed graph state and the next runnable
node under a thread identity. After interruption following `generate`, the rebuilt graph resumed at
`validate`; it did not repeat already-checkpointed retrieval or Planner work.

**Why does checkpointing not guarantee exactly once?** A process can die after an external provider
accepted a call but before the graph saves its next checkpoint. On recovery, the node may run again.
Exactly once requires provider-side idempotency or a transaction covering both effect and receipt;
the project claims bounded deduplication, not an impossible guarantee.

**What does the idempotency key contain?** A hash over tenant/user/thread scope, operation name,
Planner version, normalized request payload, evidence IDs, and evidence content hashes. Changing
scope, input, evidence content, or implementation version creates a different operation identity.

**Why include evidence content hashes instead of only IDs?** A source correction can retain an ID.
Replaying the old result after evidence changed would be stale and incorrect, so content participates
without putting raw evidence in the stored key.

**What happens to concurrent duplicates?** The first caller owns an in-progress receipt. Another
caller with the same key is rejected rather than starting the side effect again. A production store
needs an atomic unique constraint/lease and a recovery policy for abandoned in-progress receipts.

**Why use a serializer allowlist?** Checkpoint deserialization reconstructs Python objects. Explicitly
allowing only TravelMind state types is safer and more future-proof than accepting all modules. Tests
run with `LANGGRAPH_STRICT_MSGPACK=true` so compatibility warnings cannot hide future failure.

**Are thread ID, trace ID, and idempotency key the same?** No. Thread ID locates workflow state, trace
ID correlates one execution's telemetry, and idempotency key identifies one retryable operation.
Reusing one value for all three creates incorrect retention, authorization, and deduplication scope.

**What did Stage 7C prove and not prove?** Six logical checks passed, including rebuilt-graph resume,
one Planner call, receipt replay, and checkpoint-outage safe failure. InMemorySaver does not survive
OS process loss. Stage 7C.2 subsequently added a SQLite cross-process proof; distributed production
recovery still requires PostgreSQL.

## Stage 7C.2 durable persistence answer anchors

**Why SQLite before PostgreSQL?** SQLite proves real process-boundary persistence with deterministic,
service-free tests. LangGraph officially positions it for lightweight synchronous/local use and
PostgresSaver for production workloads. The graph keeps an injected saver, so this is a development
adapter rather than an architectural dead end.

**How did you prove cross-process recovery?** One Python process ran through `generate`, committed the
checkpoint, and exited. A second process opened the same database, resumed at `validate`, completed,
and reported zero Planner calls. The receipt test similarly used two separate processes.

**How is the SQLite receipt claimed atomically?** `BEGIN IMMEDIATE` serializes the claim transaction,
and `receipt_key` is a primary key. The row stores status, owner, and acquisition time. Only that
owner can commit the completed result.

**What happens to an abandoned in-progress receipt?** It is not automatically stolen after expiry,
because the external operation might have succeeded before the crash. The store raises a typed
reconciliation error. An operator or provider-specific recovery workflow decides whether replay is
safe.

**Why WAL mode and a busy timeout?** WAL improves local reader/writer behavior, while the five-second
busy timeout bounds lock waiting. Neither makes SQLite appropriate for high-concurrency multi-instance
production.

**Why is checkpointing an optional dependency?** Core deterministic tests and agent execution do not
need a disk saver. The `checkpoint` extra makes the operational dependency explicit and keeps missing
installation errors actionable. Production would use a different PostgreSQL extra/adapter.

**What did Stage 7C.2 measure?** Six cross-process/file checks passed. Resume and receipt replay both
used zero Planner calls in the second process, and both database files were mode `0600`. This does not
measure concurrent throughput, disk corruption recovery, or PostgreSQL behavior.

## Stage 7D SLO and composite-outage answer anchors

**Why is the Stage 7D result not a production SLO?** It uses one local injected sample per scenario,
not a service observation window or representative traffic population. It is a synthetic pre-release
gate for fallback composition, visibility, safe failure, redaction, and gross latency regressions.

**Why test simultaneous failures?** Components that degrade correctly alone can interact badly. A
model fallback might run after retrieval fallback while the telemetry sink is unavailable, hiding the
actual state. The composite case proves the user path completes and all three degradation signals are
present in the returned typed result.

**Why not count degraded completion as healthy availability?** It masks chronic outages and may spend
more latency, use older evidence, or reduce recommendation quality. Healthy, degraded, and failed
requests need separate SLIs and budgets even when both healthy and degraded requests return answers.

**When should the agent fail instead of fallback?** When no admissible evidence path remains or a hard
constraint cannot be verified. In the dual-retrieval outage, returning an itinerary would trade an
availability failure for unsupported recommendations, so the pipeline returns no itinerary and a
stable failure reason.

**What did Stage 7D prove?** Seven deterministic checks passed: healthy completion, recoverable
three-component outage completion, full degradation visibility, dual-retrieval safe failure, two
broad local latency gates, and zero canary exposure. It did not prove production percentiles,
capacity, network-partition behavior, or a real error budget.

## Stage 8A versioned-ingestion answer anchors

**Why retain raw snapshots after parsing?** Parser behavior and schemas change. Immutable raw input
plus its content hash lets us reproduce derived facts, compare parser versions, investigate bad
answers, and re-index without refetching an already changed source.

**Why hash content instead of using URL as identity?** One URL can return different content over time,
while mirrors can return identical bytes. Content addressing deduplicates the latter and creates a new
version for the former. Source URL and fetch time remain provenance, not version identity.

**Why not write directly into the active index?** A crash or validation failure would expose a mixed
generation. The project builds outside the serving path, validates the whole candidate, stores it as
an immutable version, and then switches one pointer.

**Is `os.replace` enough for production atomicity?** Only for a rename on the same filesystem. Remote
vector stores need versioned collections plus an alias/metadata swap with conditional concurrency;
cross-system publication may require an orchestration state machine and reconciliation.

**What happens when validation fails?** The build is moved to quarantine, a typed sanitized error is
raised, and `CURRENT` still names the previous complete build. Bad data cannot become active merely
because part of the pipeline succeeded.

**How does rollback work?** It verifies that the target immutable build has a manifest, then atomically
changes the pointer. It does not refetch, reparse, or re-embed during the incident, keeping recovery
fast and avoiding the code path that may have caused the bad release.

**How do you handle pointer tampering or disk corruption?** Build IDs must be exact SHA-256 digests
before path resolution, preventing traversal through the control file or rollback API. Serving then
hashes `records.jsonl` and compares it with the immutable manifest; a mismatch fails closed instead of
silently feeding corrupted evidence to the agent.

**What did Stage 8A prove?** Seven local lifecycle checks passed, including snapshot deduplication,
changed-content versioning, quarantine, previous-index preservation, promotion, rollback, and
owner-only control files. It did not prove object-store consistency or vector-database alias behavior.

## Stage 8B conditional-fetch answer anchors

**Why use both ETag and Last-Modified?** They let the source validate an existing representation with
a small `304` response. ETag is usually the stronger entity validator; Last-Modified is a widely
supported fallback. A `304` updates validation time but retains the original content bytes.

**Which failures are retried?** Bounded transport failures, `429`, and `5xx`. Authentication,
authorization, invalid URL/content, redirects, and most other `4xx` responses are not transient;
retry would waste capacity and hide a configuration or contract bug.

**Why cap Retry-After and exponential backoff?** The worker has its own latency budget. An unbounded
server value can occupy it indefinitely, while uncapped exponential delay makes recovery time
unpredictable. Production should also add jitter and shared rate-limit coordination.

**Why can static cache be used longer than dynamic cache?** A historical description often remains
useful during a short outage; yesterday's opening or booking state can invalidate the trip. Typed
policy admits stale static evidence only to a hard age and rejects dynamic evidence after fresh TTL.

**Does the host allowlist completely solve SSRF?** No. It blocks arbitrary schemes, hosts,
credentials, ports, and redirects before transport, but an allowed hostname could resolve to a
private address or change between checks. Production needs resolution-time IP validation and
DNS-rebinding protection at the egress layer.

**Why inject a transport instead of mocking HTTPX everywhere?** The policy state machine can be tested
against scripted outcomes while HTTPX remains a thin adapter. Retry, freshness, and security behavior
stay independent of the HTTP library's internals.

**What did Stage 8B prove?** Eight controlled checks passed, including conditional headers and `304`,
bounded third-attempt recovery, dynamic-stale rejection, static-stale fallback, URL blocking before
transport, and payload redaction. It did not contact a live source or prove DNS/network policy.

## Stage 8C typed incremental-ingestion answer anchors

**Why is a valid JSON object still untrusted?** JSON syntax says nothing about domain correctness. A
fact can reference the wrong document/place, reuse another fact ID, carry an invalid time range, or
claim a different source URL. Pydantic plus cross-record validation defines the ingestion boundary.

**What is stored when parsing fails?** Only snapshot hash, parser version, and exception type in an
owner-only quarantine receipt. The immutable raw snapshot supports debugging, while parser exception
messages and source content are kept out of routine diagnostics.

**Why must the semantic conflict key exclude value?** If `30 CNY` and `35 CNY` produce different keys,
they never meet and the conflict is invisible. The key includes place, type, unit, qualifiers, and
validity interval; value and source identify the competing candidates inside that group.

**Why group equivalent values before comparing precedence?** Without grouping, two strong sources
that agree can occupy the first two sorted positions and hide a different weaker value. This bug was
found by a failing test and fixed by comparing the strongest representative of each distinct value.

**Can a newer third-party value beat older official data?** Not under authority-first reconciliation,
but stale official data should already have been removed by Stage 8B. This separation keeps freshness
admission deterministic. Authority order still needs fact-class review and policy versioning.

**Why exclude unresolved facts instead of returning both?** Hard planning constraints cannot safely
pick between equal-precedence conflicting values. The fact index suppresses the value; the next
production step should propagate an uncertainty/abstention reason to the answer layer.

**How is an incremental update atomic?** It copies documents, facts, and resolutions, replaces one
source inside the copies, recomputes only the union of old/new semantic keys, and swaps state after all
checks succeed. A collision or resolver failure leaves the live dictionaries unchanged.

**What did Stage 8C prove?** Eight integrated checks and twelve focused tests passed. The update
changed one of two keys, giving a 0.5 recompute ratio; quarantine, conflict behavior, no-op detection,
and failed-update preservation were exact. It is not a remote vector-index concurrency claim.

## Stage 9A interview-release answer anchors

**Why create a release manifest instead of citing whichever report looks best?** The manifest binds a
named release to exact code-lock, architecture, decision, and evaluation artifacts with SHA-256. A
later edit or accidental report replacement fails the audit, so an interview claim remains tied to
the evidence that originally supported it.

**What does the automated release audit check beyond file hashes?** It checks 18 semantic invariants:
the package version and secret-ignore policy; selected Router, context, and Planner decisions; the
Hybrid RRF quality threshold; explicit rejection of the reranker, paid Planner, and Judge v1; and
successful durability, outage, and incremental-ingestion drills. A present but contradictory report
therefore cannot pass merely because its hash was pinned.

**Why preserve negative experiments in the release?** Rejected reranking, Planner, and Judge runs
show that selection was gate-driven rather than technology-driven. They also provide useful failure
analysis: added model complexity may reduce recall, add tokens without quality lift, or be too
unstable to automate evaluation.

**What is the fallback if a pinned file changes intentionally?** First rerun the relevant evaluation
and review the semantic decision. Then create a new release manifest or version; do not silently
replace the old digest. The old manifest remains reproducible evidence for the old claim.

**Why is the interview demo offline?** Reliability and cost are part of the demonstration. The script
uses the selected deterministic workflow and locally recorded evidence, then exercises composite
dependency failure, atomic index publication, typed incremental ingestion, and release auditing. Real
DeepSeek experiments remain reproducible separately but are not required for a five-minute demo.

**What does Stage 9A not prove?** It does not turn a small project-authored dataset into a production
or statistically significant benchmark. It proves artifact integrity, internal claim consistency,
and reproducible pilot behavior; independent labels, production traffic, capacity testing, and a
human-calibrated Judge remain outside the claim boundary.

## Stage 9B resume and narrative answer anchors

**How were the resume bullets selected?** Each bullet represents a different engineering dimension:
Agent control flow, retrieval, context efficiency, evaluation-based model selection, or resilience.
Every number maps to a frozen JSON report, and every small-sample number carries its experiment scope.

**Why put rejected experiments on a resume?** The project's strongest signal is not that it contains
many model calls; it is that components must prove incremental value. Rejecting a fashionable
reranker or paid Planner after controlled A/B testing demonstrates evaluation judgment, latency and
cost awareness, and the ability to preserve negative evidence.

**How should the project be introduced before discussing implementation?** Start with the reliability
problem: a travel answer must be evidence-grounded, constraint-valid, and safe under dependency
failure. Then explain how the architecture and evaluation system enforce those properties. Listing
framework names first makes the project sound assembled rather than designed.

**What should be said if challenged on the small sample size?** Agree with the factual boundary and
separate two claims. The experiments are sufficient to select the current pilot defaults and test the
evaluation plumbing; they are insufficient for population-level accuracy or production SLO claims.
The next step is independently authored labels, hard negatives, abstention cases, confidence
intervals, and a production observation window.

## Stage 10A governed-PDF answer anchors

**Why is PDF ingestion more than installing a parser?** A PDF is untrusted binary input obtained over
the network. Source authorization, bounded download, payload admission, immutable versioning, parser
isolation, and index promotion are separate boundaries. Parser quality matters only after unsafe or
partial bytes have been prevented from entering it.

**Why check MIME, magic, and EOF together?** MIME rejects an unexpected declared type, magic detects a
spoofed non-PDF body, and EOF detects the common partial-transfer case that still begins with a valid
PDF header. None alone proves that the document is structurally valid.

**Does scanning for `/JavaScript` make a PDF safe?** No. It is a conservative admission rule, not a
malware scanner or full object-graph analysis. Stage 10B must parse in a resource-constrained process,
reject encryption and unsupported objects, enforce page/time budgets, and quarantine failures.

**Why are raw official PDFs excluded from Git?** The repository owns source metadata, parsers, tests,
and derived evaluation evidence, not the publisher's binary. Downloading from the official URL and
recording an immutable content hash preserves provenance while avoiding repository bloat and unclear
redistribution claims.

**What happens when an official server has TLS or throughput problems?** Certificate verification is
not weakened and the operation remains bounded. No complete payload means no snapshot or index build;
the current validated index remains active. A partial development download is quarantined as an
operational observation, not treated as knowledge.

**Should an old brochure override a new ticket rule?** No. PDF brochures are admitted for static
culture, route, and visitor-guide context. Dynamic prices, opening hours, bookings, and closures come
from fresher official pages, with fact-type-specific conflict resolution before index publication.

**What did Stage 10A prove?** Four official sources pass registry governance and ten controlled
admission/snapshot checks pass with zero rejected-payload admission. It did not prove layout parsing,
OCR, page citation, or retrieval improvement; those remain explicit Stage 10B–10D gates.

## Stage 11 agentic-runtime answer anchors

**Why was the old graph not sufficiently agentic?** It had bounded retrieval rewrite and output
repair, but the execution strategy was wired into the graph. There was no explicit plan, external
action observation, or replacement of future steps. Stage 11 adds a versioned plan and makes a real
revision after execution feedback.

**What is the difference between retry, repair, and replan?** Retry repeats the same action after a
transient fault. Repair changes an invalid output while keeping the strategy. Replan changes the
remaining strategy after an observation invalidates the original plan. The trace and counters keep
the three mechanisms distinct.

**If a booking API times out, why not immediately replan?** A bounded retry is cheaper and preserves
the intended plan for a likely transient failure. Authentication rejection, unsupported operation,
or invalid response schema is not retried blindly; it triggers replan or safe stop.

**How do you detect hallucinations?** I avoid claiming a universal hallucination detector. The
deterministic boundary catches fabricated evidence IDs, unknown place IDs, absent provenance, and
recomputed constraint errors. Semantic entailment of free-form prose remains a separately evaluated,
fallible judge task.

**How do you distinguish retrieval error from generation error?** Attribute at the earliest observed
contract boundary. Empty/failed/unusable retrieved evidence is retrieval-layer; a generator that had
admissible evidence but emits unknown entities or citations is generation-layer. If both contributed,
record one primary boundary and the other as a contributor instead of pretending root cause is
certain.

**How do you prevent an infinite agent loop?** Bound attempts per tool step, plan revisions, and total
tool calls. Validate plan dependencies before execution. When a bound is exhausted, fail closed with
the latest typed attribution and no unsupported itinerary.

**Why not let the LLM decide every recovery action?** LLM planning is injectable, but termination,
error classification, budgets, provenance admission, and hard constraints remain deterministic.
This keeps creativity in strategy selection while protecting safety and reproducibility.

**Can you show a genuinely multi-step replan rather than a retry?** Revision 1 searches candidates,
checks the primary attraction's availability and booking, then requests travel time. If booking or
travel fails after earlier success, revision 2 switches to the alternative attraction and contains
only its availability and travel steps. The trace shows `[1, 2]`, while candidate-search call count
stays at one.

**How are completed actions preserved across plan revisions?** Successful calls are immutable typed
observations in graph state, independent of the current plan object. The replanner receives the full
observation history, and itinerary generation converts successful observations from all revisions
into realtime evidence. Failed observations never enter planner evidence.

**Can a replanner quietly change what the user asked for?** No. Runtime validation requires stable
plan identity, monotonically increasing revision, and an unchanged goal. Hard travel constraints
remain in the original `TravelRequest` and are recomputed against the final itinerary. A plan that
changes the goal is classified as an orchestration failure.

**Did the real DeepSeek replanner beat the deterministic planner?** No. After safe canonicalization,
it matched the four-case contract and fallback was zero, but measured lift was zero, it consumed 5725
tokens with about 1.08 seconds mean latency, and 42.9% of calls needed argument normalization. It
failed the 25% normalization and positive-value gates, so deterministic remains selected.

**Why did DeepSeek generate invalid tool arguments even at temperature zero?** The model inferred
reasonable semantic fields such as interests, destination, and date, but those fields were absent
from the actual tool schema. Temperature zero reduces sampling variance; it does not guarantee exact
function signatures or deterministic provider behavior.

**Why canonicalize arguments instead of accepting or rejecting them?** Query and origin are
runtime-owned values, so restoring them is deterministic and safer than forwarding model text. Extra
date fields can be removed when the tool contract does not accept them. The plan remains usable, but
normalization is counted so the correction cannot be mistaken for strict model success.

**How did you avoid a misleading 100% success claim?** I report final fallback-inclusive completion,
accepted model plans, strict plans, normalization rate, fallback rate, post-provider validation
failures, latency, tokens, and contract lift separately. In the first run, final recovery was 100%
even though every model plan failed; that is fallback quality, not model quality.

**Why create a v2 release instead of editing the v1 manifest?** A hash-pinned release should be
immutable. Rewriting v1 evidence would erase what the earlier 33-check claim actually referred to.
V2 retains those 15 files, adds six Agentic Runtime artifacts, and evaluates 21 hashes plus 25
semantic invariants. Both historical claims remain reproducible.

**What do the 46 release checks prove?** They prove artifact integrity and internal consistency:
selected components match reports, rejected candidates stay rejected, and runtime recovery/safe-stop
claims match frozen evidence. They do not add statistical power to four project-authored cases or
turn fixture tools into live booking reliability evidence.

**How do you demo replanning without spending API tokens?** The interview script injects booking and
travel failures into deterministic fixture tools, then prints the multi-step runtime metrics and runs the v2
release audit. The previously captured DeepSeek report is hash-checked rather than replayed. If asked
about the model, I open its per-call telemetry and explain why the selection gate rejected it.

## Stage 12 expanded-evaluation answer anchors

**Did increasing from 15 to 105 queries make the metric trustworthy?** It improved diagnostic
coverage but did not create independent ground truth. The 105 queries represent 35 intent clusters
with three correlated paraphrases each, so I report both counts and bootstrap over intent clusters.
All labels remain Codex-authored and `reviewed=false`; metric promotion is blocked until a person
checks them.

**How did you prevent paraphrase leakage?** Every row has an `intent_id`, and all three paraphrases
must remain in one split. Dataset validation rejects an intent appearing in both development and test,
incomplete paraphrase groups, duplicate text, and inconsistent labels inside a cluster.

**Why did the test Recall@5 reach 1.000, and can you put it on the resume?** Not yet. The corpus has
only 14 documents and the draft labels were written against that corpus, so the retrieval task is
still relatively closed and author bias is likely. I report overall Hybrid Recall@5 0.971 and the
intent-cluster interval, but neither becomes a reviewed benchmark claim until independent validation.

**What did the no-answer cases reveal?** BM25, Dense, Hybrid, and Reranked retrieval always returned
some ranking, giving raw abstention accuracy 0. A ranker answers “which item is nearest,” not “is any
item sufficient.” This exposed a missing evidence-admission boundary that the original positive-only
set could not detect.

**Why not threshold the RRF score?** RRF scores encode rank positions, not calibrated relevance
confidence; relevant and unrelated top scores overlapped. A lexical top-score threshold was evaluated
separately because its scale retains match strength, but it is corpus-specific and only provisional.

**Did you tune the admission threshold on the test set?** No. The threshold was selected once on 45
development queries with an answerable-recall floor, then frozen on 60 test queries. Test answerable
recall was 0.956, abstention accuracy 0.800, and balanced accuracy 0.878 versus 0.500 for always-admit.
The quality gates pass, but the missing-human-review gate keeps the candidate blocked.

**What are the 34 Runtime cases?** The matrix spans candidate search, availability, booking, and travel tools;
timeout, connection, permission, runtime exception, invalid Schema, and insufficient evidence;
single-retry recovery, exhausted retry, replan, fallback-path recovery, fallback-path failure, and safe stop.

**Why are 34/34 passing cases not a 100% reliability claim?** These are deterministic branch
contracts authored from the implementation's failure model. They prove retry/replan/state behavior under
those injections, not the frequency, dependence, or payload diversity of production incidents.
