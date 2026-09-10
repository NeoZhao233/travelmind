# ADR 001: Use LangGraph for bounded agent orchestration

## Status

Accepted for the initial architecture; validate again after the first end-to-end baseline.

## Problem

The workflow needs conditional retrieval retries, deterministic validation, targeted repair,
checkpointing, and inspectable execution state.

## Alternatives

- Plain Python functions and an explicit loop
- LangChain LCEL
- CrewAI or AutoGen

## Decision

Use LangGraph as a thin orchestration layer. Keep retrieval, planning, validation, and storage
logic framework-independent behind typed interfaces.

## Why

LangGraph directly represents conditional edges and bounded cycles and has a persistence model
for later checkpointing. A plain Python state machine would have fewer dependencies and remains
appropriate for a one-pass pipeline, but becomes harder to inspect as recovery paths grow.

## Costs and risks

- Framework dependency and learning cost
- State-schema migration must be managed
- Graph abstractions can hide simple business logic if nodes are too coarse
- The project must demonstrate a real need for cycles; otherwise plain Python is simpler

## Evidence required

- A trace showing at least one useful rewrite/retrieval retry
- Tests proving the loop is bounded
- A comparison with a one-pass baseline on quality, latency, and token usage

## Interview questions

- Why is a graph necessary instead of a sequential chain?
- Which nodes are deterministic and which require an LLM?
- How do you prevent infinite loops and repeated side effects?
- What is stored in graph state, and what is deliberately excluded?
- How would a schema or graph migration affect saved checkpoints?
