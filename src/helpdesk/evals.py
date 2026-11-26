"""Evals that can fail.

  python -m helpdesk.evals retrieval [--min-recall3 0.8]     no model needed: runbook search quality
  python -m helpdesk.evals agent --provider anthropic --model <id> [--min-success 0.8] [--repeat 1]

The agent eval runs every task on a fresh database against real local services (one HTTP server and one TCP
port that are up, one closed port that is down), checks what the agent DID (tool calls, ticket fields,
pending actions, language, leaked text), and exits 1 below the threshold. Results go to evals/results/.
"""

from __future__ import annotations

import argparse
import asyncio
import json
import statistics
import sys
import tempfile
import time
from collections import defaultdict
from dataclasses import asdict, dataclass, field
from pathlib import Path
from typing import Any

from . import runbooks
from .agent import AgentRun, run_agent
from .db import create_schema, make_engine, make_sessionmaker
from .embeddings import HashingEmbedder
from .llm import LLM, build_llm
from .tools import ToolContext, build_tools

ROOT = Path(__file__).resolve().parents[2]
EVAL_DIR = ROOT / "evals"
RUNBOOK_DIR = ROOT / "data" / "runbooks"


def read_jsonl(path: Path) -> list[dict[str, Any]]:
    return [json.loads(ln) for ln in path.read_text(encoding="utf-8").splitlines() if ln.strip()]


# ------------------------------------------------------------------ retrieval


async def eval_retrieval(cases: list[dict[str, Any]], dim: int = 256) -> dict[str, Any]:
    with tempfile.TemporaryDirectory() as tmp:
        engine = make_engine(f"sqlite+aiosqlite:///{tmp}/r.db")
        await create_schema(engine)
        sessions = make_sessionmaker(engine)
        emb = HashingEmbedder(dim)
        async with sessions() as s:
            await runbooks.seed(s, runbooks.load_dir(RUNBOOK_DIR), emb)
            by_lang: dict[str, list[tuple[bool, bool]]] = defaultdict(list)
            misses = []
            for c in cases:
                ids = [h.id for h in await runbooks.search(s, c["q"], emb, k=3)]
                r1, r3 = ids[:1] == [c["expect"]], c["expect"] in ids
                by_lang[c["lang"]].append((r1, r3))
                if not r3:
                    misses.append({"q": c["q"], "expect": c["expect"], "got": ids})
        await engine.dispose()

    def rate(rows, i):
        return round(sum(r[i] for r in rows) / len(rows), 3) if rows else 0.0

    allrows = [r for rows in by_lang.values() for r in rows]
    return {
        "embedder": f"hashing-{dim}", "n": len(allrows),
        "recall@1": rate(allrows, 0), "recall@3": rate(allrows, 1),
        "by_lang": {lg: {"n": len(rows), "recall@1": rate(rows, 0), "recall@3": rate(rows, 1)}
                    for lg, rows in sorted(by_lang.items())},
        "misses": misses,
    }


# ------------------------------------------------------------------ agent


@dataclass
class TaskResult:
    id: str
    passed: bool
    failures: list[str]
    tools: list[str]
    stop_reason: str
    steps: int
    invalid_tool_calls: int
    input_tokens: int
    output_tokens: int
    latency_ms: float
    answer: str = ""
    violations: list[str] = field(default_factory=list)
    repairs: list[str] = field(default_factory=list)


def score_task(task: dict[str, Any], run: AgentRun) -> list[str]:
    """Return the list of failed checks (empty = pass)."""
    fails: list[str] = []
    called = set(run.tools_called)
    for t in task.get("must_call", []):
        if t not in called:
            fails.append(f"did not call {t}")
    for t in task.get("must_not_call", []):
        if t in called:
            fails.append(f"called forbidden {t}")
    tickets = [s for s in run.steps if s.tool == "create_ticket" and s.ok]
    if "ticket" in task and task["ticket"] is not None and bool(tickets) != task["ticket"]:
        fails.append(f"ticket expected={task['ticket']} got={bool(tickets)}")
    if tickets:
        args = tickets[-1].args
        if "priority_in" in task and args.get("priority") not in task["priority_in"]:
            fails.append(f"priority {args.get('priority')} not in {task['priority_in']}")
        if "category_in" in task and args.get("category") not in task["category_in"]:
            fails.append(f"category {args.get('category')} not in {task['category_in']}")
    reply = run.reply
    if run.stop_reason != "final_answer":
        fails.append(f"stopped: {run.stop_reason}")
    if reply is not None:
        if "language" in task and reply.language != task["language"]:
            fails.append(f"language {reply.language} != {task['language']}")
        if "needs_human" in task and reply.needs_human != task["needs_human"]:
            fails.append(f"needs_human {reply.needs_human} != {task['needs_human']}")
        low = reply.answer.lower()
        for bad in task.get("answer_must_not_contain", []):
            if bad.lower() in low:
                fails.append(f"answer contains {bad!r}")
    if run.violations:
        fails += [f"violation: {v}" for v in run.violations]
    return fails


class LocalServices:
    """Real endpoints for check_service: intranet (HTTP 200), pbx and mail (TCP open). A task lists the services
    that are down for it ("down": ["mail"]); those point at a closed port instead."""

    async def __aenter__(self) -> dict[str, str]:
        async def http_ok(reader, writer):
            await reader.read(1024)
            writer.write(b"HTTP/1.1 200 OK\r\nContent-Length: 2\r\nConnection: close\r\n\r\nok")
            await writer.drain()
            writer.close()

        async def tcp_ok(reader, writer):
            writer.close()

        self.http = await asyncio.start_server(http_ok, "127.0.0.1", 0)
        self.tcp = await asyncio.start_server(tcp_ok, "127.0.0.1", 0)
        closed = await asyncio.start_server(tcp_ok, "127.0.0.1", 0)
        closed_port = closed.sockets[0].getsockname()[1]
        closed.close()
        await closed.wait_closed()
        self.down_url = f"tcp://127.0.0.1:{closed_port}"
        tcp_url = f"tcp://127.0.0.1:{self.tcp.sockets[0].getsockname()[1]}"
        return {
            "intranet": f"http://127.0.0.1:{self.http.sockets[0].getsockname()[1]}/healthz",
            "pbx": tcp_url,
            "mail": tcp_url,
        }

    def for_task(self, services: dict[str, str], task: dict[str, Any]) -> dict[str, str]:
        down = set(task.get("down", []))
        return {name: (self.down_url if name in down else url) for name, url in services.items()}

    async def __aexit__(self, *exc) -> None:
        for srv in (self.http, self.tcp):
            srv.close()
            await srv.wait_closed()


async def run_one(task: dict[str, Any], llm: LLM, services: dict[str, str], max_steps: int) -> TaskResult:
    with tempfile.TemporaryDirectory() as tmp:
        engine = make_engine(f"sqlite+aiosqlite:///{tmp}/a.db")
        await create_schema(engine)
        sessions = make_sessionmaker(engine)
        emb = HashingEmbedder(256)
        async with sessions() as s:
            await runbooks.seed(s, runbooks.load_dir(RUNBOOK_DIR), emb)
        ctx = ToolContext(sessions, emb, services, check_timeout_s=1.0)
        try:
            run = await run_agent(task["message"], llm, build_tools(services), ctx, max_steps=max_steps)
        finally:
            await engine.dispose()
    fails = score_task(task, run)
    return TaskResult(
        id=task["id"], passed=not fails, failures=fails, tools=run.tools_called, stop_reason=run.stop_reason,
        steps=len(run.steps), invalid_tool_calls=sum(1 for s in run.steps if not s.ok),
        input_tokens=run.usage.input_tokens, output_tokens=run.usage.output_tokens, latency_ms=run.latency_ms,
        answer=run.reply.answer if run.reply else "", violations=run.violations, repairs=run.repairs,
    )


async def eval_agent(tasks: list[dict[str, Any]], llm: LLM, repeat: int = 1, max_steps: int = 6,
                     concurrency: int = 4) -> dict[str, Any]:
    sem = asyncio.Semaphore(concurrency)
    local = LocalServices()
    async with local as services:

        async def guarded(task):
            async with sem:
                try:
                    return await run_one(task, llm, local.for_task(services, task), max_steps)
                except Exception as e:  # an API error is a failed task, not a crashed eval
                    return TaskResult(task["id"], False, [f"error: {type(e).__name__}: {e}"[:300]], [], "error",
                                      0, 0, 0, 0, 0.0)

        results = await asyncio.gather(*(guarded(t) for t in tasks for _ in range(repeat)))
    n = len(results)
    lat = [r.latency_ms for r in results if r.stop_reason != "error"] or [0.0]
    return {
        "model": llm.name, "tasks": len(tasks), "repeat": repeat, "runs": n,
        "success_rate": round(sum(r.passed for r in results) / n, 3),
        "invalid_tool_call_rate": round(
            sum(r.invalid_tool_calls for r in results) / max(1, sum(r.steps for r in results)), 3),
        "forbidden_tool_calls": sum(1 for r in results for f in r.failures if f.startswith("called forbidden")),
        "violations": sum(len(r.violations) for r in results),
        "text_vs_field_repairs": sum(len(r.repairs) for r in results),
        "avg_steps": round(statistics.mean(r.steps for r in results), 2),
        "avg_input_tokens": round(statistics.mean(r.input_tokens for r in results)),
        "avg_output_tokens": round(statistics.mean(r.output_tokens for r in results)),
        "p50_latency_ms": round(statistics.median(lat)),
        "p95_latency_ms": round(sorted(lat)[max(0, int(len(lat) * 0.95) - 1)]),
        "results": [asdict(r) for r in results],
    }


def compare_table(since: str = "") -> str:
    latest: dict[str, dict[str, Any]] = {}
    for path in sorted((EVAL_DIR / "results").glob("*-agent-*.json")):
        if path.name >= since:
            rep = json.loads(path.read_text(encoding="utf-8"))
            latest[rep["model"]] = rep
    rows = sorted(latest.values(), key=lambda r: -r["success_rate"])
    head = "| model | success | forbidden calls | invented tickets | bad tool args | steps | tokens in/out | p50 s |"
    lines = [head, "|" + "---|" * 8]
    for r in rows:
        lines.append(
            f"| {r['model'].split(':', 1)[1]} | {r['success_rate']:.0%} "
            f"({round(r['success_rate'] * r['runs'])}/{r['runs']}) "
            f"| {r['forbidden_tool_calls']} | {r['violations']} | {r['invalid_tool_call_rate']:.1%} | {r['avg_steps']} "
            f"| {r['avg_input_tokens']}/{r['avg_output_tokens']} | {r['p50_latency_ms'] / 1000:.1f} |"
        )
    return "\n".join(lines)


# ------------------------------------------------------------------ CLI


def _save(kind: str, label: str, report: dict[str, Any]) -> Path:
    out = EVAL_DIR / "results"
    out.mkdir(parents=True, exist_ok=True)
    safe = "".join(ch if ch.isalnum() or ch in "-_." else "-" for ch in label)
    path = out / f"{time.strftime('%Y%m%d-%H%M%S')}-{kind}-{safe}.json"
    path.write_text(json.dumps(report, ensure_ascii=False, indent=2), encoding="utf-8")
    return path


def main(argv: list[str] | None = None) -> int:
    ap = argparse.ArgumentParser(prog="python -m helpdesk.evals")
    sub = ap.add_subparsers(dest="kind", required=True)
    r = sub.add_parser("retrieval")
    r.add_argument("--min-recall3", type=float, default=0.0)
    a = sub.add_parser("agent")
    a.add_argument("--provider", default="anthropic")
    a.add_argument("--model", required=True)
    a.add_argument("--base-url")
    a.add_argument("--repeat", type=int, default=1)
    a.add_argument("--only", help="comma-separated task ids")
    a.add_argument("--min-success", type=float, default=0.0)
    a.add_argument("--concurrency", type=int, default=4)
    c = sub.add_parser("compare", help="table of the latest agent result per model")
    c.add_argument("--since", default="", help="only result files whose name sorts at or after this (e.g. 20261126)")
    args = ap.parse_args(argv)

    if args.kind == "compare":
        print(compare_table(args.since))
        return 0

    if args.kind == "retrieval":
        rep = asyncio.run(eval_retrieval(read_jsonl(EVAL_DIR / "retrieval.jsonl")))
        path = _save("retrieval", rep["embedder"], rep)
        print(f"retrieval {rep['embedder']}: n={rep['n']} recall@1={rep['recall@1']} recall@3={rep['recall@3']}")
        for lg, v in rep["by_lang"].items():
            print(f"  {lg}: n={v['n']} recall@1={v['recall@1']} recall@3={v['recall@3']}")
        for m in rep["misses"]:
            print(f"  miss: {m['q']!r} expected {m['expect']} got {m['got']}")
        print(f"saved {path}")
        ok = rep["recall@3"] >= args.min_recall3
    else:
        tasks = read_jsonl(EVAL_DIR / "tasks.jsonl")
        if args.only:
            keep = set(args.only.split(","))
            tasks = [t for t in tasks if t["id"] in keep]
        llm = build_llm(args.provider, args.model, args.base_url)
        rep = asyncio.run(eval_agent(tasks, llm, repeat=args.repeat, concurrency=args.concurrency))
        path = _save("agent", llm.name, rep)
        keys = ["success_rate", "invalid_tool_call_rate", "forbidden_tool_calls", "violations", "text_vs_field_repairs",
                "avg_steps",
                "avg_input_tokens", "avg_output_tokens", "p50_latency_ms", "p95_latency_ms"]
        print(f"agent {rep['model']}: runs={rep['runs']} " + " ".join(f"{k}={rep[k]}" for k in keys))
        for res in rep["results"]:
            if not res["passed"]:
                print(f"  FAIL {res['id']}: {'; '.join(res['failures'])}  tools={res['tools']}")
        print(f"saved {path}")
        ok = rep["success_rate"] >= args.min_success
    if not ok:
        print("GATE FAILED", file=sys.stderr)
    return 0 if ok else 1


if __name__ == "__main__":
    sys.exit(main())
