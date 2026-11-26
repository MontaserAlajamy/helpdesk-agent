"""Runbook store: load markdown runbooks, embed them, search them (pgvector or in-Python cosine)."""

from __future__ import annotations

from dataclasses import dataclass
from pathlib import Path

from sqlalchemy import Float, func, select
from sqlalchemy.ext.asyncio import AsyncSession

from .db import Runbook
from .embeddings import Embedder, cosine


@dataclass(frozen=True)
class RunbookDoc:
    id: str
    title: str
    category: str
    content: str


@dataclass(frozen=True)
class Hit:
    id: str
    title: str
    category: str
    content: str
    score: float


def parse_runbook(text: str) -> RunbookDoc:
    """Format: '---' / 'id: x' / 'category: y' / '---' / '# Title' / body."""
    lines = text.strip().splitlines()
    if not lines or lines[0].strip() != "---":
        raise ValueError("runbook must start with a '---' header")
    meta: dict[str, str] = {}
    i = 1
    while i < len(lines) and lines[i].strip() != "---":
        key, _, value = lines[i].partition(":")
        meta[key.strip()] = value.strip()
        i += 1
    body = lines[i + 1 :]
    title_line = next((ln for ln in body if ln.startswith("# ")), None)
    if not title_line or "id" not in meta or "category" not in meta:
        raise ValueError("runbook needs id, category and a '# Title' line")
    content = "\n".join(ln for ln in body if ln is not title_line).strip()
    return RunbookDoc(meta["id"], title_line[2:].strip(), meta["category"], content)


def load_dir(path: Path) -> list[RunbookDoc]:
    return [parse_runbook(p.read_text(encoding="utf-8")) for p in sorted(path.glob("*.md"))]


async def seed(session: AsyncSession, docs: list[RunbookDoc], embedder: Embedder) -> int:
    """Insert or update runbooks; returns how many were written."""
    for d in docs:
        vec = embedder.embed(f"{d.title}\n{d.content}")
        await session.merge(Runbook(id=d.id, title=d.title, category=d.category, content=d.content, embedding=vec))
    await session.commit()
    return len(docs)


async def count(session: AsyncSession) -> int:
    return (await session.execute(select(func.count()).select_from(Runbook))).scalar_one()


async def search(session: AsyncSession, query: str, embedder: Embedder, k: int = 3) -> list[Hit]:
    qvec = embedder.embed(query)
    if session.bind.dialect.name == "postgresql":
        dist = Runbook.__table__.c.embedding.op("<=>", return_type=Float)
        stmt = select(Runbook, dist(qvec).label("d")).order_by("d").limit(k)
        rows = (await session.execute(stmt)).all()
        return [Hit(r.id, r.title, r.category, r.content, 1.0 - float(d)) for r, d in rows]
    rows = (await session.execute(select(Runbook))).scalars().all()
    scored = sorted(((cosine(qvec, r.embedding), r) for r in rows), key=lambda t: t[0], reverse=True)[:k]
    return [Hit(r.id, r.title, r.category, r.content, s) for s, r in scored]
