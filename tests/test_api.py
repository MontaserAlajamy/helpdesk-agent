from conftest import call, respond
from fastapi.testclient import TestClient

from helpdesk.api import create_app
from helpdesk.config import Settings, parse_services
from helpdesk.llm import ScriptedLLM


def make_client(tmp_path, script):
    settings = Settings(database_url=f"sqlite+aiosqlite:///{tmp_path}/api.db", services={"mail": "tcp://127.0.0.1:1"})
    return TestClient(create_app(settings, llm=ScriptedLLM(script)))


def test_chat_ticket_and_approval_flow(tmp_path):
    script = [
        respond(call("check_service", 0, name="mail")),
        respond(call("restart_service", 1, name="mail", reason="check_service shows mail is down")),
        respond(call("create_ticket", 2, title="Mail service down", description="Port closed, restart requested",
                     priority="high", category="email")),
        respond(call("final_answer", 3, answer="Mail is down. Ticket 1 opened; restart waits for approval.",
                     language="en", ticket_id=1, needs_human=True)),
    ]
    with make_client(tmp_path, script) as c:
        assert c.get("/healthz").json()["status"] == "ok"
        r = c.post("/v1/chat", json={"message": "mail is down"})
        assert r.status_code == 200, r.text
        body = r.json()
        assert body["reply"]["ticket_id"] == 1
        expected = ["check_service", "restart_service", "create_ticket", "final_answer"]
        assert [s["tool"] for s in body["steps"]] == expected
        assert body["pending_action_ids"] == [1]

        assert c.get("/v1/tickets/1").json()["priority"] == "high"
        assert len(c.get("/v1/actions").json()) == 1
        assert c.post("/v1/actions/1/approve").json()["status"] == "approved"
        assert c.post("/v1/actions/1/reject").status_code == 409
        assert c.get("/v1/actions").json() == []


def test_validation_and_404(tmp_path):
    with make_client(tmp_path, []) as c:
        assert c.post("/v1/chat", json={"message": ""}).status_code == 422
        assert c.get("/v1/tickets/5").status_code == 404
        assert c.post("/v1/actions/5/maybe").status_code == 422


def test_missing_llm_config_is_503(tmp_path):
    settings = Settings(database_url=f"sqlite+aiosqlite:///{tmp_path}/x.db", llm_model="")
    with TestClient(create_app(settings)) as c:
        assert c.post("/v1/chat", json={"message": "hi"}).status_code == 503


def test_parse_services():
    assert parse_services("a=http://x/h, b=tcp://h:1") == {"a": "http://x/h", "b": "tcp://h:1"}
