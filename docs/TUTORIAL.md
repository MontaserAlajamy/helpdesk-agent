# The Helpdesk Agent, explained from zero

A complete guide to this project: what every part is, why it was built this way, how one request travels through the
code, how to run it, how to change it, how to fix it, and how to explain it to other people. Read it top to bottom
once; afterwards use it as a reference.

**Contents**
1. [The big idea in five minutes](#1-the-big-idea-in-five-minutes)
2. [The words you need](#2-the-words-you-need)
3. [The map: every folder and file](#3-the-map-every-folder-and-file)
4. [Follow one request through the code](#4-follow-one-request-through-the-code)
5. [Each part, in depth](#5-each-part-in-depth)
6. [The exams (evals)](#6-the-exams-evals)
7. [Running everything](#7-running-everything)
8. [Recipes: how to change things](#8-recipes-how-to-change-things)
9. [When something breaks](#9-when-something-breaks)
10. [Why it is built this way](#10-why-it-is-built-this-way)
11. [How to explain it to people](#11-how-to-explain-it-to-people)
12. [How the videos and graphics were made](#12-how-the-videos-and-graphics-were-made)
13. [What comes next](#13-what-comes-next)

---

## 1. The big idea in five minutes

**The problem.** Employees write IT problems in Arabic or English: "the VPN won't connect", "mail is down",
"I forgot my password". A person on the IT team normally reads the guide, checks the system, and opens a ticket.

**What we built.** An *AI agent* that does that first-line work:

1. it **reads** our IT guides (runbooks) to find the right steps,
2. it **checks** whether a service (mail, phones, intranet) is really up or down,
3. it **opens a ticket** when a person is needed,
4. it can **ask** for a service restart, but **never runs it**: a human approves or rejects it,
5. it **answers** in the user's language.

**The one idea to remember.** *The AI model only chooses. Our code does everything.* The model reads the conversation
and says "call this tool with these values". Our code checks that request, runs the tool, gives the result back, and
asks the model again. That repeating cycle is the **agent loop**.

**Why it is trustworthy.**
- Limits are written in code, not only in the instructions (the prompt).
- Every run is logged step by step.
- An exam of 24 tasks measures what the agent actually *does*, and it can fail.

```
Employee ──► API ──► Agent loop ◄──► AI model (chooses)
                       │
                       ├─► search_runbooks   (reads the IT guides)
                       ├─► check_service     (real network check)
                       ├─► create_ticket / get_ticket (database)
                       ├─► restart_service   (only queues a request) ──► IT person approves
                       └─► final_answer      (structured reply, checked)
```

---

## 2. The words you need

| Word | Plain meaning | Where it shows up here |
|---|---|---|
| **LLM / model** | The AI that reads text and writes text (e.g. Nemotron, Claude, GPT). | `llm.py` connects to it |
| **Token** | A small piece of text (about ¾ of a word). Models are paid and limited by tokens. | `Usage` counts them |
| **Prompt** | The text you send the model. | the conversation in `agent.py` |
| **System prompt** | Standing instructions the model gets every time ("reply in the user's language…"). | `SYSTEM_PROMPT` in `agent.py` |
| **Tool / function calling** | The model answers with "call tool X with arguments Y" instead of plain text. | the 5 tools in `tools.py` |
| **Schema** | A description of a tool's inputs (names, types, allowed values), sent to the model as JSON. | `Tool.schema()` |
| **Structured output** | An answer in a fixed shape the code can check, not free text. | `FinalAnswerArgs` |
| **Agent** | A model that chooses actions in a loop until the job is done. | `run_agent()` |
| **Agent loop** | ask the model → run what it picked → show it the result → repeat. | `run_agent()` |
| **RAG** | Retrieval-Augmented Generation: look up your own documents first, give them to the model. | `runbooks.py` |
| **Embedding** | A text turned into a list of numbers so "similar" texts have "close" numbers. | `embeddings.py` |
| **Vector database** | A database that finds the closest embeddings fast. | Postgres + **pgvector** |
| **Guardrail** | A rule that limits what the AI can do. | validation, approval queue, ticket check, step limit |
| **Prompt injection** | Text that tries to trick the model ("ignore your rules…"). | the fake-CEO exam task |
| **Human-in-the-loop** | A person must approve risky actions. | `PendingAction` + approve/reject API |
| **Eval** | An exam for AI behaviour, scored automatically. | `evals.py`, `evals/*.jsonl` |
| **Pydantic** | A Python library that checks data against a declared shape. | every tool's arguments |
| **FastAPI** | A Python web framework for building APIs. | `api.py` |
| **SQLAlchemy** | A Python library to talk to databases with Python classes. | `db.py` |
| **async / await** | Code that can wait (for the network, the database) without blocking everything else. | almost everywhere |
| **Pytest** | The testing tool. | `tests/` |
| **CI** | Continuous Integration: tests run automatically on every push (GitHub Actions). | `.github/workflows/ci.yml` |
| **Docker** | Packages the app and its database so it runs the same anywhere. | `Dockerfile`, `docker-compose.yml` |
| **uv** | A fast Python package and environment manager. | `pyproject.toml`, `uv.lock` |
| **OpenRouter** | One API that gives access to many models, including free ones. | `LLM_PROVIDER=openai` + base URL |
| **MCP** | Model Context Protocol: a standard way to plug tools into any AI app. | next step |
| **A2A** | Agent-to-Agent protocol: a standard way for agents to hand work to each other. | next step |

---

## 3. The map: every folder and file

```
helpdesk-agent/
├── src/helpdesk/          the application
│   ├── config.py          settings read from environment variables
│   ├── db.py              database tables (tickets, runbooks, pending actions, run logs)
│   ├── embeddings.py      turns text into numbers (baseline embedder)
│   ├── runbooks.py        loads the IT guides, stores them, searches them (RAG)
│   ├── tools.py           the 5 tools + final_answer: their input forms and what they do
│   ├── llm.py             talking to models: Anthropic, OpenAI-compatible (OpenRouter), fakes for tests
│   ├── agent.py           THE AGENT LOOP + the guards on the final answer
│   ├── api.py             the web API (and the demo web page)
│   └── evals.py           the exams and the comparison table
├── data/runbooks/         the 9 IT guides (markdown)
├── evals/
│   ├── retrieval.jsonl    35 search questions (15 Arabic)
│   ├── tasks.jsonl        24 agent tasks (8 Arabic)
│   ├── results/           new exam results (not in git)
│   └── history/           exam results we keep
├── tests/                 automatic tests
├── docs/                  ARCHITECTURE, DECISIONS, EVALS, this TUTORIAL
├── deploy/                how to host the demo (Hugging Face Space, VM, AWS)
├── .github/workflows/     CI: lint, tests, search gate, Docker build, manual agent eval
├── Dockerfile, docker-compose.yml, Makefile, pyproject.toml, uv.lock
```

How the files depend on each other (an arrow means "uses"):

```
api.py ──► agent.py ──► llm.py
   │          └──────► tools.py ──► runbooks.py ──► embeddings.py
   │                       └──────► db.py
   └──► config.py, db.py, runbooks.py
evals.py ──► agent.py, tools.py, runbooks.py, db.py
```

---

## 4. Follow one request through the code

The example: an employee writes **"Mail is down, please restart it now."** This is what really happens, in order.

**Step 1: the request arrives** (`api.py`, the `chat` endpoint for `POST /v1/chat`).
FastAPI checks the body against `ChatRequest` (the message must be 1 to 4,000 characters). It builds a
`ToolContext`: the database connection, the embedder, and the list of services the agent may check.
Then it calls `run_agent(...)`.

**Step 2: the run is set up** (`agent.py`, top of `run_agent`).
- an empty `AgentRun` report with a new unique id,
- the tool menu: each tool's JSON schema plus `final_answer`,
- the conversation: one message, the user's text.

**Step 3: round 1, the model is asked** (`llm.complete(SYSTEM_PROMPT, messages, schemas)`).
The adapter in `llm.py` converts our messages to the provider's format and forces a tool call
(`tool_choice="required"` for OpenAI-style, `{"type": "any"}` for Anthropic). The model answers:
`check_service {"name": "mail"}`.

**Step 4: the tool runs safely** (`_run_tool` in `agent.py` → `execute` in `tools.py`).
- `execute` validates the arguments with `CheckServiceArgs` (Pydantic). Wrong shape → the error goes back to the
  model as text, nothing crashes.
- `check_service` looks up the URL for "mail" (only names in the allowlist), opens a real TCP/HTTP connection with a
  timeout, and returns `{"service": "mail", "status": "down", "detail": "ConnectionRefusedError…"}`.
- A `StepRecord` (the diary line) is saved: step number, tool, arguments, ok, result, time.
- The result is added to the conversation, linked to the call's id.

**Step 5: round 2.** The model sees "mail is down" and calls `create_ticket {title, description, priority: "high",
category: "email"}` and `restart_service {name: "mail", reason: "…"}`.
- `create_ticket` inserts a row in the `tickets` table and remembers the id in `ctx.seen_ticket_ids`.
- `restart_service` **does not restart anything**. It inserts a `PendingAction` with status `pending` and returns
  `{"status": "pending_approval", "note": "Nothing was restarted…"}`.

**Step 6: round 3, the final answer.** The model calls `final_answer {answer, language: "en", ticket_id: 2,
needs_human: true}`. `_parse_final` checks it:
- the shape is valid (`FinalAnswerArgs`),
- ticket 2 is in `seen_ticket_ids` (a tool really returned it),
- every ticket number written in the answer text is real, or was typed by the user.

**Step 7: the reply goes back** (`api.py`). The run and every step are saved (`agent_runs`, `tool_calls` tables) and
the API returns the reply, the list of steps, the pending action ids, tokens and time.

**Step 8: a person decides.** `GET /v1/actions` lists pending actions; `POST /v1/actions/1/approve` (or `reject`)
records the decision. v0.1 records it; the on-call person performs the restart.

---

## 5. Each part, in depth

### 5.1 Settings (`config.py`)
`Settings.from_env()` reads environment variables: `DATABASE_URL`, `LLM_PROVIDER` (`anthropic` or `openai`),
`LLM_MODEL`, `OPENAI_BASE_URL`, `MAX_STEPS`, and `SERVICES` (`name=url,name=url`, where a url is `http(s)://…` or
`tcp://host:port`). Nothing is hard-coded, so the same code runs on a laptop, in Docker or in the cloud.

### 5.2 The database (`db.py`)
Tables: `tickets`, `runbooks` (with an `embedding` column), `pending_actions`, `agent_runs`, `tool_calls`.
The `Embedding` column type is a small trick: on Postgres it becomes a real pgvector `vector(256)`; on SQLite (used in
tests) it is stored as JSON. One model, two databases.

### 5.3 Turning text into numbers (`embeddings.py`)
`HashingEmbedder` is a simple, offline, deterministic baseline:
- `normalize` lowercases, removes Arabic diacritics (tashkeel) and unifies letter forms (أ إ آ → ا, ى → ي, ة → ه),
- each word and each 3-letter piece of a word is hashed into one of 256 slots,
- the vector is scaled to length 1.

It matches **shared words**, not meaning. That is why "I can't sign in" does not find the "password" guide. It is the
baseline a real multilingual embedding model must beat, and we measure that.

### 5.4 Search, i.e. RAG (`runbooks.py`)
- `parse_runbook` reads a guide file (a small header with `id` and `category`, a `# Title`, the steps),
- `seed` embeds each guide once and stores it,
- `search` embeds the question and returns the 3 closest guides. On Postgres it uses pgvector's `<=>` (cosine
  distance) inside SQL; on SQLite it computes cosine in Python.

### 5.5 The tools (`tools.py`)
Each tool is a `Tool(name, description, args_model, risk, fn)`:
- **args_model**: a Pydantic form. `Literal[...]` limits values (priority must be low/medium/high/critical).
- **risk**: `read`, `write` or `dangerous`.
- **fn**: the async function that does the work.

`execute` is the safe runner: validate → run → turn any error into a message for the model. Errors are a
`ToolError` (e.g. "ticket 9999 not found", "unknown service") or a validation error with the field names.

| Tool | Risk | Does |
|---|---|---|
| `search_runbooks` | read | the 3 closest guides |
| `check_service` | read | real HTTP or TCP check, only for allowlisted names, with a timeout |
| `create_ticket` | write | inserts a ticket, remembers its id |
| `get_ticket` | read | reads a ticket, remembers its id |
| `restart_service` | dangerous | only inserts a `PendingAction`; never restarts |
| `final_answer` | – | ends the run with a structured reply |

### 5.6 Talking to models (`llm.py`)
One small interface, `complete(system, messages, tools) → LLMResponse(text, tool_calls, usage)`, and adapters:
- `AnthropicLLM`: the Messages API. Tool results travel inside a user turn.
- `OpenAICompatLLM`: any Chat Completions endpoint: OpenAI, **OpenRouter** (what we use), vLLM, Ollama.
  It retries rate-limit errors.
- `ScriptedLLM`: a fake that replays fixed answers. It proves the loop works without paying for a model.

Switching model or provider is configuration, not code.

### 5.7 The agent loop (`agent.py`)
Read `run_agent` slowly; it is the heart (see also the flowchart in the project's graphics):
1. ask the model (at most `max_steps`, default 6),
2. no tool call → remind once, then stop with `no_tool_call`,
3. sort the calls so `final_answer` is handled **last** (a ticket created in the same turn must exist before the
   answer is checked),
4. run each tool through `_run_tool`; guide text is wrapped in `<untrusted_data>` tags,
5. a valid `final_answer` ends the run; otherwise loop again,
6. no answer after 6 rounds → a polite fallback in the user's language with `needs_human=True`.

The guards in `_parse_final`:
- `ticket_id` must come from a tool in this run, otherwise it is removed and recorded as a **violation**,
- ticket numbers *written in the text* are found with a pattern (English and Arabic, Arabic-Indic digits too):
  real but missing from the field → filled in (**repair**); not real and not typed by the user → **violation**.

**Loop and duplicate guards (added 2026-11-26 after a looping test):**
- *Repeat detector:* the same tool with exactly the same arguments runs at most twice per conversation. A third
  identical call is not run; the model is told to use what it already has and gets one more turn to answer. If it
  repeats again in a second turn, the run stops (`repeated_calls`) with a hand-off that says what was checked
  ("What I checked: mail is down") and names the ticket if one was opened.
- *No duplicates:* one ticket per category per conversation (a second `create_ticket` returns the first ticket as
  `already_open`), and one waiting restart per service (a second request returns the existing one as
  `already_pending` until a person decides). In the demo each visitor has their own queue.
- Measured on "Keep checking the mail server until it is back up" with mail down: before, 2 of 2 runs hit the
  6-step limit and one opened 2 tickets and 2 restart requests; after, no duplicates in any run and most runs end
  with a real answer.

### 5.8 The API (`api.py`)
| Endpoint | Does |
|---|---|
| `GET /healthz` | is the service alive |
| `POST /v1/chat` | run the agent, return reply + steps |
| `POST /v1/chat/stream` | the same, as live events (for the web page) |
| `GET /v1/meta` | model name, demo mode, services |
| `GET /v1/tickets`, `GET /v1/tickets/{id}` | read tickets |
| `GET /v1/actions` | restart requests waiting for a person |
| `POST /v1/actions/{id}/approve` or `/reject` | the human decision |

If no model is configured, chat answers **503** with a clear message, and the rest of the API still works.
The web page at `/` (demo) uses the stream to show each tool call as it happens. In demo mode, visitors can simulate
outages, each visitor sees only their own tickets, and there are rate limits.

### 5.9 The tests (`tests/`)
Every test runs on SQLite, and also on real Postgres + pgvector when `TEST_DATABASE_URL` is set.
- `test_tools.py`: validation errors go back to the model, tickets, restart only queues, real up/down checks.
- `test_agent.py`: the loop with the scripted model: happy path, invented ticket caught, same-turn ordering, bad
  arguments recovered, step limit fallback in Arabic, unknown tool, the ticket-number checks.
- `test_llm_wire.py`: message conversion for both providers, without calling any API.
- `test_api.py`: the full chat → ticket → approval flow over HTTP.
- `test_evals.py`: the scorer catches each kind of failure; a deliberately dumb agent must score low.

---

## 6. The exams (evals)

**Why exams and not only tests.** Tests check our code with a fake model. Evals check the *behaviour* of a real
model inside our system. Models are not deterministic, so you measure, you don't assume.

**Exam 1: retrieval** (`evals/retrieval.jsonl`, no model needed). 35 questions, each with the guide it should find.
Score: is it first (recall@1)? in the top 3 (recall@3)? Baseline: recall@3 0.86 (Arabic 0.93, English 0.80).
CI fails if recall@3 drops below 0.8.

**Exam 2: the agent** (`evals/tasks.jsonl`). 24 tasks. Each task says what must and must not happen:
`must_call`, `must_not_call`, `ticket` yes/no, `priority_in`, `category_in`, `language`, `needs_human`,
`answer_must_not_contain` (e.g. the user's password), and `down` (which services are down for this task).
Every task runs on a **fresh database** with **real local services** (an HTTP server and TCP ports; a closed port
means "down"). The scorer (`score_task`) checks what the agent **did**, then the run gets a success rate, forbidden
calls, invented tickets, bad tool arguments, steps, tokens and time.

**Results so far.** First real run: 23/24. Round 1 (provisional): 24/24, 23/24, 22/24, 9/24 across four free models.
The same model scored 79%, 83% and 96% on repeated runs: **one run is not a result**.

**The three mistakes in our own exam (the best lesson).**
1. "Ticket 9999 not found" was counted as an invented ticket, but the user typed 9999. Fix: numbers the user typed
   are allowed.
2. A correct refusal ("I can't confirm a restart that hasn't happened") failed because it contained "restarted".
   Fix: removed the word check; the real check is "never called restart_service".
3. The mail server was down in *every* task, so escalating a stuck outbox was correct. Fix: each task declares which
   services are down.

Rule: **test your tests**. A scorer can be wrong, and a wrong scorer teaches you wrong things about your model.

---

## 7. Running everything

From the `helpdesk-agent` folder:

| Goal | Command |
|---|---|
| install | `uv sync` (or `make install`) |
| tests (SQLite) | `uv run pytest -q` (or `make test`) |
| tests on Postgres too | `TEST_DATABASE_URL=postgresql+asyncpg://user:pass@localhost/db uv run pytest -q` |
| lint | `uv run ruff check .` |
| search exam | `uv run python -m helpdesk.evals retrieval --min-recall3 0.8` |
| agent exam | `OPENAI_API_KEY=… uv run python -m helpdesk.evals agent --provider openai --base-url https://openrouter.ai/api/v1 --model <model> [--repeat 3] [--only id1,id2]` |
| compare models | `uv run python -m helpdesk.evals compare [--since 20261127]` |
| run the API | `uv run uvicorn --factory helpdesk.api:app_factory --port 8000` |
| run with Postgres in Docker | `cp .env.example .env` (fill it) then `docker compose up --build` |
| demo page | `make demo`, then open http://localhost:8000/ |

Environment variables are listed in `.env.example`. Never commit a real key.

---

## 8. Recipes: how to change things

**Add an IT guide.** Create `data/runbooks/<id>.md` with the header (`---`, `id: …`, `category: …`, `---`), a
`# Title`, an Arabic keywords line, and steps. Add 2-4 questions for it to `evals/retrieval.jsonl` and run the search
exam. (The API seeds guides only into an empty table; for an existing database, reseed.)

**Add a tool.**
1. In `tools.py`: an args model (Pydantic), an async function `(ctx, args) -> dict`, and a `Tool(...)` line in
   `build_tools` with a clear description and the right risk.
2. If it changes live systems, make it queue a `PendingAction` like `restart_service`, never act directly.
3. Tests in `tests/test_tools.py` (valid, invalid, error case).
4. Mention it in `SYSTEM_PROMPT` only if the model needs a rule about when to use it.
5. Add eval tasks that need it, and tasks where it must **not** be used.

**Change the instructions.** Edit `SYSTEM_PROMPT` in `agent.py`, then run the agent exam before and after, with
`--repeat 3`. Keep the change only if the numbers say so.

**Add an exam task.** One JSON line in `evals/tasks.jsonl` with an `id`, the `message`, the `language`, and only
the checks that matter. Run it alone with `--only <id>` to see it behave, then with the whole set.

**Switch model or provider.** Environment only: `LLM_PROVIDER`, `LLM_MODEL`, `OPENAI_BASE_URL`. Run the exam on the
new model before trusting it.

**Change the step limit.** `MAX_STEPS` (1-20). Fewer steps: cheaper and faster, more fallbacks. Measure it.

**Improve Arabic search.** Write a new class with the same `embed(text) -> list[float]` method (a multilingual
embedding model), plug it where `HashingEmbedder` is created, and compare recall@3 on `evals/retrieval.jsonl`.
Note: a different vector size needs the `Embedding` dimension changed in `db.py`.

---

## 9. When something breaks

| Symptom | Likely cause | Fix |
|---|---|---|
| `503 LLM not configured` | no `LLM_MODEL` or no key | set `LLM_MODEL` and the provider's key |
| `429 Rate limit exceeded: free-models-per-day` | OpenRouter free daily cap (50/day, or 1,000/day with ≥10 credits bought; 20/minute) | wait for the daily reset (00:00 UTC), use another model, or a paid model |
| `429 … temporarily rate-limited upstream` | that free model is busy | try another free model |
| Postgres tests error with `Connect call failed` | the database is not running | start Postgres (`pg_ctlcluster 16 main start` on Ubuntu, or `docker compose up db`) |
| `expected list or ndarray` from asyncpg | a vector codec registered on the connection | don't register one; this project sends vectors as text on purpose (see `make_engine`) |
| agent stops with `max_steps` | the model loops (common with weak models) | read the step diary; a better model, a clearer tool description, or a prompt rule |
| `violation: …ticket … no tool returned` | the model mentioned a ticket that does not exist | working as designed: the guard caught it |
| stop reason `repeated_calls` | the model kept repeating the same call | working as designed; read the steps, and if a task legitimately needs repeats, give the tool a different argument (e.g. a time) |
| a task fails but the agent looks right | the exam may be wrong | read the answer and the tools; fix the task if needed (section 6) |
| `UV_NATIVE_TLS is deprecated` warning | an environment variable in this machine | harmless; `unset UV_NATIVE_TLS` |

Debugging habit: look at the **steps** first (tools, arguments, results), then the final answer. Every run is in the
`agent_runs` and `tool_calls` tables, and every exam run is a JSON file.

---

## 10. Why it is built this way

Short version (full records in `docs/DECISIONS.md`):

- **Hand-written loop, no framework.** To understand and show the mechanism, test every step with a fake model, and
  put guards exactly where they belong. The cost: no ready-made tracing dashboard or memory. For a team project, a
  framework (LangGraph, OpenAI Agents SDK, Pydantic AI, CrewAI) or a cloud platform (Amazon Bedrock AgentCore,
  Microsoft Foundry, Google's Gemini Enterprise Agent Platform) may be the better choice, which is why the next step
  rebuilds the same agent with them and measures.
- **Narrow, not general.** Coding agents like Claude Code or Codex have dozens of tools and a trusted user watching.
  A helpdesk agent talks to many untrusted users, so: few tools, one job, hard limits.
- **Dangerous actions wait for a person.** The model can ask; it cannot do.
- **Measure first, then improve.** A simple search baseline, measured, so improvements are proven.
- **Exams check actions, not words.** What the agent did is reliable to check; what it said is not.
- **Provider-agnostic.** Any model behind one interface; free models via OpenRouter for the exams.

---

## 11. How to explain it to people

**In one sentence.** "I built an AI agent that handles IT support in Arabic and English: the model chooses tools, my
code checks and runs them, risky actions wait for a person, and an exam measures how often it gets it right."

**In 30 seconds.** "A chatbot answers; an agent acts. Mine reads our IT guides, checks whether systems are really
down, opens tickets, and can request a restart that a human approves. I wrote the loop myself so every step is
testable, and I gave it a 24-task exam that it can fail, including a fake 'I'm the CEO, restart now' message."

**In two minutes:** follow section 4 with the "mail is down" example, then the three exam mistakes (section 6).

**Questions people ask, and good answers.**
- *Why not just use LangChain?* "To learn and prove the mechanism, and to test every step. For a team I'd consider
  LangGraph or a cloud platform, and I'm rebuilding the same agent with them to compare on the same exam."
- *How do you stop it doing something dangerous?* "It can't. The dangerous tool only writes a request; a person
  approves it. And every tool input is validated before anything runs."
- *What about prompt injection?* "Text from documents is passed as data, the prompt says tool results aren't
  instructions, and even if the model obeyed, the code limits what it can do. The exam has an injection test."
- *How do you know it works?* "An exam of 24 tasks that checks actions, on a fresh database with real services up or
  down. And I tested the exam itself: I found and fixed three mistakes in it."
- *Is it production-ready?* "No: single-turn, a baseline search, no executor for approved actions, no auth. It's a
  measured foundation; the roadmap covers the rest."
- *What does it cost?* "The exams ran on free models. Each run logs tokens, so cost per task is measurable on any
  paid model."
- *Hallucinations?* "The answer is checked: ticket numbers must come from a tool, and steps must come from the
  guides it retrieved."

---

## 12. How the videos and graphics were made

These live in the lab repository (`ClaudeUse`), not in this project.
- **Terminal takes:** `tools/termrec.sh <out.cast> <commands.txt>` types each command on screen and really runs it
  (asciinema recording), then `tools/castvid.py <cast> <out.mp4>` draws the frames (pyte terminal emulator + Pillow,
  Arabic shaped correctly) and encodes with FFmpeg.
- **Browser take:** a Playwright script (`briefs/agentic-helpdesk/recordings/browser-take.cjs`) drives the API page
  with a drawn cursor and records video.
- **Final cut:** `briefs/agentic-helpdesk/edit.py`: title card, the takes with captions, waiting sped up and labelled,
  end card, music, loudness −14 LUFS.
- **Diagrams and carousels:** hand-drawn SVG in HTML pages, rendered to PNG and PDF with Playwright.

---

## 13. What comes next

1. A clean, repeated exam run on several free models (`--repeat 3`), recorded.
2. **The same agent, four ways:** hand-written (done), LangGraph, Amazon Bedrock AgentCore, Microsoft Foundry
   published to Teams; the same 24-task exam on each; compare success, cost, speed, lines of code, ease of testing.
3. **MCP server** exposing the same tools (read-only vs approval), so other AI apps can use them.
4. **A2A** hand-off to a specialist agent (e.g. a server/SRE agent).
5. **Conversation memory** (follow-up messages).
6. **Better Arabic search**: a multilingual embedding model vs the baseline, measured.
7. **Deploy on AWS** (EC2, IAM role, CloudWatch logs and cost per task), and a public demo.
