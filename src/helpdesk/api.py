"""FastAPI service: chat with the agent (plain or streamed), read tickets, approve or reject queued actions.

With DEMO_MODE=1 it is a public "try it" demo: simulated local services that a visitor can switch off, every
visitor sees only their own tickets and actions (X-Demo-Session), and in-memory abuse limits.
"""

import asyncio
import json
import re
import time
from collections import deque
from collections.abc import AsyncIterator, Callable
from contextlib import asynccontextmanager
from datetime import datetime
from pathlib import Path
from typing import Annotated, Any, Literal

from fastapi import Depends, FastAPI, HTTPException, Request
from fastapi.responses import StreamingResponse
from fastapi.staticfiles import StaticFiles
from pydantic import BaseModel, Field
from sqlalchemy import select

from . import __version__, runbooks
from .agent import AgentRun, run_agent
from .config import Settings
from .db import (
    AgentRunRow,
    PendingAction,
    Ticket,
    ToolCallRow,
    create_schema,
    make_engine,
    make_sessionmaker,
    utcnow,
)
from .embeddings import HashingEmbedder
from .llm import LLM, build_llm
from .localservices import LocalServices
from .tools import FinalAnswerArgs, ToolContext, build_tools

RUNBOOK_DIR = Path(__file__).resolve().parents[2] / "data" / "runbooks"
WEB_DIR = Path(__file__).resolve().parent / "web"
DEMO_MAX_MESSAGE = 500
SESSION_RE = re.compile(r"[A-Za-z0-9_-]{8,64}")


class ChatRequest(BaseModel):
    message: str = Field(min_length=1, max_length=4000)
    down: list[str] = Field(default_factory=list, max_length=10,
                            description="Demo mode only: names of simulated services to take down for this request")


class RateLimiter:
    """In-memory sliding windows: per client IP per hour, and a global cap per day. `clock` is injectable."""

    def __init__(self, per_ip: int = 12, per_ip_window_s: float = 3600, global_cap: int = 300,
                 global_window_s: float = 86400, clock: Callable[[], float] = time.monotonic) -> None:
        self.per_ip, self.per_ip_window_s = per_ip, per_ip_window_s
        self.global_cap, self.global_window_s = global_cap, global_window_s
        self.clock = clock
        self.by_ip: dict[str, deque[float]] = {}
        self.all: deque[float] = deque()

    def hit(self, ip: str) -> str | None:
        """Count one chat for `ip`; return a friendly refusal instead when a limit is reached."""
        now = self.clock()
        while self.all and now - self.all[0] >= self.global_window_s:
            self.all.popleft()
        q = self.by_ip.setdefault(ip, deque())
        while q and now - q[0] >= self.per_ip_window_s:
            q.popleft()
        if len(self.all) >= self.global_cap:
            return "The demo has answered all the questions it can for today. Please come back tomorrow."
        if len(q) >= self.per_ip:
            wait = max(1, round((self.per_ip_window_s - (now - q[0])) / 60))
            return (f"You have sent {self.per_ip} messages this hour, the most this demo allows. "
                    f"Please try again in about {wait} min.")
        q.append(now)
        self.all.append(now)
        if len(self.by_ip) > 10000:  # drop idle IPs so the dict cannot grow without bound
            self.by_ip = {k: v for k, v in self.by_ip.items() if v}
        return None


def client_ip(request: Request) -> str:
    fwd = request.headers.get("x-forwarded-for", "")
    first = fwd.split(",")[0].strip()
    return first or (request.client.host if request.client else "unknown")


class StepOut(BaseModel):
    tool: str
    args: dict
    ok: bool


class ChatResponse(BaseModel):
    run_id: str
    reply: FinalAnswerArgs
    stop_reason: str
    steps: list[StepOut]
    pending_action_ids: list[int]
    input_tokens: int
    output_tokens: int
    latency_ms: float


class TicketOut(BaseModel):
    id: int
    title: str
    description: str
    priority: str
    category: str
    status: str
    created_at: datetime


class ActionOut(BaseModel):
    id: int
    run_id: str
    tool: str
    args: dict
    status: Literal["pending", "approved", "rejected"]
    created_at: datetime
    decided_at: datetime | None


def create_app(settings: Settings | None = None, llm: LLM | None = None,
               limiter: RateLimiter | None = None) -> FastAPI:
    settings = settings or Settings.from_env()
    limiter = limiter or RateLimiter()

    @asynccontextmanager
    async def lifespan(app: FastAPI) -> AsyncIterator[None]:
        engine = make_engine(settings.database_url)
        await create_schema(engine)
        sessions = make_sessionmaker(engine)
        embedder = HashingEmbedder(settings.embed_dim)
        async with sessions() as s:
            if await runbooks.count(s) == 0 and RUNBOOK_DIR.exists():
                await runbooks.seed(s, runbooks.load_dir(RUNBOOK_DIR), embedder)
            guides = await runbooks.count(s)
        local: LocalServices | None = None
        services = settings.services
        if settings.demo_mode:  # real listeners on localhost; a visitor's "down" switch points one at a closed port
            local = LocalServices()
            services = await local.__aenter__()
        app.state.sessions = sessions
        app.state.embedder = embedder
        app.state.local = local
        app.state.services = services
        app.state.tools = build_tools(services)
        app.state.guides = guides
        app.state.llm = llm  # built lazily so the API starts without a key
        try:
            yield
        finally:
            if local is not None:
                await local.__aexit__(None, None, None)
            await engine.dispose()

    app = FastAPI(title="Helpdesk Agent", version=__version__, lifespan=lifespan)

    def get_llm(request: Request) -> LLM:
        if request.app.state.llm is None:
            try:
                request.app.state.llm = build_llm(settings.llm_provider, settings.llm_model, settings.openai_base_url)
            except Exception as e:  # missing key or model
                raise HTTPException(503, f"LLM not configured: {e}") from e
        return request.app.state.llm

    @app.get("/healthz")
    async def healthz() -> dict:
        return {"status": "ok", "version": __version__}

    def get_owner(request: Request) -> str | None:
        """Demo mode: the visitor's session id (X-Demo-Session). Outside demo mode: None (no isolation)."""
        if not settings.demo_mode:
            return None
        sid = request.headers.get("x-demo-session", "")
        if not SESSION_RE.fullmatch(sid):
            raise HTTPException(400, "Missing or invalid X-Demo-Session header (8-64 letters, digits, - or _).")
        return sid

    Owner = Annotated[str | None, Depends(get_owner)]

    def start_run(body: ChatRequest, request: Request, owner: str | None) -> ToolContext:
        """Checks that apply before any model call; returns the context for this one run."""
        st = request.app.state
        services = st.services
        if settings.demo_mode:
            if len(body.message) > DEMO_MAX_MESSAGE:
                raise HTTPException(422, f"Please keep demo messages under {DEMO_MAX_MESSAGE} characters.")
            refusal = limiter.hit(client_ip(request))
            if refusal:
                raise HTTPException(429, refusal)
            services = st.local.with_down(services, [d for d in body.down if d in services])
        # the tools' descriptions only list service names, which "down" does not change: st.tools still fits
        return ToolContext(st.sessions, st.embedder, services, check_timeout_s=settings.check_timeout_s, owner=owner)

    @app.post("/v1/chat", response_model=ChatResponse)
    async def chat(body: ChatRequest, request: Request, llm: Annotated[LLM, Depends(get_llm)],
                   owner: Owner) -> ChatResponse:
        st = request.app.state
        ctx = start_run(body, request, owner)
        run = await run_agent(body.message, llm, st.tools, ctx, max_steps=settings.max_steps)
        await _save_run(st.sessions, body.message, run)
        return ChatResponse(
            run_id=run.run_id, reply=run.reply, stop_reason=run.stop_reason,
            steps=[StepOut(tool=s.tool, args=s.args, ok=s.ok) for s in run.steps],
            pending_action_ids=ctx.pending_action_ids,
            input_tokens=run.usage.input_tokens, output_tokens=run.usage.output_tokens, latency_ms=run.latency_ms,
        )

    @app.post("/v1/chat/stream")
    async def chat_stream(body: ChatRequest, request: Request, llm: Annotated[LLM, Depends(get_llm)],
                          owner: Owner) -> StreamingResponse:
        """Server-Sent Events: model_turn, tool, final as they happen, then done (or error)."""
        st = request.app.state
        ctx = start_run(body, request, owner)
        queue: asyncio.Queue[dict[str, Any] | None] = asyncio.Queue()

        async def work() -> None:
            try:
                run = await run_agent(body.message, llm, st.tools, ctx, max_steps=settings.max_steps,
                                      on_event=queue.put)
                await _save_run(st.sessions, body.message, run)
                await queue.put({"type": "done", "run_id": run.run_id, "input_tokens": run.usage.input_tokens,
                                 "output_tokens": run.usage.output_tokens, "latency_ms": run.latency_ms,
                                 "pending_action_ids": ctx.pending_action_ids})
            except Exception as e:  # a provider error ends the stream with an honest message
                await queue.put({"type": "error", "detail": f"The model call failed: {type(e).__name__}: {e}"[:300]})
            finally:
                await queue.put(None)

        async def events() -> AsyncIterator[str]:
            task = asyncio.create_task(work())
            try:
                while (event := await queue.get()) is not None:
                    yield f"event: {event['type']}\ndata: {json.dumps(event, ensure_ascii=False, default=str)}\n\n"
            finally:
                if not task.done():
                    task.cancel()

        return StreamingResponse(events(), media_type="text/event-stream",
                                 headers={"Cache-Control": "no-cache", "X-Accel-Buffering": "no"})

    @app.get("/v1/meta")
    async def meta(request: Request) -> dict:
        model = "fake (offline demo)" if settings.llm_provider == "fake" else settings.llm_model
        return {"demo": settings.demo_mode, "model": model, "services": sorted(request.app.state.services),
                "max_steps": settings.max_steps, "tools": len(request.app.state.tools) + 1,
                "guides": request.app.state.guides, "version": __version__}

    @app.get("/v1/tickets", response_model=list[TicketOut])
    async def list_tickets(request: Request, owner: Owner, status: str | None = None) -> list[Ticket]:
        async with request.app.state.sessions() as s:
            stmt = select(Ticket).order_by(Ticket.id.desc())
            if status:
                stmt = stmt.where(Ticket.status == status)
            if owner is not None:
                stmt = stmt.where(Ticket.owner == owner)
            return list((await s.execute(stmt)).scalars())

    @app.get("/v1/tickets/{ticket_id}", response_model=TicketOut)
    async def read_ticket(ticket_id: int, request: Request, owner: Owner) -> Ticket:
        async with request.app.state.sessions() as s:
            t = await s.get(Ticket, ticket_id)
        if t is None or (owner is not None and t.owner != owner):
            raise HTTPException(404, "ticket not found")
        return t

    @app.get("/v1/actions", response_model=list[ActionOut])
    async def list_actions(request: Request, owner: Owner, status: str = "pending") -> list[PendingAction]:
        async with request.app.state.sessions() as s:
            stmt = select(PendingAction).order_by(PendingAction.id)
            if status != "all":
                stmt = stmt.where(PendingAction.status == status)
            if owner is not None:
                stmt = stmt.where(PendingAction.owner == owner)
            return list((await s.execute(stmt)).scalars())

    @app.post("/v1/actions/{action_id}/{decision}", response_model=ActionOut)
    async def decide(action_id: int, decision: Literal["approve", "reject"], request: Request,
                     owner: Owner) -> PendingAction:
        """Records a human decision. v0.1 has no executor: an approved restart is done by the on-call person."""
        async with request.app.state.sessions() as s:
            act = await s.get(PendingAction, action_id)
            if act is None or (owner is not None and act.owner != owner):
                raise HTTPException(404, "action not found")
            if act.status != "pending":
                raise HTTPException(409, f"action already {act.status}")
            act.status = "approved" if decision == "approve" else "rejected"
            act.decided_at = utcnow()
            await s.commit()
            return act

    if WEB_DIR.is_dir():  # the "try it" page; mounted last so the API routes win
        app.mount("/", StaticFiles(directory=WEB_DIR, html=True), name="web")
    return app


async def _save_run(sessions, message: str, run: AgentRun) -> None:
    async with sessions() as s:
        s.add(AgentRunRow(id=run.run_id, message=message, reply=run.reply.model_dump() if run.reply else None,
                          stop_reason=run.stop_reason, steps=len(run.steps), input_tokens=run.usage.input_tokens,
                          output_tokens=run.usage.output_tokens, latency_ms=run.latency_ms))
        await s.flush()
        for st in run.steps:
            s.add(ToolCallRow(run_id=run.run_id, step=st.step, tool=st.tool, args=st.args, ok=st.ok,
                              result=st.result[:4000], latency_ms=st.latency_ms))
        await s.commit()


def app_factory() -> FastAPI:  # uvicorn --factory helpdesk.api:app_factory
    return create_app()
