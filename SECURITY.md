# Security

## Reporting a vulnerability

Please do not open a public issue. Use GitHub's
"Report a vulnerability" (private advisories) on this repository. Expect a first reply within a week.

## Never commit keys

API keys (`ANTHROPIC_API_KEY`, `OPENAI_API_KEY`, OpenRouter keys) live in `.env` (git-ignored), CI secrets, or Space
secrets, never in code, issues or logs. If a key is committed, revoke it first, then remove it from history.

## The public demo

The demo is meant to be abused safely:
- Services are simulated (`DEMO_MODE=1`); the agent cannot reach any real system, and `restart_service` only queues a
  request that nothing executes.
- Per-visitor sessions and rate limits cap how much one visitor can spend or send. Use a separate model key with a
  small spend limit for the demo, never your main key.
- Data in the demo (tickets, messages) is public-grade: do not type secrets or personal data into it. The demo
  database is ephemeral.
- The agent treats runbook text as untrusted data and cannot act on instructions inside it, but prompt injection is
  not solved; the real defence is that dangerous actions need a human.

## Scope

In scope: this repository's code and Dockerfiles. Out of scope: third-party model providers and hosting platforms.
