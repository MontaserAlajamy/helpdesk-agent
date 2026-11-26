# Eval history (kept in git)

New runs write to `evals/results/` (git-ignored). Runs worth keeping are copied here.

| Folder / file | What it is |
|---|---|
| `2026-11-26-agent-nemotron-3-ultra-free.json` | first real agent eval: 23/24 |
| `2026-11-26-retrieval-hashing-baseline.json` | retrieval baseline: recall@3 0.857 |
| `round0-overlapping/` | runs that overlapped by accident: same model, same tasks, 79-96%; shows run-to-run variance |
| `round1/` | four free models, one run each. Provisional: scored before two eval-design fixes (per-task service state, a substring check that failed a correct refusal) |
