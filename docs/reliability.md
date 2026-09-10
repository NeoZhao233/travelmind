# Reliability and fallback strategy

Reliability is part of each feature's definition of done. This document is updated whenever a
model call, graph node, datastore, external API, or background job is introduced.

## Definition of done for a dependency

Every dependency must document:

1. failure modes and how they are detected;
2. timeout and retry policy;
3. idempotency and duplicate-execution risks;
4. fallback or fail-closed behavior;
5. what the user sees when degraded;
6. metrics, logs, and trace attributes;
7. a deterministic or injected-failure test;
8. recovery and data-consistency behavior.

Retries are bounded and reserved for transient failures. Backoff and jitter are required before
production use. Validation errors, authentication errors, invalid requests, and hard policy
violations are not blindly retried.

## Initial failure matrix

| Dependency or stage | Primary failure | Fallback | Safety boundary |
| --- | --- | --- | --- |
| Planner LLM | Timeout or provider error | One bounded retry; optional evaluated backup model | Revalidate schema and itinerary after model switch |
| Structured output | Invalid schema | One repair attempt with validation errors | Never pass malformed data to downstream nodes |
| Dense retrieval | Vector service unavailable | Implemented sparse-only ranking; confidence gating is still planned | Mark degraded retrieval mode in response and traces |
| Sparse retrieval | Sparse index unavailable | Implemented dense-only ranking; confidence gating is still planned | Do not claim hybrid quality while degraded |
| Reranker | Timeout or model failure | Use fused RRF order | Cap candidate count and expose fallback metric |
| Qdrant | Complete outage | Read-through cache or fail retrieval explicitly | Never let the LLM invent missing evidence |
| PostgreSQL | Structured facts unavailable | Fail closed for prices, opening hours, and hard constraints | Do not publish an apparently feasible itinerary |
| Redis | Cache unavailable | Bypass cache and call the source within rate limits | Cache failure must not corrupt correctness |
| Weather or route API | Timeout or rate limit | Fresh-enough cached value, otherwise return unknown | Include retrieval time and stale-data warning |
| LangSmith | Telemetry unavailable | Local structured logs and buffered export | Observability failure must not block user work |
| Checkpointer | Persistence failure | Continue only for explicitly stateless, side-effect-free runs | Do not promise resumability without a saved checkpoint |
| Constraint validator | Violations remain after repair budget | Return partial plan plus explicit violations | Never relabel an invalid plan as completed |
| Seed/ingestion record | Malformed schema, duplicate ID, or broken reference | Stop ingestion with file/line or record identity | Never build an index from a partially valid snapshot |
| Dynamic source | Missing, stale, or contradictory value | Refresh from higher-authority source; otherwise return unknown | Fail closed for opening time, booking, price, and feasibility |
| Source fetch | Timeout, block, or page-format change | Keep last known snapshot only if its fact-specific freshness policy allows | Mark collection time; do not silently present stale data as current |
| Corpus publish | Process stops during refresh | Build a versioned candidate snapshot, validate, then atomically promote | Readers stay on the previous complete version |
| BM25 query | Empty or punctuation-only input | Return an empty result and let bounded graph fallback handle insufficiency | Do not return arbitrary zero-score documents |
| Metadata prefilter | Unsupported key or invalid value | Report unsupported keys; reject invalid supported values | Never claim an unenforced constraint was applied |
| Metadata prefilter | Valid filter removes comparison evidence | Retain an unfiltered retrieval mode; consider post-retrieval validation | Do not equate filter precision with complete reasoning evidence |
| BM25 index | Empty/corrupt corpus or missing references | Refuse index construction after dataset validation | Never serve a partially built in-memory index |
| Embedding model | Missing package/cache, download failure, or inference error | Dense-only fails explicitly; hybrid uses implemented BM25 fallback | Never fabricate vectors or reuse another model silently |
| Embedding output | Wrong count/dimension, NaN, infinity, or zero vector | Reject index build/query and identify the vector | Never publish a collection with an incompatible schema |
| Qdrant dense query | Client error, missing payload identity, or unavailable collection | Hybrid falls back to sparse ranking and marks degradation | Evidence without document/chunk provenance is unusable |

The entries above are design targets, not claims that every fallback is already implemented.
Implementation status must be backed by tests and linked from this document.

## Graph-state requirements

The graph will record enough information to explain degraded behavior:

```text
degraded_components
fallbacks_used
retry_counts
dependency_errors
evidence_freshness
unresolved_violations
```

Large raw responses, credentials, and non-serializable clients must not be stored in graph state.
Nodes that may run again after checkpoint recovery must be idempotent or carry an idempotency key.

## Failure-injection test plan

- Retriever returns no documents.
- Retriever raises a timeout on the first call and succeeds on retry.
- Dense retrieval fails while sparse retrieval succeeds.
- Reranker fails and preserves deterministic RRF ordering.
- LLM returns invalid structured output.
- Route API returns a stale cached response and a freshness warning.
- PostgreSQL is unavailable during hard-constraint validation.
- Process stops after a checkpoint and resumes without repeating completed side effects.
- All retries are exhausted and the graph terminates with an explicit failure.

## Stage 1 data safeguards

Implemented now:

- Pydantic schema and range validation;
- timezone-required collection and observation timestamps;
- unique IDs and referential integrity across places, documents, facts, and evaluation labels;
- fact/source place consistency;
- evaluation fact-type coverage checks;
- deterministic normalized chunks and content-derived IDs;
- line-aware JSONL parse errors;
- authority and freshness metadata retained on source documents and chunks.

Implemented in Stage 2A:

- empty-query and impossible-filter behavior returns no arbitrary documents;
- invalid BM25 parameters and invalid supported filter values fail explicitly;
- unsupported filters are counted in experiment output;
- stable tie-breaking and document-level deduplication keep repeated runs comparable;
- filtered and unfiltered reports expose prefilter trade-offs instead of hiding recall loss;
- dataset fingerprints prevent comparing metrics from silently different inputs.

Implemented in Stage 2B:

- FastEmbed is optional and the missing-extra error includes the bootstrap command;
- project-local model/Hugging Face/Xet cache paths avoid implicit user-directory permissions;
- ONNX Runtime telemetry is disabled before model import to avoid network/cache side effects;
- `--local-files-only` verifies cached offline inference and fails if provisioning is incomplete;
- model/runtime/source metadata and a cached-artifact SHA-256 enter every dense report;
- vector count, dimension, finiteness, and nonzero validation happen before index publication;
- deterministic UUIDv5 point IDs make repeated upserts idempotent;
- model/index failures and query failures use distinct exception boundaries;
- unit tests inject wrong dimensions and query-time outages;
- dense filters are reported as unsupported and rejected by the Stage 2B CLI.

Implemented in Stage 2C:

- sparse and dense calls run concurrently under a shared orchestration deadline;
- an exception or timeout in one channel returns the surviving ranking with `sparse_only` or
  `dense_only`, `degraded_components`, and `fallbacks_used` diagnostics;
- dual failure raises `HybridRetrievalError` rather than producing unsupported evidence;
- channel status counts and fallback counts are aggregated in evaluation reports;
- third-party exception messages are excluded from diagnostics to avoid leaking request data or
  credentials;
- unit tests inject channel exception, deadline expiry, and dual failure;
- hybrid filters fail explicitly until both channels enforce equivalent semantics.

Remaining boundary: the orchestration deadline stops waiting but cannot terminate a Python thread
that already entered provider code. Production Qdrant/model adapters require their own connection,
read, and inference timeouts plus a bounded executor. Confidence-based gating of a surviving
channel also awaits an abstention dataset and calibration.

Implemented in Stage 2D:

- reranking is bounded to ten candidates and hidden behind an injected provider;
- missing, extra, NaN, or infinite scores are treated as inference failures;
- runtime exception, invalid output, or timeout preserves deterministic RRF order;
- result diagnostics distinguish successful reranking from `preserve_base_order` fallback;
- exception types are recorded without potentially sensitive third-party message text;
- startup/model-cache failure aborts the reranked experiment instead of silently relabeling an RRF
  result;
- model ID, FastEmbed version, registered license/size/source, and artifact fingerprint are stored;
- failure-injection tests cover exception, timeout, malformed scores, empty candidates, and graph
  score provenance.

The BGE reranker is not a production dependency because its measured quality/latency trade-off was
negative. The fallback remains implemented so future model experiments cannot reduce availability.

Implemented in Stage 3A:

- LangGraph retrieval and rewrite cycles have explicit maximum attempts;
- routing, grading, and rewriting use injected policies with deterministic fallbacks;
- dependency errors store only component and exception type;
- missing fact aspects enter targeted rewrites and terminal failure reasons;
- retrieved evidence is deduplicated across attempts;
- query fanout is deduplicated and capped at four;
- partial multi-query failure preserves surviving rankings, while all-query failure is explicit;
- tests inject router, grader, rewriter, retriever, and individual-query failures;
- insufficient evidence terminates without calling the planner.

Implemented in Stage 3B policy evaluation:

- routing labels and evidence-sufficiency labels are separate from retrieval-relevance labels;
- case IDs and document/query references are validated before evaluation;
- both development and test splits are required, and the dataset fingerprint is stored;
- the weak `rule-v1` report is frozen instead of being replaced by a tuned result;
- every incorrect case retains expected/predicted decisions and machine-readable reason codes;
- reports disclose that labels are project-authored drafts and that the test split is not blind.

This split is an evaluation fallback, not a production runtime fallback. If a learned Router or
Grader is unavailable, malformed, or times out, the Stage 3A graph can still use deterministic
policies; whether those policies are accurate enough is a separate quality question exposed by the
Stage 3B report.

Implemented in Stage 3C:

- timeout injection is allowlisted; arbitrary exception construction from dataset text is rejected;
- document references and per-step oracle labels are validated before a run;
- the report distinguishes recoverable abstention from correct terminal abstention;
- unsupported generation is a first-class metric and is not hidden by aggregate task success;
- the complete Agentic node trajectory and degraded component list remain auditable per case;
- scripted-harness timing is not mislabeled as provider latency.

Implemented in Stage 3C.2:

- `retrieval_limit` is explicit and validated instead of being a hidden graph constant;
- support is checked against relevance labels and expected fact-type coverage, independently of the
  runtime Grader;
- Hybrid rank calls and end-to-end local control latency are recorded per query;
- a failed rewrite cannot exceed the two-attempt budget and terminates without planning;
- missing corpus coverage is distinguished from retriever or rewrite failure.

Implemented in Stage 3D/3E:

- API keys come only from environment configuration and are excluded from representations;
- provider timeouts and transient 429/500/503 failures have one bounded retry;
- empty, truncated, malformed, non-object, and schema-invalid JSON triggers deterministic fallback;
- Grader contradictions are rejected even when the JSON schema parses;
- prompts have explicit component versions and calls record tokens, latency, attempts, and errors;
- fallback-inclusive quality is paired with raw fallback rate;
- absence of a candidate report retains the baseline rather than blocking runtime availability;
- Rewriter cannot be selected using Router or Grader metrics.
- thinking is disabled for short JSON control calls after a live truncation failure demonstrated
  that reasoning tokens could exhaust the output budget;
- the selected API-enabled profile uses only the LLM Router, so Grader/Rewriter quality does not
  regress merely because their integrations are available.

Implemented in Stage 4A/4B:

- full prompt and evidence content are excluded from `ContextTrace`;
- original request, system instructions, and explicit constraints cannot be silently truncated;
- mandatory overflow fails before the provider call;
- output reserve and estimation safety margin are deducted before evidence admission;
- per-evidence caps prevent one long document from monopolizing the context;
- every clip/drop action has a reason code and document ID;
- tokenizer failure degrades to a heuristic and emits a sanitized component signal;
- provider-side truncation is not used as a context-management strategy.

Implemented in Stage 4C:

- missing typed fact metadata degrades to retrieval-priority order;
- unknown query wording retains a generic description target and the retrieval score;
- coverage promotion is bounded so broad metadata cannot completely override relevance;
- release evaluation pairs aspect coverage with relevant-document recall to prevent metric gaming;
- inferred targets and selection reason codes are traceable without storing user or evidence text;
- the stress-budget A/B records per-case regressions, not only an aggregate average.

Implemented in Stage 4D:

- different structured values bypass near-duplicate suppression and enter conflict handling;
- suppressed duplicates retain merged document IDs for citation provenance;
- higher authority wins before recency, so a new guide cannot override an official claim;
- equal-precedence conflicts remain visible and require downstream uncertainty or abstention;
- malformed or missing timestamps never create false freshness precedence;
- compression is extractive and prioritizes numeric, negative, closure, exception, and requirement
  spans;
- when no complete sentence fits, compression is skipped and Stage 4B handles bounded overflow;
- refinement traces exclude evidence content and expose unresolved conflicts and skipped compression.

Implemented in Stage 4E:

- memory keys include tenant, user, and thread boundaries rather than a global conversation key;
- short-term turns expire, are capacity bounded, and use `turn_id` for retry-safe idempotency;
- long-term preferences require consent, use an allowlist, and reject stale overwrites;
- explicit current-request values override stored preferences before context construction;
- memory reads fail open to marked stateless mode and writes disclose non-persistence;
- deletion failures fail closed and never claim that data was removed;
- thread deletion and user deletion have separate tested semantics;
- memory content remains optional context and cannot evict mandatory instructions or constraints.

Implemented in Stage 4F:

- model-visible metadata excludes full URLs and internal selector labels while provenance retains them;
- answer JSON is schema validated and provider/schema failures count as fallback, not successful abstention;
- citation IDs are normalized to one document-ID contract and invalid citations remain in the
  precision denominator;
- an unsupported real-time query tests abstention rather than forcing an answer;
- unbounded-context output failure is retained as negative evidence;
- reference-label corrections preserve the old dataset and all earlier reports for auditability;
- final selection requires non-decreasing task/citation quality, fallback at most 10%, and fewer
  provider tokens.

Implemented in Stage 5A:

- hard constraints are rechecked outside the LLM with typed machine-readable violations;
- budget uses recomputed line-item cost, so an inconsistent claimed total cannot bypass the limit;
- timestamps must be timezone-aware and adjacent half-open intervals are not false conflicts;
- strict availability validation distinguishes missing, unsourced, unknown, stale, closed, and
  outside-hours states;
- duplicate `(place_id, service_date)` availability facts are rejected rather than resolved by
  accidental input order;
- booking-required activities need explicit confirmation;
- missing dynamic facts fail closed for the affected activity, while the reason code enables later
  refresh, replacement, or bounded partial repair;
- controlled failure scenarios are versioned and store exact expected versus actual violation sets.

Current boundary: the reference scenarios use fixtures. A real availability provider still needs
timeouts, freshness thresholds by fact type, cached-last-known-good policy, and outage drills.
Travel-time feasibility is implemented by Stage 5B below.

Implemented in Stage 5B:

- travel estimates are directed, dated, sourced, and time-bounded;
- origin-to-first, between-activity, and final return legs are checked independently;
- a configurable transfer buffer is enforced by both generation and validation;
- missing, unknown, unsourced, or stale routes fail closed instead of becoming zero-duration edges;
- candidates are admitted only when their visit and return fit the daily window;
- required, excluded, budget, pace, booking, and operational constraints are applied during
  construction and independently rechecked afterward;
- every candidate receives a selected or skipped trace with sanitized reason codes;
- deterministic candidate-ID tie breaking prevents run-to-run instability.

Current boundary: the travel fixtures are static point estimates. Production adapters need per-mode
TTL policy, timeout and rate-limit handling, uncertainty/quantile estimates, cache provenance, and
live outage drills. The greedy algorithm is a safe baseline, not a global-optimality guarantee.

Implemented in Stage 5C:

- validate, repair, and revalidate are explicit LangGraph nodes with a two-attempt default cap;
- violation codes map to arithmetic, activity-removal, affected-day, or unsupported scopes;
- unsupported violations fail immediately rather than consuming retry or provider budget;
- unaffected days are excluded from replanning and covered by a preservation probe;
- `modified_days` records actual typed changes, not attempted no-op repairs;
- every repair candidate passes the independent deterministic validator;
- primary repairer exceptions fall back to the deterministic repairer and expose only error type;
- exhausted repair retains remaining violations and cannot publish an invalid itinerary as success.

Current boundary: checkpoint persistence and concurrent resume have not been exercised, and the
primary repairer outage is injected rather than a real provider timeout. Full-trip regeneration is
not automatic because its larger blast radius needs a separate quality and cost gate.

Implemented in Stage 5D:

- the end-to-end pipeline has explicit failure boundaries for retrieval, mandatory context,
  candidate matching, planning, validation, and repair;
- total retrieval failure can use an injected fallback retriever; dual failure returns no itinerary;
- candidate eligibility requires retrieved place-linked evidence and preserves evidence IDs;
- raw narrative context stays bounded while structured candidate breadth is preserved separately;
- the DeepSeek component controls soft ranking only and cannot bypass feasibility checks;
- duplicate or unknown LLM place IDs activate deterministic fallback;
- omitted safe-shortlist IDs are completed by deterministic retrieval order;
- provider-success/schema-failure telemetry retains actual tokens and latency;
- component selection includes fallback and provider cost, not only valid JSON rate;
- real A/B rejection leaves the deterministic planner as the zero-provider-dependency default.

Current boundary: operational facts and routes in the Stage 5D cases are controlled fixtures. A
retrieval fallback is unit-tested, but a live dense-channel or DeepSeek outage was not deliberately
triggered during the final A/B. Production alerts must treat elevated fallback as degradation.

Implemented in Stage 6A/6B:

- the governance manifest pins the exact task-dataset SHA-256 and reports its own fingerprint;
- manifest coverage must exactly match dataset case IDs and development/test must both be non-empty;
- duplicate IDs and cross-split normalized-query or scenario collisions fail the audit;
- `independently_reviewed` is invalid unless at least one reviewer differs from every author;
- the current test split is machine-reported as project-authored and non-blind;
- a report/data fingerprint mismatch fails closed instead of computing metrics on mixed versions;
- metrics are broken down by split and variant so aggregate success cannot hide a test regression;
- multi-label symptom codes cover retrieval, context, candidate, constraint, preference, repair,
  provider, structured-output, and fallback boundaries;
- telemetry absent from an older frozen report is marked unobserved rather than reconstructed.

Current boundary: lexical leakage checks do not detect every semantic paraphrase, the five-case set
has no independent reviewer, and deterministic symptoms do not prove root cause. Stage 6C must use a
human-scored calibration set before any LLM judge is trusted; Stage 6D will turn selected metrics into
automated regression gates.

Implemented in Stage 6C infrastructure:

- incomplete human labels stop execution before the first provider call;
- source variant and model identity are absent from each annotation/Judge item;
- Judge JSON is schema-validated with four bounded integer scores and a bounded evidence summary;
- three calls per item measure instability, while per-candidate aggregation avoids pseudo-replication;
- provider or output failure counts against a maximum 5% fallback gate;
- Judge rejection affects only subjective scoring and never disables deterministic safety metrics;
- API keys remain environment-only and no live Judge is called during packet preparation.

Current boundary: the annotation file has no human labels, so no calibration or acceptance claim has
been produced. Human-human agreement and independent review are still absent.

Implemented in Stage 6D:

- the release profile pins the exact baseline audit hash and fails closed if it changes;
- candidate dataset and manifest fingerprints must match the baseline before metrics are compared;
- quality floors are checked independently on development and test partitions;
- safety-related issue codes are forbidden rather than averaged into task success;
- fallback, provider tokens, and provider latency have explicit ceilings;
- any candidate consuming provider tokens must produce a predeclared minimum quality lift;
- the CLI writes diagnostics and exits nonzero on rejection, making it directly usable in CI;
- the selected deterministic baseline self-check passes, while the zero-lift paid candidate is
  rejected by an injected real-report comparison.

Current boundary: CI workflow wiring is not yet committed because this project workspace has no
repository-local GitHub configuration. The command-level contract and exit status are tested.

Implemented in Stage 7A:

- one typed trace ID correlates pipeline, retrieval, context, candidate, planner, and repair events;
- per-run sequence numbers expose locally missing or reordered emissions;
- telemetry attributes are allowlisted and unknown values are dropped with a count;
- raw query, prompt, evidence, URL, provider response, and exception message are excluded;
- exceptions expose only their type at the telemetry boundary;
- sink failure cannot fail planning and sets `telemetry_degraded=true` in the result;
- primary-retrieval timeout remains visible even when fallback completes the business request;
- injected canaries verify that user and exception payloads do not enter events or final results.

Current boundary: the reference sink is in-memory. A production exporter still needs a bounded
buffer, overflow/drop metrics, batching, sampling, flush semantics, transport deadlines, retention,
and cardinality controls. Sink-outage detection cannot depend only on that failed sink.

Implemented in Stage 7B:

- transient timeout/connection failures drive a thread-safe closed/open/half-open state machine;
- open circuits fail fast without calling the unhealthy provider;
- only one half-open probe is admitted, preventing a recovery thundering herd per breaker instance;
- non-transient request/validation failures do not poison provider-health state;
- cache keys hash canonical queries and limits instead of storing raw query text as identifiers;
- evidence snapshots are deep-copied on cache read/write to prevent shared mutation;
- fresh cache fallback is explicitly degraded and observable through retrieval diagnostics;
- stale fallback requires every returned evidence item to have an allowlisted freshness class;
- stale dynamic or over-age static evidence fails closed with a sanitized typed error;
- pipeline telemetry records cache mode, age, circuit state, and fallback without content.

Current boundary: the in-memory cache and process-local breaker do not prove Redis TTL atomicity,
distributed breaker coordination, eviction behavior, or cross-replica recovery. Circuit breaking does
not replace provider-native deadlines. Live fact adapters still need fact-specific freshness policy.

Implemented in Stage 7C logical-resume pilot:

- the Agentic graph accepts an injected checkpointer and explicit interrupt boundaries;
- checkpointed invocation requires an explicit scoped thread ID;
- a rebuilt compiled graph resumes from the recorded next node without repeating the Planner;
- strict MessagePack mode uses an explicit internal class allowlist rather than arbitrary modules;
- idempotency keys bind scope, operation, implementation version, request, and evidence fingerprints;
- completed receipts return deep copies and count replay separately from execution;
- an in-progress duplicate is rejected instead of executing concurrently;
- failed operations release their in-progress receipt so a legitimate retry can run;
- checkpoint write failure stops a run that requested resumability and records only safe error type.

Current boundary: InMemorySaver and in-memory receipts do not survive process loss or coordinate
replicas. A crash after external success but before receipt commit remains ambiguous. Production
requires a durable LangGraph saver, transactional receipt uniqueness/leases, migrations, retention,
tenant authorization, encryption, and abandoned-operation reconciliation.

Implemented in Stage 7C.2:

- the official SQLite checkpointer persists strict-serialized graph state across Python processes;
- a second process resumes at the saved next node and performs zero repeated Planner calls;
- SQLite receipts use an atomic primary-key claim with owner, state, and acquisition timestamp;
- a second process replays completed typed itinerary JSON with zero underlying Planner calls;
- normal operation failure removes only the matching owner's unfinished claim;
- expired in-progress receipts fail closed instead of being automatically stolen;
- checkpoint and receipt database files are restricted to owner-only mode `0600`;
- WAL and a bounded busy timeout improve local behavior without claiming distributed scalability.

Current boundary: SQLite is a local synchronous adapter, not the production database. It does not
establish multi-instance concurrency, remote backup/restore, disk-full/corruption recovery, tenant
row-level authorization, encryption at rest, pruning, or PostgreSQL migration behavior.

Planned for the live ingestion stage:

- network timeouts, bounded retry, rate limiting, and conditional requests;
- immutable raw-source snapshots and content hashes;
- conflict reconciliation by authority, update time, and fact-specific policy;
- quarantine of invalid records instead of partial index publication;
- versioned index builds with atomic promotion and rollback;
- stale-source, parse-change, duplicate-fetch, and interrupted-publish failure injection.

An official source is not automatically current. Dynamic hard constraints need a fact-specific
freshness threshold; if no admissible value exists, the planner must expose uncertainty or stop the
affected itinerary step.

Stage 8A implements the first ingestion reliability boundary. Raw bytes are retained by content hash;
parsed records are built in isolation; validation failure quarantines the candidate while preserving
the active version; and publication or rollback changes only an atomic `CURRENT` pointer. This avoids
mixed-generation reads locally. It does not claim a distributed transaction: production Qdrant or
Elasticsearch should use versioned collections and an alias swap, with conditional promotion and
multi-writer ownership.

Stage 8B constrains live source fetches with exact HTTPS-host policy, disabled redirects, per-call
timeout, bounded attempts, and capped backoff. Only transport failures, `429`, and `5xx` retry.
Conditional validators avoid downloading unchanged content. On outage, fresh cache may cover a
transient fault; only explicitly static facts may cross the fresh TTL, and never beyond maximum stale
age. Dynamic booking, opening, route, weather, and price evidence fails closed once stale.

Stage 8C treats every parser output as untrusted. Domain-schema and cross-record failures create only
a sanitized quarantine receipt. Conflict comparison uses value-independent semantic keys, groups
equivalent values, then applies authority and observation time to already freshness-admissible facts.
Equal-precedence disagreement is excluded from the active fact set. Incremental updates compute on
copies and commit only after affected-key resolution succeeds, preserving the previous state on error.

## Development environment reliability

The bootstrap path is treated as part of the product. On macOS, `uv sync` produced editable `.pth`
files carrying the filesystem `hidden` flag; Python then skipped those files and the installed
project became non-importable. Clearing the flag passed an immediate import but failed on the next
process because the flag was reapplied. `scripts/bootstrap.sh` therefore performs a non-editable
install that does not depend on `.pth` processing. `scripts/verify.sh` separately exercises package
import, CLI cold start, tests, and linting. See ADR 003 for alternatives and trade-offs.

## Metrics

At minimum, track:

- dependency error rate by type;
- fallback activation rate by component;
- retry count and retry success rate;
- graph completion, partial-completion, and failure rates;
- p50/p95 latency in normal and degraded modes;
- stale-evidence rate;
- unresolved-constraint rate;
- duplicate side-effect count;
- checkpoint resume success rate.

Fallbacks protect availability but can hide chronic dependency problems. A high fallback rate is
therefore an alert condition, not a successful steady state.

Index control paths validate build identifiers before joining filesystem paths. Publication refuses
manifests whose source snapshots are absent, and serving rechecks the artifact SHA-256 against the
manifest. These checks turn path traversal, missing provenance, and post-publication corruption into
explicit failures instead of silently serving an unverified generation.

Stage 7D turns this distinction into an executable pre-release gate. A simultaneous primary
retrieval, model-ranking, and telemetry outage must complete using BM25 plus deterministic planning,
but it is recorded as degraded rather than healthy. If primary and fallback retrieval both fail, the
pipeline must return a safe failure with no itinerary. The controlled report passed all seven checks
with zero canary leakage. Because it has one local sample per scenario, it is explicitly not a
production SLO or latency-percentile claim; deployment still needs windowed SLIs and burn-rate alerts.

## Interview evidence rule

An interview answer about reliability should include a concrete failure, detection signal,
fallback path, safety boundary, and test or trace. Avoid generic claims such as "we added retry"
unless the repository shows which errors are retried, how often, and how retry storms or duplicate
side effects are prevented.

## Stage 11 runtime replanning boundary

The runtime distinguishes transient transport faults from permanent tool failures and invalid tool
schemas. Only transient faults retry the same step. Other failures enter the planner as typed
observations and can produce a new plan revision. Attempt, replan, and total-call budgets are enforced
outside the planner, so a model cannot waive them. Exception messages are excluded from graph state.

The current proof uses injected local tools. It verifies control semantics and safe termination, not
remote API availability, rate-limit behavior, or exactly-once side effects. A future side-effecting
booking tool must additionally use Stage 7 idempotency receipts; replanning alone does not make a
non-idempotent external action safe.
