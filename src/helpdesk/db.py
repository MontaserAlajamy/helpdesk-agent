"""Async SQLAlchemy 2 models. Postgres + pgvector in production, SQLite in tests."""

from __future__ import annotations

from datetime import UTC, datetime

from pgvector.sqlalchemy import Vector
from sqlalchemy import JSON, Boolean, DateTime, Float, ForeignKey, Integer, String, Text, inspect
from sqlalchemy.ext.asyncio import AsyncEngine, async_sessionmaker, create_async_engine
from sqlalchemy.orm import DeclarativeBase, Mapped, mapped_column
from sqlalchemy.types import TypeDecorator

EMBED_DIM = 256


def utcnow() -> datetime:
    return datetime.now(UTC)


class Embedding(TypeDecorator):
    """pgvector `vector(n)` on Postgres, JSON list elsewhere."""

    impl = JSON
    cache_ok = True

    def __init__(self, dim: int = EMBED_DIM) -> None:
        super().__init__()
        self.dim = dim

    def load_dialect_impl(self, dialect):
        if dialect.name == "postgresql":
            return dialect.type_descriptor(Vector(self.dim))
        return dialect.type_descriptor(JSON())

    def process_result_value(self, value, dialect):
        return None if value is None else [float(v) for v in value]


class Base(DeclarativeBase):
    pass


class Ticket(Base):
    __tablename__ = "tickets"
    id: Mapped[int] = mapped_column(Integer, primary_key=True)
    title: Mapped[str] = mapped_column(String(200))
    description: Mapped[str] = mapped_column(Text)
    priority: Mapped[str] = mapped_column(String(16))
    category: Mapped[str] = mapped_column(String(32))
    status: Mapped[str] = mapped_column(String(16), default="open")
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=utcnow)
    owner: Mapped[str | None] = mapped_column(String(64), nullable=True, index=True)  # demo visitor session


class Runbook(Base):
    __tablename__ = "runbooks"
    id: Mapped[str] = mapped_column(String(64), primary_key=True)
    title: Mapped[str] = mapped_column(String(200))
    category: Mapped[str] = mapped_column(String(32))
    content: Mapped[str] = mapped_column(Text)
    embedding: Mapped[list[float]] = mapped_column(Embedding(EMBED_DIM))


class PendingAction(Base):
    """A dangerous action the agent asked for. Only a human can approve it."""

    __tablename__ = "pending_actions"
    id: Mapped[int] = mapped_column(Integer, primary_key=True)
    run_id: Mapped[str] = mapped_column(String(36), index=True)
    tool: Mapped[str] = mapped_column(String(64))
    args: Mapped[dict] = mapped_column(JSON)
    status: Mapped[str] = mapped_column(String(16), default="pending")  # pending | approved | rejected
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=utcnow)
    decided_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)
    owner: Mapped[str | None] = mapped_column(String(64), nullable=True, index=True)  # demo visitor session


class AgentRunRow(Base):
    __tablename__ = "agent_runs"
    id: Mapped[str] = mapped_column(String(36), primary_key=True)
    message: Mapped[str] = mapped_column(Text)
    reply: Mapped[dict | None] = mapped_column(JSON, nullable=True)
    stop_reason: Mapped[str] = mapped_column(String(32))
    steps: Mapped[int] = mapped_column(Integer)
    input_tokens: Mapped[int] = mapped_column(Integer, default=0)
    output_tokens: Mapped[int] = mapped_column(Integer, default=0)
    latency_ms: Mapped[float] = mapped_column(Float, default=0.0)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=utcnow)


class ToolCallRow(Base):
    __tablename__ = "tool_calls"
    id: Mapped[int] = mapped_column(Integer, primary_key=True)
    run_id: Mapped[str] = mapped_column(ForeignKey("agent_runs.id"), index=True)
    step: Mapped[int] = mapped_column(Integer)
    tool: Mapped[str] = mapped_column(String(64))
    args: Mapped[dict] = mapped_column(JSON)
    ok: Mapped[bool] = mapped_column(Boolean)
    result: Mapped[str] = mapped_column(Text)
    latency_ms: Mapped[float] = mapped_column(Float)


def make_engine(url: str) -> AsyncEngine:
    # No asyncpg vector codec is registered: pgvector's SQLAlchemy type sends vectors as text ('[1,2,3]'),
    # which asyncpg passes through for the extension type.
    return create_async_engine(url)


async def create_schema(engine: AsyncEngine) -> None:
    async with engine.begin() as conn:
        if engine.dialect.name == "postgresql":
            await conn.exec_driver_sql("CREATE EXTENSION IF NOT EXISTS vector")
        await conn.run_sync(Base.metadata.create_all)
        await conn.run_sync(_add_missing_columns)


# columns added after the first release: create_all does not alter existing tables, so add them by hand
_LATER_COLUMNS = [("tickets", "owner", "VARCHAR(64)"), ("pending_actions", "owner", "VARCHAR(64)")]


def _add_missing_columns(conn) -> None:
    insp = inspect(conn)
    for table, column, ddl in _LATER_COLUMNS:
        if insp.has_table(table) and column not in {c["name"] for c in insp.get_columns(table)}:
            conn.exec_driver_sql(f"ALTER TABLE {table} ADD COLUMN {column} {ddl}")


def make_sessionmaker(engine: AsyncEngine) -> async_sessionmaker:
    return async_sessionmaker(engine, expire_on_commit=False)
