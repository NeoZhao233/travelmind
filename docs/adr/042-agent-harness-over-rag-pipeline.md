# ADR 042: Position the system as an Agent Harness with retrieval tools

## Decision

Treat LangGraph state, Plan-Act-Observe-Replan, context selection, tool policy, persistence, budgets,
validation, tracing, and evaluation as the Agent Harness. Keep BM25+BGE+RRF as a knowledge tool
inside the harness instead of describing the whole system as a RAG pipeline.

## Why

A fixed retrieve-then-generate pipeline cannot represent mid-flight tool feedback, selective replan,
side-effect policy, or durable continuation. Retrieval is still required for grounded tourism facts;
the harness determines when to retrieve, what enters context, and what happens when retrieval fails.

## Rejected alternatives

- Removing RAG because agents are fashionable: tools cannot ground changing tourism facts by
  themselves.
- Calling every workflow a Multi-Agent system: TravelMind has one governed runtime and does not need
  fictional autonomous roles.
- Letting the LLM own retry and termination: those safety budgets must remain deterministic and
  testable.

## Interview answer

RAG and Harness are different layers. RAG supplies evidence; the Harness owns the repeated model/tool
loop, context, persistence, permissions, recovery, and termination.
