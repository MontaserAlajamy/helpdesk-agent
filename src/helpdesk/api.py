"""FastAPI service: chat with the agent, read tickets, approve or reject queued actions."""

from collections.abc import AsyncIterator
from contextlib import asynccontextmanager
from datetime import datetime
from pathlib import Path
from typing import Annotated, Literal

from fastapi import Depends, FastAPI, HTTPException, Request
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
from .tools import FinalAnswerArgs, ToolContext, build_tools

RUNBOOK_DIR = Path(__file__).resolve().parents[2] / "data" / "runbooks"


class ChatRequest(BaseModel):
    message: str = Field(min_length=1, max_length=4000)


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


def create_app(settings: Settings | None = None, llm: LLM | None = None) -> FastAPI:
    settings = settings or Settings.from_env()

    @asynccontextmanager
    async def lifespan(app: FastAPI) -> AsyncIterator[None]:
        engine = make_engine(settings.database_url)
        await create_schema(engine)
        sessions = make_sessionmaker(engine)
        embedder = HashingEmbedder(settings.embed_dim)
        async with sessions() as s:
            if await runbooks.count(s) == 0 and RUNBOOK_DIR.exists():
                await runbooks.seed(s, runbooks.load_dir(RUNBOOK_DIR), embedder)
        app.state.sessions = sessions
        app.state.embedder = embedder
        app.state.tools = build_tools(settings.services)
        app.state.llm = llm  # built lazily so the API starts without a key
        yield
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

    @app.post("/v1/chat", response_model=ChatResponse)
    async def chat(body: ChatRequest, request: Request, llm: Annotated[LLM, Depends(get_llm)]) -> ChatResponse:
        st = request.app.state
        ctx = ToolContext(st.sessions, st.embedder, settings.services, check_timeout_s=settings.check_timeout_s)
        run = await run_agent(body.message, llm, st.tools, ctx, max_steps=settings.max_steps)
        await _save_run(st.sessions, body.message, run)
        return ChatResponse(
            run_id=run.run_id, reply=run.reply, stop_reason=run.stop_reason,
            steps=[StepOut(tool=s.tool, args=s.args, ok=s.ok) for s in run.steps],
            pending_action_ids=ctx.pending_action_ids,
            input_tokens=run.usage.input_tokens, output_tokens=run.usage.output_tokens, latency_ms=run.latency_ms,
        )

    @app.get("/v1/tickets", response_model=list[TicketOut])
    async def list_tickets(request: Request, status: str | None = None) -> list[Ticket]:
        async with request.app.state.sessions() as s:
            stmt = select(Ticket).order_by(Ticket.id.desc())
            if status:
                stmt = stmt.where(Ticket.status == status)
            return list((await s.execute(stmt)).scalars())

    @app.get("/v1/tickets/{ticket_id}", response_model=TicketOut)
    async def read_ticket(ticket_id: int, request: Request) -> Ticket:
        async with request.app.state.sessions() as s:
            t = await s.get(Ticket, ticket_id)
        if t is None:
            raise HTTPException(404, "ticket not found")
        return t

    @app.get("/v1/actions", response_model=list[ActionOut])
    async def list_actions(request: Request, status: str = "pending") -> list[PendingAction]:
        async with request.app.state.sessions() as s:
            stmt = select(PendingAction).where(PendingAction.status == status).order_by(PendingAction.id)
            return list((await s.execute(stmt)).scalars())

    @app.post("/v1/actions/{action_id}/{decision}", response_model=ActionOut)
    async def decide(action_id: int, decision: Literal["approve", "reject"], request: Request) -> PendingAction:
        """Records a human decision. v0.1 has no executor: an approved restart is done by the on-call person."""
        async with request.app.state.sessions() as s:
            act = await s.get(PendingAction, action_id)
            if act is None:
                raise HTTPException(404, "action not found")
            if act.status != "pending":
                raise HTTPException(409, f"action already {act.status}")
            act.status = "approved" if decision == "approve" else "rejected"
            act.decided_at = utcnow()
            await s.commit()
            return act

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
