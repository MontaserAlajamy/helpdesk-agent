---
title: Helpdesk Agent
emoji: 🛠️
colorFrom: indigo
colorTo: blue
sdk: docker
app_port: 8000
pinned: false
license: mit
short_description: IT helpdesk AI agent demo (Arabic and English), tools and approval queue
---

# Helpdesk Agent (demo)

A small IT helpdesk agent: searches runbooks, checks simulated services, opens tickets, and queues restarts for human
approval. Source and docs: https://github.com/MontaserAlajamy/helpdesk-agent

This Space runs in demo mode (simulated services, per-visitor sessions, rate limits) on a temporary SQLite database.
Do not enter personal data or secrets.

## Setup (owner, once)

Copy `README.md` and `Dockerfile` from this folder into a new Docker Space repository (the Dockerfile fetches the
project from GitHub at build time), then in the Space settings:

- Secret `OPENAI_API_KEY`: an OpenRouter key. Use a separate key with a small spend limit.
- Variable `LLM_PROVIDER` = `openai`
- Variable `OPENAI_BASE_URL` = `https://openrouter.ai/api/v1`
- Variable `LLM_MODEL` = a free model id, for example one ending in `:free` that supports tool calling.
- Optional build variable `REPO_REF` = a tag or commit to pin.

Free models are rate limited and may return 429; the demo then shows an error, which is expected.
