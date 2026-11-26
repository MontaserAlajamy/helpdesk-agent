from __future__ import annotations

import os

import pytest

from helpdesk import runbooks
from helpdesk.api import RUNBOOK_DIR
from helpdesk.db import create_schema, make_engine, make_sessionmaker
from helpdesk.embeddings import HashingEmbedder
from helpdesk.llm import LLMResponse, ToolCall, Usage
from helpdesk.tools import ToolContext

PG_URL = os.environ.get("TEST_DATABASE_URL")  # e.g. postgresql+asyncpg://helpdesk:helpdesk@localhost/helpdesk_test


@pytest.fixture(params=["sqlite"] + (["postgres"] if PG_URL else []))
async def sessions(request, tmp_path):
    url = f"sqlite+aiosqlite:///{tmp_path}/t.db" if request.param == "sqlite" else PG_URL
    engine = make_engine(url)
    if request.param == "postgres":
        from helpdesk.db import Base

        async with engine.begin() as conn:
            await conn.run_sync(Base.metadata.drop_all)
    await create_schema(engine)
    sm = make_sessionmaker(engine)
    async with sm() as s:
        await runbooks.seed(s, runbooks.load_dir(RUNBOOK_DIR), HashingEmbedder(256))
    yield sm
    await engine.dispose()


@pytest.fixture
def ctx(sessions):
    return ToolContext(sessions, HashingEmbedder(256), {"mail": "tcp://127.0.0.1:1"}, check_timeout_s=0.5)


def call(tool: str, i: int = 0, /, **args) -> ToolCall:
    return ToolCall(id=f"c{i}-{tool}", name=tool, args=args)


def respond(*calls: ToolCall, text: str = "") -> LLMResponse:
    return LLMResponse(text=text, tool_calls=list(calls), usage=Usage(100, 20))
