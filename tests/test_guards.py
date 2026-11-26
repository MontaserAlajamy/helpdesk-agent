"""Repeat detector and no-duplicates guards."""

from conftest import call, respond
from sqlalchemy import func, select

from helpdesk.agent import run_agent
from helpdesk.db import PendingAction, Ticket
from helpdesk.evals import score_task
from helpdesk.llm import ScriptedLLM
from helpdesk.tools import build_tools, execute

TICKET = dict(title="Mail service down", description="check_service shows mail is down", priority="high",
              category="email")


async def test_third_identical_call_is_not_run(ctx):
    llm = ScriptedLLM([respond(call("check_service", i, name="mail")) for i in range(3)]
                      + [respond(call("final_answer", 9, answer="Mail is down.", language="en", needs_human=True))])
    run = await run_agent("check mail", llm, build_tools(ctx.services), ctx)
    assert [s.ok for s in run.steps[:3]] == [True, True, False]
    assert "repeated call" in run.steps[2].result
    assert run.stop_reason == "final_answer" and run.blocked_repeats == 1 and run.blocked_turns == 1


async def test_persistent_repeats_stop_with_handoff_that_names_the_ticket(ctx):
    llm = ScriptedLLM([respond(call("create_ticket", 0, **TICKET))]
                      + [respond(call("check_service", i, name="mail")) for i in range(1, 6)])
    run = await run_agent("keep checking mail until it is up", llm, build_tools(ctx.services), ctx)
    assert run.stop_reason == "repeated_calls"
    assert run.model_turns == 5  # ticket, check, check, blocked, blocked
    assert run.reply.ticket_id == 1 and run.reply.needs_human and "#1" in run.reply.answer
    assert "What I checked: mail is down." in run.reply.answer


async def test_different_arguments_are_not_repeats(ctx):
    ctx.services = {"mail": "tcp://127.0.0.1:1", "pbx": "tcp://127.0.0.1:1", "intranet": "tcp://127.0.0.1:1"}
    llm = ScriptedLLM([respond(call("check_service", 0, name="mail"), call("check_service", 1, name="pbx"),
                               call("check_service", 2, name="intranet")),
                       respond(call("final_answer", 3, answer="All three are down.", language="en",
                                    needs_human=True))])
    run = await run_agent("check everything", llm, build_tools(ctx.services), ctx)
    assert all(s.ok for s in run.steps) and run.blocked_repeats == 0


async def test_one_ticket_per_category_per_conversation(ctx, sessions):
    tools = build_tools(ctx.services)
    a = await execute(tools["create_ticket"], TICKET, ctx)
    b = await execute(tools["create_ticket"], {**TICKET, "title": "Email still down"}, ctx)
    c = await execute(tools["create_ticket"], {**TICKET, "category": "voip", "title": "Phones dead too"}, ctx)
    assert a.data["ticket_id"] == b.data["ticket_id"] and b.data["status"] == "already_open"
    assert c.data["ticket_id"] != a.data["ticket_id"]
    async with sessions() as s:
        assert (await s.execute(select(func.count()).select_from(Ticket))).scalar_one() == 2


async def test_one_waiting_restart_per_service(ctx, sessions):
    tools = build_tools(ctx.services)
    args = {"name": "mail", "reason": "check_service shows mail is down"}
    first = await execute(tools["restart_service"], args, ctx)
    second = await execute(tools["restart_service"], args, ctx)
    assert second.data["status"] == "already_pending" and second.data["action_id"] == first.data["action_id"]
    async with sessions() as s:
        act = await s.get(PendingAction, first.data["action_id"])
        act.status = "approved"  # once a person decided, a new request is allowed
        await s.commit()
    third = await execute(tools["restart_service"], args, ctx)
    assert third.data["status"] == "pending_approval" and third.data["action_id"] != first.data["action_id"]


async def test_demo_visitors_do_not_block_each_other(ctx):
    tools = build_tools(ctx.services)
    args = {"name": "mail", "reason": "check_service shows mail is down"}
    ctx.owner = "visitor-a"
    a = await execute(tools["restart_service"], args, ctx)
    ctx.owner = "visitor-b"
    b = await execute(tools["restart_service"], args, ctx)
    assert b.data["status"] == "pending_approval" and b.data["action_id"] != a.data["action_id"]


def test_eval_counts_duplicate_tickets():
    from helpdesk.agent import AgentRun, StepRecord
    from helpdesk.llm import Usage
    from helpdesk.tools import FinalAnswerArgs

    steps = [StepRecord(1, "create_ticket", {}, True, '{"ticket_id": 1}', 0),
             StepRecord(2, "create_ticket", {}, True, '{"ticket_id": 2}', 0)]
    run = AgentRun("r", FinalAnswerArgs(answer="ok", language="en", needs_human=True), "final_answer", steps, Usage())
    assert any("distinct create_ticket" in f for f in score_task({"max_tickets": 1}, run))


async def test_many_repeats_in_one_turn_still_get_a_turn_to_answer(ctx):
    llm = ScriptedLLM([respond(*[call("check_service", i, name="mail") for i in range(10)]),
                       respond(call("final_answer", 99, answer="Mail is down.", language="en", needs_human=True))])
    run = await run_agent("check mail 10 times", llm, build_tools(ctx.services), ctx)
    assert run.blocked_repeats == 8 and run.blocked_turns == 1
    assert run.stop_reason == "final_answer" and run.reply.answer == "Mail is down."
