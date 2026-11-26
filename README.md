# Helpdesk Agent

A small IT helpdesk agent you can read in an afternoon, and trust because it is measured.

An employee writes, in Arabic or English, "the VPN won't connect" or "mail is down". The agent searches the IT
runbooks, checks the real service, opens a ticket when a person is needed, and can *request* a restart, which waits
for a human to approve. Every run is logged, and an eval suite checks what the agent actually did.

```
POST /v1/chat ──► agent loop (src/helpdesk/agent.py, no framework)
                    │  model ⇄ tools, max N steps, structured final answer
                    ├─ search_runbooks   read       pgvector similarity search (Postgres)
                    ├─ check_service     read       real HTTP / TCP check of allowlisted services
                    ├─ get_ticket        read
                    ├─ create_ticket     write      Postgres (SQLAlchemy 2, async)
                    ├─ restart_service   dangerous  only queues a PendingAction; never executes
                    └─ final_answer      structured reply (Pydantic): answer, language, ticket_id, needs_human
GET  /v1/tickets, /v1/actions      POST /v1/actions/{id}/approve|reject
```

## Why it is built this way
- **Own loop, no agent framework.** About 150 lines you can step through: tool arguments are validated by
  Pydantic and errors go back to the model so it can fix them; the loop never crashes on bad model output.
- **Guardrails in code, not only in the prompt.** Dangerous tools cannot execute. A final answer that cites a ticket
  number no tool returned is caught and corrected (`violations`). Runbook text is passed as untrusted data.
- **Two model providers behind one small interface:** Anthropic, and any OpenAI-compatible endpoint (OpenAI,
  OpenRouter, vLLM, Ollama). Tests use a scripted fake model, so they run free and offline.
- **Evals that can fail.** See below. The harness itself is tested: a deliberately dumb policy must score low.

## Evals
| Eval | What it measures | Runs in CI | Current |
|---|---|---|---|
| Retrieval (`evals/retrieval.jsonl`, 35 questions, 15 Arabic) | right runbook in top 1 / top 3 | yes, gate recall@3 ≥ 0.8 | hashing baseline: recall@1 0.74, recall@3 0.86 (AR 0.93, EN 0.80) |
| Agent (`evals/tasks.jsonl`, 24 tasks, 8 Arabic) | right tools, no forbidden tools, ticket yes/no, priority, category, language, no leaked password, prompt injection | by hand (costs API money) | not run yet |

The retrieval baseline is a deliberately simple hashing embedder (offline, deterministic). Its misses are synonyms
("I can't sign in" ≠ "password"): the number a real multilingual embedding model has to beat.

Agent tasks run against real local services (an HTTP server and a TCP port that are up, a closed port that is
down) on a fresh database each time.

```bash
uv run python -m helpdesk.evals retrieval --min-recall3 0.8
uv run python -m helpdesk.evals agent --provider anthropic --model <model-id> --min-success 0.8 [--repeat 3]
```

## Run it
```bash
cp .env.example .env          # set LLM_MODEL and an API key
docker compose up --build     # Postgres + pgvector, API on :8000
curl -s localhost:8000/v1/chat -H 'content-type: application/json' -d '{"message":"الـ VPN ما بيوصل"}'
```
Development: `uv sync`, `uv run pytest` (SQLite; set `TEST_DATABASE_URL` to also run every test on Postgres +
pgvector), `uv run ruff check .`.

## Layout
`src/helpdesk/`: `agent.py` loop · `tools.py` tools + validation · `llm.py` providers · `runbooks.py` RAG ·
`embeddings.py` baseline embedder · `db.py` models · `api.py` FastAPI · `evals.py` eval harness.
`data/runbooks/` the knowledge base · `evals/` test sets and results · `tests/` 45 tests.

## Known limits (v0.1)
- Single-turn chat (no conversation memory yet).
- Approving a restart records the decision; there is no executor yet.
- Baseline embedder is lexical; no HNSW index (9 runbooks do not need one).

## Next
MCP server for the same tools · AWS deployment (EC2, IAM, CloudWatch metrics per run, results in S3) ·
multilingual embeddings vs the baseline · model comparison on cost, success and latency.

MIT licence.
