# Decisions

Short records. Status of all: accepted, v0.1.

## 001. A hand-written loop instead of a framework

**Context.** Frameworks considered: LangChain / LangGraph, OpenAI Agents SDK, CrewAI, Pydantic AI.
**Decision.** Write the loop by hand: [`run_agent`](../src/helpdesk/agent.py), about 100 lines.
**Why.** Every step can be read, stepped through and unit-tested with a scripted fake model; the guards (ticket
citation, text/field agreement, untrusted data) sit exactly where the loop needs them; no framework upgrade can change
behaviour under the evals; and the point of the project is to show the mechanics.
**Trade-offs.** No built-in memory, tracing, retries, multi-agent routing or graph persistence; more code to own.
**When we would switch.** Several agents with handoffs, long-running or resumable workflows, human-in-the-loop pauses
that must survive a restart, or a managed platform requirement. The roadmap rebuilds the same agent in LangGraph,
Bedrock and Foundry and measures all of them on the same exam, so the choice is tested rather than assumed.

## 002. A narrow agent with few tools, not a general agent

**Decision.** Five tools (search_runbooks, check_service, create_ticket, get_ticket, restart_service) plus
`final_answer`, in one domain.
**Why.** A narrow scope can be specified, evaluated and trusted: 24 tasks cover the real behaviours. Few tools mean
less tool-choice confusion, which matters most for small and free models.
**Trade-offs.** It cannot do anything outside IT support; new capabilities are new tools plus tests plus eval tasks.

## 003. Dangerous actions only queue for human approval

**Decision.** `restart_service` inserts a `PendingAction`; a human approves or rejects through the API. The agent
never executes it, and the prompt forbids claiming a restart happened.
**Why.** An action with side effects must not depend on a model following a prompt. The separation is in code.
**Trade-offs.** Slower resolution; there is not yet an executor, so approval only records the decision.

## 004. Baseline hashing embedder first, measured, to be replaced

**Decision.** Start with an offline, deterministic hashing embedder (256 dims) and measure it: recall@1 0.743,
recall@3 0.857 (Arabic 0.933, English 0.800) on 35 questions.
**Why.** It needs no network or key, so tests and CI are free and repeatable, and it gives a number a real
multilingual embedding model must beat. Without a baseline, "better embeddings" is a claim, not a result.
**Trade-offs.** Lexical only: misses synonyms. Replacement is on the roadmap, measured on the same set.

## 005. Evals check actions, not words; fresh database per task; real up/down services

**Decision.** The agent eval inspects tool calls, ticket fields, pending actions, language and leaked text. Each task
runs on a fresh database against real local servers (HTTP and TCP up, a closed port down).
**Why.** Fluent text can hide a wrong action, and a wrong-sounding text can hide a right one. Real services mean
`check_service` is genuinely exercised. A fresh database stops tasks leaking state into each other. The harness is
itself tested: a deliberately dumb policy must score low.
**Trade-offs.** Checks encode our expectations; three of them were wrong at first (see [EVALS.md](EVALS.md)).

## 006. OpenRouter free models for evals; provider-agnostic adapter

**Decision.** `llm.py` exposes one small interface with an Anthropic provider and an OpenAI-compatible provider
(OpenAI, OpenRouter, vLLM, Ollama via `OPENAI_BASE_URL`). Evals were run on OpenRouter free models.
**Why.** Zero cost lets the eval run many times and across several models, and the adapter keeps the agent free of a
vendor. Tests use a scripted fake model.
**Trade-offs.** Free tiers are rate limited (a daily cap blocked the clean re-run), results vary run to run, and
latency includes queueing. Numbers are labelled provisional until repeated.
