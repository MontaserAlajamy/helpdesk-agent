from conftest import call, respond

from helpdesk.agent import run_agent
from helpdesk.llm import ScriptedLLM
from helpdesk.tools import build_tools


async def test_happy_path_search_ticket_answer(ctx):
    llm = ScriptedLLM([
        respond(call("search_runbooks", 0, query="vpn not connecting")),
        respond(call("create_ticket", 1, title="VPN fails after all steps", description="User tried every step.",
                     priority="high", category="network")),
        respond(call("final_answer", 2, answer="Ticket 1 opened.", language="en", ticket_id=1, needs_human=True)),
    ])
    run = await run_agent("vpn broken", llm, build_tools(ctx.services), ctx)
    assert run.stop_reason == "final_answer"
    assert run.tools_called == ["search_runbooks", "create_ticket", "final_answer"]
    assert run.reply.ticket_id == 1 and not run.violations
    assert run.usage.input_tokens == 300
    # runbook text reaches the model wrapped as untrusted data
    tool_msgs = [m for m in llm.calls[1] if m.role == "tool"]
    assert tool_msgs[0].content.startswith("<untrusted_data>")


async def test_invented_ticket_id_is_caught(ctx):
    llm = ScriptedLLM([respond(call("final_answer", answer="Your ticket is 42.", language="en", ticket_id=42,
                                    needs_human=False))])
    run = await run_agent("hi", llm, build_tools(ctx.services), ctx)
    assert run.reply.ticket_id is None and run.reply.needs_human
    assert run.violations == ["cited ticket 42 that no tool returned"]


async def test_final_answer_in_same_turn_can_cite_new_ticket(ctx):
    llm = ScriptedLLM([respond(
        call("final_answer", 1, answer="Opened ticket 1.", language="en", ticket_id=1, needs_human=True),
        call("create_ticket", 0, title="Printer fuser error", description="Fuser error code on screen",
             priority="low", category="hardware"),
    )])
    run = await run_agent("printer", llm, build_tools(ctx.services), ctx)
    assert run.tools_called == ["create_ticket", "final_answer"] and not run.violations


async def test_bad_args_are_returned_and_model_can_recover(ctx):
    llm = ScriptedLLM([
        respond(call("create_ticket", 0, title="x")),
        respond(call("final_answer", 1, answer="ok", language="en", needs_human=True)),
    ])
    run = await run_agent("x", llm, build_tools(ctx.services), ctx)
    assert [s.ok for s in run.steps] == [False, True]
    assert "invalid arguments" in [m for m in llm.calls[1] if m.role == "tool"][0].content


async def test_step_limit_gives_safe_fallback_in_arabic(ctx):
    llm = ScriptedLLM([respond(call("search_runbooks", i, query="شبكة")) for i in range(3)])
    run = await run_agent("الشبكة واقفة", llm, build_tools(ctx.services), ctx, max_steps=3)
    assert run.stop_reason == "max_steps"
    assert run.reply.language == "ar" and run.reply.needs_human


async def test_text_without_tools_is_nudged_once_then_stops(ctx):
    llm = ScriptedLLM([respond(text="hello"), respond(text="still talking")])
    run = await run_agent("hi", llm, build_tools(ctx.services), ctx)
    assert run.stop_reason == "no_tool_call" and run.model_turns == 2


async def test_unknown_tool_is_reported(ctx):
    llm = ScriptedLLM([respond(call("rm_rf", 0)), respond(call("final_answer", 1, answer="no", language="en",
                                                                 needs_human=False))])
    run = await run_agent("x", llm, build_tools(ctx.services), ctx)
    assert run.steps[0].tool == "rm_rf" and not run.steps[0].ok
