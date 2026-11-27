# Eval history (kept in git)

New runs write to `evals/results/` (git-ignored). Runs worth keeping are copied here.

| Folder / file | What it is |
|---|---|
| `2026-11-26-agent-nemotron-3-ultra-free.json` | first real agent eval: 23/24 |
| `2026-11-26-retrieval-hashing-baseline.json` | retrieval baseline: recall@3 0.857 |
| `round0-overlapping/` | runs that overlapped by accident: same model, same tasks, 79-96%; shows run-to-run variance |
| `round1/` | four free models, one run each. Provisional: scored before two eval-design fixes (per-task service state, a substring check that failed a correct refusal) |
| `round2/` | clean exam (per-task service state): nemotron-3.5-super-vl (paid) 24/24, p50 3.4 s, 2026-11-26 |
| `round3/` | after the loop + duplicate guards, 25 tasks: nemotron-3.5-super-vl 24/25 (one rare repeated-search stop), 2026-11-26 |
| `round4-free-compare/` | clean exam + guards, 25 tasks, four free models (recorded): super-vl 25/25, ernie-5.5-flash 24/25, ultra 23/25, lightning 11/25, 2026-11-27 |
