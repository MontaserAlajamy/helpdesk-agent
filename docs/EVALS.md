# Evals

Two evals. Both can fail, and the harness is itself tested.

## How to run

```bash
# retrieval: no model, no key. Exits 1 below the threshold.
uv run python -m helpdesk.evals retrieval --min-recall3 0.8

# agent: one model, 24 tasks. Costs API calls.
uv run python -m helpdesk.evals agent --provider openai --base-url https://openrouter.ai/api/v1 \
    --model <model-id> --min-success 0.8 --repeat 3
uv run python -m helpdesk.evals agent --provider anthropic --model <model-id>

# compare the saved agent results (latest per model)
uv run python -m helpdesk.evals compare --since 20261126
```

Or `make eval-retrieval` and `make eval-agent MODEL=<id>`. Results are written to `evals/results/` (JSON). With
`--provider openai` set `OPENAI_API_KEY`; use `--base-url` or `OPENAI_BASE_URL` for OpenRouter. In CI the manual
`agent-eval` job accepts either `ANTHROPIC_API_KEY` or `OPENROUTER_API_KEY` secrets.

## Retrieval eval

`evals/retrieval.jsonl`: one `{"q", "expect", "lang"}` per line (35 questions, 15 Arabic). The runbooks are seeded
into a temporary SQLite database, each question is searched with k=3, and we report recall@1 (right runbook first),
recall@3 (right runbook in the top three), by language, plus the list of misses.

## Agent eval: what each check means

Each task in `evals/tasks.jsonl` (24 tasks, 8 Arabic) runs on a fresh database against real local services. After
the run the harness checks (`score_task` in `src/helpdesk/evals.py`):

| Task field | Check |
|---|---|
| `must_call` | These tools were called (for example search_runbooks before giving steps). |
| `must_not_call` | None of these were called (for example no restart when the service is up). |
| `ticket` | A ticket was created, or not, as expected. |
| `priority_in`, `category_in` | The created ticket's priority / category is in the allowed set. |
| `language` | The structured reply language matches the user's language. |
| `needs_human` | The hand-off flag matches. |
| `answer_must_not_contain` | The answer does not leak a string (for example a password). |
| `down` | Which services are down for this task (default: all up). |
| (always) | Stop reason is `final_answer`; no guard `violations` (for example an invented ticket number). |

The report also records success rate, invalid-tool-call rate, forbidden tool calls, violations, text/field repairs,
average steps, tokens, and p50/p95 latency.

## Add a task

1. Append one JSON line to `evals/tasks.jsonl` with a unique `id`, `message`, `language`, and the checks above.
2. Say what you expect *and why* in the check fields; prefer checking an action over a phrase.
3. Run it alone: `uv run python -m helpdesk.evals agent --model <id> --only <task-id>`.
4. If a good model fails it, read the transcript before changing the model or the task (see below).

## Eval history

All agent numbers are from free OpenRouter models on 2026-11-26. Provisional.

- **Round 0** (runs overlapped by accident, which exposed variance): nemotron-3-ultra scored 79%, 83% and 96% on the
  same 24 tasks. nemotron-3.5-super 96% and 88%; ernie-5.5-flash 83% and 88%; nemotron-3.5-lightning 58% and 50%.
- **Single run, nemotron-3-ultra** (`evals/history/`): 23/24 = 95.8%, 0 forbidden tool calls, 0 violations, 1.6%
  invalid tool arguments (all recovered), 2.58 average steps, about 4.9k input and 0.5k output tokens, p50 15.8 s,
  p95 27.3 s. The one failure: an Arabic printer-fuser task where the agent gave steps but opened no ticket.
- **Round 1** (provisional, eval still had two flaws): nemotron-3.5-super 24/24, nemotron-3-ultra 23/24,
  ernie-5.5-flash 22/24, nemotron-3.5-lightning 9/24.
- **Round 2** (clean): not done. Blocked by the free-tier daily request limit; to be run with `--repeat 3`.

### The three mistakes in my eval

1. **Substring check.** "restarted" in the answer was flagged, but the agent had correctly refused ("I did not
   restart it; I queued a request"). Fixed by checking actions, not words.
2. **Mail down in every task.** With mail always down, escalating a "stuck outbox" was correct and the eval counted it
   against the model. Fixed: tasks declare `"down": [...]`; services are up otherwise.
3. **User's own number.** The ticket check flagged "ticket 9999 not found". The user had typed 9999. Fixed: numbers
   present in the user's message are allowed.

A related finding from a live demo: the Arabic answer text said "ticket 1" while the structured `ticket_id` was null.
That became a guard (text and field must agree; see ARCHITECTURE.md) and is counted as `text_vs_field_repairs`.
