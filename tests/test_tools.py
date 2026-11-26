import asyncio
import json

from sqlalchemy import select

from helpdesk.db import PendingAction, Ticket
from helpdesk.tools import build_tools, execute


async def test_invalid_arguments_go_back_to_the_model_not_raise(ctx):
    tools = build_tools(ctx.services)
    res = await execute(tools["create_ticket"], {"title": "x", "priority": "urgent!!"}, ctx)
    assert not res.ok
    body = json.loads(res.content)
    assert body["error"] == "invalid arguments"
    fields = {d["field"] for d in body["details"]}
    assert {"title", "priority", "description", "category"} <= fields


async def test_create_and_get_ticket(ctx, sessions):
    tools = build_tools(ctx.services)
    args = {"title": "VPN down for user", "description": "Tried all steps, still failing",
            "priority": "high", "category": "network"}
    res = await execute(tools["create_ticket"], args, ctx)
    assert res.ok
    tid = res.data["ticket_id"]
    assert tid in ctx.seen_ticket_ids
    got = await execute(tools["get_ticket"], {"ticket_id": tid}, ctx)
    assert got.ok and got.data["priority"] == "high"
    async with sessions() as s:
        assert (await s.get(Ticket, tid)).category == "network"


async def test_get_missing_ticket_is_a_tool_error(ctx):
    res = await execute(build_tools(ctx.services)["get_ticket"], {"ticket_id": 9999}, ctx)
    assert not res.ok and "not found" in res.content


async def test_restart_only_queues_for_approval(ctx, sessions):
    ctx.run_id = "run-1"
    res = await execute(build_tools(ctx.services)["restart_service"],
                        {"name": "mail", "reason": "check_service showed mail is down"}, ctx)
    assert res.ok and res.data["status"] == "pending_approval"
    async with sessions() as s:
        acts = (await s.execute(select(PendingAction))).scalars().all()
    assert [(a.tool, a.status, a.run_id) for a in acts] == [("restart_service", "pending", "run-1")]


async def test_restart_unknown_service_refused(ctx):
    res = await execute(build_tools(ctx.services)["restart_service"],
                        {"name": "everything", "reason": "user asked me to restart it all"}, ctx)
    assert not res.ok and "unknown service" in res.content


async def test_check_service_up_and_down(ctx):
    async def handler(reader, writer):
        writer.close()

    srv = await asyncio.start_server(handler, "127.0.0.1", 0)
    port = srv.sockets[0].getsockname()[1]
    ctx.services = {"pbx": f"tcp://127.0.0.1:{port}", "mail": "tcp://127.0.0.1:1"}
    tools = build_tools(ctx.services)
    up = await execute(tools["check_service"], {"name": "pbx"}, ctx)
    down = await execute(tools["check_service"], {"name": "mail"}, ctx)
    srv.close()
    await srv.wait_closed()
    assert up.data["status"] == "up"
    assert down.data["status"] == "down"


def test_tool_schemas_are_json_schema():
    for t in build_tools({"a": "tcp://x:1"}).values():
        s = t.schema()
        assert s["parameters"]["type"] == "object" and s["description"]
