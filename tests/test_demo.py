"""Streaming, demo mode (simulated outages, visitor isolation, abuse limits), the page and /v1/meta."""

import json
import socket

import pytest
from conftest import call, respond
from fastapi.testclient import TestClient

from helpdesk.agent import run_agent
from helpdesk.api import RateLimiter, create_app
from helpdesk.config import Settings
from helpdesk.llm import FakeDemoLLM, ScriptedLLM
from helpdesk.tools import build_tools

A = {"X-Demo-Session": "visitor-aaaa"}
B = {"X-Demo-Session": "visitor-bbbb"}


def sse(text: str) -> list[dict]:
    return [json.loads(line[5:]) for line in text.splitlines() if line.startswith("data:")]


def client(tmp_path, script, demo=False, services=None, limiter=None, provider="anthropic"):
    settings = Settings(database_url=f"sqlite+aiosqlite:///{tmp_path}/demo.db", demo_mode=demo,
                        services=services or {}, llm_provider=provider, llm_model="m", check_timeout_s=1.0)
    return TestClient(create_app(settings, llm=ScriptedLLM(script), limiter=limiter))


def check_then_answer(i=0):
    return [respond(call("check_service", i, name="mail")),
            respond(call("final_answer", i + 1, answer="checked", language="en", needs_human=False))]


@pytest.fixture
def listening_port():
    s = socket.socket()
    s.bind(("127.0.0.1", 0))
    s.listen(8)
    yield s.getsockname()[1]
    s.close()


def test_stream_yields_tool_final_done_in_order(tmp_path):
    script = [
        respond(call("search_runbooks", 0, query="vpn authentication failed")),
        respond(call("create_ticket", 1, title="VPN auth fails", description="User sees authentication failed",
                     priority="medium", category="network")),
        respond(call("final_answer", 2, answer="Opened ticket 1.", language="en", ticket_id=1, needs_human=True)),
    ]
    with client(tmp_path, script) as c:
        r = c.post("/v1/chat/stream", json={"message": "vpn says authentication failed"})
        assert r.status_code == 200 and r.headers["content-type"].startswith("text/event-stream")
        events = sse(r.text)
    assert [e["type"] for e in events] == ["model_turn", "tool", "model_turn", "tool", "model_turn", "tool",
                                           "final", "done"]
    tools = [e for e in events if e["type"] == "tool"]
    assert [t["tool"] for t in tools] == ["search_runbooks", "create_ticket", "final_answer"]
    assert all(t["ok"] for t in tools) and len(tools[0]["result_preview"]) <= 300
    assert events[-2]["reply"]["ticket_id"] == 1 and events[-2]["stop_reason"] == "final_answer"
    done = events[-1]
    assert done["input_tokens"] == 300 and done["run_id"] and done["pending_action_ids"] == []


def test_stream_reports_provider_error(tmp_path):
    with client(tmp_path, []) as c:  # ScriptedLLM runs out at once: like a provider failure
        events = sse(c.post("/v1/chat/stream", json={"message": "hi"}).text)
    assert events[-1]["type"] == "error" and "failed" in events[-1]["detail"]


async def test_on_event_sequence(ctx):
    seen = []

    async def collect(e):
        seen.append(e)

    llm = ScriptedLLM([respond(call("create_ticket", 0, title="x")),
                       respond(call("final_answer", 1, answer="ok", language="en", needs_human=True))])
    run = await run_agent("x", llm, build_tools(ctx.services), ctx, on_event=collect)
    assert [e["type"] for e in seen] == ["model_turn", "tool", "model_turn", "tool", "final"]
    assert seen[1]["ok"] is False and "invalid arguments" in seen[1]["result_preview"]
    assert seen[-1]["reply"] == run.reply.model_dump()


def test_down_is_honoured_in_demo_mode_only_for_known_names(tmp_path):
    with client(tmp_path, check_then_answer(0) + check_then_answer(2), demo=True) as c:
        down = sse(c.post("/v1/chat/stream", json={"message": "mail?", "down": ["mail"]}, headers=A).text)
        up = sse(c.post("/v1/chat/stream", json={"message": "mail?", "down": ["nope", "../etc"]}, headers=A).text)
    status = [json.loads(e["result_preview"])["status"] for e in down + up if e.get("tool") == "check_service"]
    assert status == ["down", "up"]


def test_down_is_ignored_outside_demo_mode(tmp_path, listening_port):
    services = {"mail": f"tcp://127.0.0.1:{listening_port}"}
    with client(tmp_path, check_then_answer(), services=services) as c:
        events = sse(c.post("/v1/chat/stream", json={"message": "mail?", "down": ["mail"]}).text)
    check = next(e for e in events if e.get("tool") == "check_service")
    assert json.loads(check["result_preview"])["status"] == "up"


def test_visitor_isolation_in_demo_mode(tmp_path):
    script = [
        respond(call("restart_service", 0, name="mail", reason="check_service shows mail is down")),
        respond(call("create_ticket", 1, title="Mail down", description="Port closed, restart asked",
                     priority="high", category="email")),
        respond(call("final_answer", 2, answer="Ticket 1 opened.", language="en", ticket_id=1, needs_human=True)),
        # visitor B tries to read A's ticket through the agent
        respond(call("get_ticket", 3, ticket_id=1)),
        respond(call("final_answer", 4, answer="Not found.", language="en", needs_human=False)),
    ]
    with client(tmp_path, script, demo=True) as c:
        assert c.post("/v1/chat", json={"message": "mail down"}).status_code == 400  # no session header
        assert c.post("/v1/chat", json={"message": "mail down"}, headers={"X-Demo-Session": "bad id!"}).status_code \
            == 400
        assert c.post("/v1/chat", json={"message": "mail down"}, headers=A).json()["pending_action_ids"] == [1]
        assert [t["id"] for t in c.get("/v1/tickets", headers=A).json()] == [1]
        assert len(c.get("/v1/actions", headers=A).json()) == 1
        assert c.get("/v1/tickets", headers=B).json() == []
        assert c.get("/v1/actions", headers=B).json() == []
        assert c.get("/v1/tickets/1", headers=B).status_code == 404
        assert c.post("/v1/actions/1/approve", headers=B).status_code == 404
        steps = c.post("/v1/chat", json={"message": "status of ticket 1?"}, headers=B).json()["steps"]
        assert steps[0] == {"tool": "get_ticket", "args": {"ticket_id": 1}, "ok": False}
        assert c.post("/v1/actions/1/approve", headers=A).json()["status"] == "approved"
        assert [a["status"] for a in c.get("/v1/actions?status=all", headers=A).json()] == ["approved"]


def test_no_isolation_outside_demo_mode(tmp_path):
    script = [respond(call("create_ticket", 0, title="Printer jam", description="Paper jam in tray 2",
                           priority="low", category="hardware")),
              respond(call("final_answer", 1, answer="Ticket 1.", language="en", ticket_id=1, needs_human=True))]
    with client(tmp_path, script) as c:
        c.post("/v1/chat", json={"message": "printer"}, headers=A)
        assert len(c.get("/v1/tickets").json()) == 1
        assert len(c.get("/v1/tickets", headers=B).json()) == 1
        assert c.get("/v1/tickets/1", headers=B).status_code == 200


def test_rate_limiter_per_ip_and_global_with_fake_clock():
    now = [0.0]
    rl = RateLimiter(per_ip=2, per_ip_window_s=3600, global_cap=3, global_window_s=86400, clock=lambda: now[0])
    assert rl.hit("1.1.1.1") is None and rl.hit("1.1.1.1") is None
    assert "this hour" in rl.hit("1.1.1.1")
    assert rl.hit("2.2.2.2") is None
    assert "today" in rl.hit("3.3.3.3")  # global cap of 3 reached
    now[0] = 3601
    assert "today" in rl.hit("1.1.1.1")  # per-IP window passed, the day has not
    now[0] = 86401
    assert rl.hit("1.1.1.1") is None and rl.hit("3.3.3.3") is None


def test_rate_limit_returns_429_by_forwarded_ip(tmp_path):
    rl = RateLimiter(per_ip=1, global_cap=100, clock=lambda: 0.0)
    script = [respond(call("final_answer", i, answer="ok", language="en", needs_human=False)) for i in range(2)]
    with client(tmp_path, script, demo=True, limiter=rl) as c:
        ip1 = {**A, "X-Forwarded-For": "9.9.9.9, 10.0.0.1"}
        assert c.post("/v1/chat", json={"message": "hi"}, headers=ip1).status_code == 200
        r = c.post("/v1/chat/stream", json={"message": "hi"}, headers=ip1)
        assert r.status_code == 429 and "try again" in r.json()["detail"]
        ip2 = {**A, "X-Forwarded-For": "8.8.8.8"}
        assert c.post("/v1/chat", json={"message": "hi"}, headers=ip2).status_code == 200


def test_message_length_cap_only_in_demo(tmp_path):
    long = "x" * 501
    script = [respond(call("final_answer", answer="ok", language="en", needs_human=False))]
    with client(tmp_path, [], demo=True) as c:
        r = c.post("/v1/chat", json={"message": long}, headers=A)
        assert r.status_code == 422 and "500" in r.json()["detail"]
    with client(tmp_path, script) as c:
        assert c.post("/v1/chat", json={"message": long}).status_code == 200


def test_page_and_meta(tmp_path):
    with client(tmp_path, [], demo=True, provider="fake") as c:
        page = c.get("/")
        assert page.status_code == 200 and "Helpdesk Agent" in page.text and "text/html" in page.headers["content-type"]
        assert c.get("/app.js").status_code == 200 and c.get("/app.css").status_code == 200
        meta = c.get("/v1/meta").json()
    assert meta["demo"] is True and meta["model"] == "fake (offline demo)"
    assert meta["services"] == ["intranet", "mail", "pbx"] and meta["max_steps"] == 6 and meta["version"]
    with client(tmp_path, []) as c:
        meta = c.get("/v1/meta").json()
    assert meta == {**meta, "demo": False, "model": "m", "services": []}


def test_live_flow_files_are_served_and_linked(tmp_path):
    with client(tmp_path, [], demo=True, provider="fake") as c:
        page = c.get("/").text
        js, css = c.get("/flow.js"), c.get("/flow.css")
        meta = c.get("/v1/meta").json()
    assert js.status_code == 200 and "javascript" in js.headers["content-type"] and "HelpdeskFlow" in js.text
    assert css.status_code == 200 and "text/css" in css.headers["content-type"]
    assert '<script src="flow.js"></script>' in page and 'href="flow.css"' in page
    assert page.index("flow.js") < page.index("app.js")  # app.js drives the flow, so it loads second
    assert 'id="flow-stage"' in page and 'role="tablist"' in page
    assert meta["tools"] == 6 and meta["guides"] == 9


async def test_fake_llm_plays_a_plausible_run(ctx):
    run = await run_agent("Mail is down, please restart it", FakeDemoLLM(), build_tools(ctx.services), ctx)
    assert run.tools_called == ["search_runbooks", "check_service", "restart_service", "create_ticket", "final_answer"]
    assert run.stop_reason == "final_answer" and run.reply.ticket_id == 1 and not run.violations
    run = await run_agent("الطابعة بتطلع رسالة خطأ", FakeDemoLLM(), build_tools(ctx.services), ctx)
    assert run.tools_called == ["search_runbooks", "create_ticket", "final_answer"] and run.reply.language == "ar"
    assert not run.violations
