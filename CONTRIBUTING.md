# Contributing

Thanks for looking. The project is deliberately small; changes that keep it readable are welcome.

## Setup

```bash
uv sync                       # installs runtime and dev dependencies
uv run pytest -q              # SQLite, no network, no API key (scripted fake model)
uv run ruff check .           # lint (line length 120)
make test-pg                  # also run every test on Postgres + pgvector (needs a running DB)
```

For Postgres tests: `docker run -d -p 5432:5432 -e POSTGRES_USER=helpdesk -e POSTGRES_PASSWORD=helpdesk
-e POSTGRES_DB=helpdesk_test pgvector/pgvector:pg16`, then `make test-pg`.

## Add a tool

1. In `src/helpdesk/tools.py` define a Pydantic args model (`Field(description=...)` is what the model reads), an async
   function `(ctx, args) -> dict`, and register a `Tool(...)` in `build_tools` with a risk level:
   `read`, `write`, or `dangerous`.
2. A `dangerous` tool must only queue a `PendingAction`; it must never act. Raise `ToolError` for expected failures so
   the message goes back to the model.
3. Add tests in `tests/test_tools.py` (valid call, invalid arguments, unknown names) and, if the agent should use it,
   a scripted-model test in `tests/test_agent.py`.
4. Add at least one task to `evals/tasks.jsonl` that checks the action (see [docs/EVALS.md](docs/EVALS.md)) and update
   the system prompt in `agent.py` only if the model needs to know when to use it.

## Add an eval task

Append a line to `evals/tasks.jsonl`, run it with `--only <id>`, read the transcript if it fails. Check actions, not
phrases. Never tune a task to make one model pass.

## Pull requests

- Tests and ruff pass; new behaviour has a test.
- Numbers in docs come from `evals/results/` or are labelled provisional.
- No keys, no personal data. See [SECURITY.md](SECURITY.md).
- Update [CHANGELOG.md](CHANGELOG.md).
