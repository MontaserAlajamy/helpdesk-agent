"""The agent's tools: typed arguments (Pydantic), a risk level, and an async implementation.

Risk levels:
  read       looks things up, safe to run any time
  write      creates records (tickets)
  dangerous  changes live systems: never executed by the agent, only queued for a human (PendingAction)
"""

from __future__ import annotations

import asyncio
import json
import time
from collections.abc import Awaitable, Callable
from dataclasses import dataclass, field
from typing import Any, Literal
from urllib.parse import urlparse

import httpx
from pydantic import BaseModel, Field, ValidationError
from sqlalchemy.ext.asyncio import async_sessionmaker

from . import runbooks
from .db import PendingAction, Ticket
from .embeddings import Embedder

Risk = Literal["read", "write", "dangerous"]
Priority = Literal["low", "medium", "high", "critical"]
Category = Literal["network", "email", "hardware", "software", "access", "voip", "server", "other"]


@dataclass
class ToolContext:
    sessions: async_sessionmaker
    embedder: Embedder
    services: dict[str, str]
    run_id: str = ""
    check_timeout_s: float = 3.0
    owner: str | None = None  # demo visitor session: tickets and actions are stamped with it and only it sees them
    # ids of tickets this run created or read: the final answer may only cite these
    seen_ticket_ids: set[int] = field(default_factory=set)
    pending_action_ids: list[int] = field(default_factory=list)


class SearchRunbooksArgs(BaseModel):
    query: str = Field(min_length=2, max_length=300, description="What the user's problem is about, in any language")
    k: int = Field(default=3, ge=1, le=5)


class CheckServiceArgs(BaseModel):
    name: str = Field(description="Service name exactly as listed in this tool's description")


class CreateTicketArgs(BaseModel):
    title: str = Field(min_length=5, max_length=120)
    description: str = Field(min_length=10, max_length=2000, description="What the user reported and what was tried")
    priority: Priority
    category: Category


class GetTicketArgs(BaseModel):
    ticket_id: int = Field(ge=1)


class RestartServiceArgs(BaseModel):
    name: str = Field(description="Service name exactly as listed in check_service")
    reason: str = Field(min_length=10, max_length=500, description="Evidence that a restart is needed")


class FinalAnswerArgs(BaseModel):
    """The agent's structured reply to the user. Calling it ends the run."""

    answer: str = Field(min_length=1, max_length=3000, description="The reply to the user, in the user's language")
    language: Literal["ar", "en"]
    ticket_id: int | None = Field(default=None, description="Only a ticket id returned by a tool in this conversation")
    needs_human: bool = Field(description="True if a person must act (ticket opened, approval waiting, or unsure)")


@dataclass(frozen=True)
class Tool:
    name: str
    description: str
    args_model: type[BaseModel]
    risk: Risk
    fn: Callable[[ToolContext, Any], Awaitable[dict[str, Any]]]

    def schema(self) -> dict[str, Any]:
        return {"name": self.name, "description": self.description, "parameters": self.args_model.model_json_schema()}


# ---------------------------------------------------------------- implementations


async def search_runbooks(ctx: ToolContext, a: SearchRunbooksArgs) -> dict[str, Any]:
    async with ctx.sessions() as s:
        hits = await runbooks.search(s, a.query, ctx.embedder, k=a.k)
    return {
        "results": [
            {"id": h.id, "title": h.title, "category": h.category, "score": round(h.score, 3), "content": h.content}
            for h in hits
        ]
    }


async def check_service(ctx: ToolContext, a: CheckServiceArgs) -> dict[str, Any]:
    url = ctx.services.get(a.name)
    if url is None:
        raise ToolError(f"unknown service {a.name!r}; known: {sorted(ctx.services)}")
    parsed = urlparse(url)
    t0 = time.perf_counter()
    try:
        if parsed.scheme == "tcp":
            conn = asyncio.open_connection(parsed.hostname, parsed.port)
            _, writer = await asyncio.wait_for(conn, timeout=ctx.check_timeout_s)
            writer.close()
            await writer.wait_closed()
            detail = "port open"
            up = True
        else:
            async with httpx.AsyncClient(timeout=ctx.check_timeout_s) as client:
                r = await client.get(url)
            up = r.status_code < 500
            detail = f"HTTP {r.status_code}"
    except (OSError, TimeoutError, httpx.HTTPError) as e:
        up, detail = False, f"{type(e).__name__}: {e}"[:200]
    return {"service": a.name, "status": "up" if up else "down", "detail": detail,
            "latency_ms": round((time.perf_counter() - t0) * 1000, 1)}


async def create_ticket(ctx: ToolContext, a: CreateTicketArgs) -> dict[str, Any]:
    async with ctx.sessions() as s:
        t = Ticket(title=a.title, description=a.description, priority=a.priority, category=a.category,
                   owner=ctx.owner)
        s.add(t)
        await s.commit()
        ctx.seen_ticket_ids.add(t.id)
        return {"ticket_id": t.id, "status": t.status, "priority": t.priority}


async def get_ticket(ctx: ToolContext, a: GetTicketArgs) -> dict[str, Any]:
    async with ctx.sessions() as s:
        t = await s.get(Ticket, a.ticket_id)
    if t is None or (ctx.owner is not None and t.owner != ctx.owner):
        raise ToolError(f"ticket {a.ticket_id} not found")
    ctx.seen_ticket_ids.add(t.id)
    return {"ticket_id": t.id, "title": t.title, "status": t.status, "priority": t.priority,
            "category": t.category, "created_at": t.created_at.isoformat()}


async def restart_service(ctx: ToolContext, a: RestartServiceArgs) -> dict[str, Any]:
    if a.name not in ctx.services:
        raise ToolError(f"unknown service {a.name!r}; known: {sorted(ctx.services)}")
    async with ctx.sessions() as s:
        act = PendingAction(run_id=ctx.run_id, tool="restart_service", args=a.model_dump(), owner=ctx.owner)
        s.add(act)
        await s.commit()
        ctx.pending_action_ids.append(act.id)
        return {"status": "pending_approval", "action_id": act.id,
                "note": "Nothing was restarted. A human must approve this action."}


class ToolError(Exception):
    """An error the model should see and can recover from."""


def build_tools(services: dict[str, str]) -> dict[str, Tool]:
    names = ", ".join(sorted(services)) or "(none configured)"
    tools = [
        Tool("search_runbooks", "Search the IT runbooks (troubleshooting guides). Use it before giving any fix steps.",
             SearchRunbooksArgs, "read", search_runbooks),
        Tool("check_service", f"Check whether an internal service is up right now. Known services: {names}.",
             CheckServiceArgs, "read", check_service),
        Tool("create_ticket", "Open a support ticket for a person to handle. Use it when self-service steps are not "
             "enough, the user asks for one, or a service is down.", CreateTicketArgs, "write", create_ticket),
        Tool("get_ticket", "Look up an existing ticket by its number.", GetTicketArgs, "read", get_ticket),
        Tool("restart_service", "Request a restart of a service. This does NOT restart anything: it queues the "
             "request for a human to approve. Only use it when check_service showed the service is down.",
             RestartServiceArgs, "dangerous", restart_service),
    ]
    return {t.name: t for t in tools}


FINAL_ANSWER = Tool("final_answer", "Send the final reply to the user. Always end with this tool.",
                    FinalAnswerArgs, "read", None)  # type: ignore[arg-type]


@dataclass
class ToolResult:
    ok: bool
    content: str  # JSON text shown to the model
    data: dict[str, Any] | None
    latency_ms: float


async def execute(tool: Tool, raw_args: dict[str, Any], ctx: ToolContext) -> ToolResult:
    """Validate the model's arguments, run the tool, never raise: errors go back to the model."""
    t0 = time.perf_counter()
    try:
        args = tool.args_model.model_validate(raw_args)
        data = await tool.fn(ctx, args)
        ok, content = True, json.dumps(data, ensure_ascii=False)
    except ValidationError as e:
        data, ok = None, False
        errs = [{"field": ".".join(map(str, er["loc"])), "error": er["msg"]} for er in e.errors()]
        content = json.dumps({"error": "invalid arguments", "details": errs}, ensure_ascii=False)
    except ToolError as e:
        data, ok = None, False
        content = json.dumps({"error": str(e)}, ensure_ascii=False)
    return ToolResult(ok, content, data, round((time.perf_counter() - t0) * 1000, 1))
