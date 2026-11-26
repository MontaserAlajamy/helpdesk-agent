.PHONY: install test test-pg lint eval-retrieval eval-agent run demo docker

PG_URL ?= postgresql+asyncpg://helpdesk:helpdesk@localhost:5432/helpdesk_test
PROVIDER ?= anthropic

install:
	uv sync

test:
	uv run pytest -q

# every test on Postgres + pgvector as well (needs a running database, see CONTRIBUTING.md)
test-pg:
	TEST_DATABASE_URL=$(PG_URL) uv run pytest -q

lint:
	uv run ruff check .

eval-retrieval:
	uv run python -m helpdesk.evals retrieval --min-recall3 0.8

# make eval-agent MODEL=<id> [PROVIDER=openai BASE_URL=https://openrouter.ai/api/v1] [REPEAT=3]
eval-agent:
	@test -n "$(MODEL)" || (echo "usage: make eval-agent MODEL=<model-id> [PROVIDER=anthropic|openai] [BASE_URL=...]"; exit 2)
	uv run python -m helpdesk.evals agent --provider $(PROVIDER) --model "$(MODEL)" \
		$(if $(BASE_URL),--base-url $(BASE_URL),) --repeat $(or $(REPEAT),1) --min-success 0.8

run:
	uv run uvicorn --factory helpdesk.api:app_factory --host 0.0.0.0 --port 8000

demo:
	DEMO_MODE=1 uv run uvicorn --factory helpdesk.api:app_factory --host 0.0.0.0 --port 8000

docker:
	docker compose up --build
