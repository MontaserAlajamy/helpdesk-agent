# Changelog

Format: [Keep a Changelog](https://keepachangelog.com/). Versions follow [SemVer](https://semver.org/).

## [0.1.0] - 2026-11-26

### Added
- FastAPI service: `POST /v1/chat`, tickets (`GET /v1/tickets`, `GET /v1/tickets/{id}`), approval queue
  (`GET /v1/actions`, `POST /v1/actions/{id}/approve|reject`), `GET /healthz`.
- Hand-written agent loop (`src/helpdesk/agent.py`) with a step limit, structured `final_answer`, and guards:
  ticket citation check, text/field agreement repair, runbook text marked as untrusted data, fallback reply.
- Five Pydantic-validated tools: `search_runbooks`, `check_service`, `create_ticket`, `get_ticket`,
  `restart_service` (dangerous: only queues a `PendingAction`).
- Async SQLAlchemy 2 models on Postgres (pgvector) or SQLite; run and tool-call logging.
- Arabic and English runbook knowledge base (9 runbooks) with a baseline hashing embedder.
- LLM adapter: Anthropic and any OpenAI-compatible endpoint (OpenAI, OpenRouter, vLLM, Ollama).
- Eval harness: retrieval eval (35 questions) and agent eval (24 tasks, real up/down local services, fresh database
  per task), result files, model comparison table.
- 53 tests (SQLite; Postgres + pgvector with `TEST_DATABASE_URL`).
- CI: lint, tests on a Postgres service, retrieval gate, Docker build, manual agent-eval job.
- Dockerfile and Docker Compose (Postgres + pgvector + API).
- Web UI at `/`, streaming endpoint `POST /v1/chat/stream`, `GET /v1/meta`, and `DEMO_MODE` with simulated services,
  per-visitor sessions and rate limits.
- Documentation: architecture, decisions, evals; Hugging Face Space and deployment guides.

### Known limits
- Single-turn chat, no executor for approved actions, lexical embedder. See the README.
