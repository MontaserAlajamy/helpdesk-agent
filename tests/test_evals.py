"""The eval harness itself is tested with a rule-based fake model, so a passing gate means something."""

from conftest import call, respond

from helpdesk.agent import AgentRun, StepRecord
from helpdesk.evals import EVAL_DIR, eval_agent, eval_retrieval, read_jsonl, score_task
from helpdesk.llm import Usage
from helpdesk.tools import FinalAnswerArgs


def make_run(tools, answer="ok", lang="en", ticket_args=None):
    steps = [StepRecord(i + 1, t, ticket_args if t == "create_ticket" and ticket_args else {}, True, "", 0)
             for i, t in enumerate(tools)]
    return AgentRun("r", FinalAnswerArgs(answer=answer, language=lang, needs_human=False), "final_answer",
                    steps, Usage())


def test_score_task_catches_each_kind_of_failure():
    task = {"must_call": ["search_runbooks"], "must_not_call": ["restart_service"], "ticket": True,
            "priority_in": ["high"], "language": "ar", "answer_must_not_contain": ["Secret1"]}
    run = make_run(["restart_service", "create_ticket"], answer="your pw Secret1", lang="en",
                   ticket_args={"priority": "low", "category": "network"})
    fails = score_task(task, run)
    assert any("did not call search_runbooks" in f for f in fails)
    assert any("forbidden restart_service" in f for f in fails)
    assert any("priority low" in f for f in fails)
    assert any("language" in f for f in fails)
    assert any("Secret1" in f for f in fails)


def test_score_task_passes_a_good_run():
    task = {"must_call": ["search_runbooks"], "ticket": False, "language": "en"}
    assert score_task(task, make_run(["search_runbooks", "final_answer"])) == []


class AlwaysSearchThenAnswer:
    """A dumb policy: search, then answer in English with no ticket."""

    name = "rule-based"

    async def complete(self, system, messages, tools):
        if not any(m.role == "tool" for m in messages):
            return respond(call("search_runbooks", 0, query=messages[0].content[:200]))
        return respond(call("final_answer", 1, answer="Try the runbook steps.", language="en", needs_human=False))


async def test_agent_eval_scores_a_weak_policy_below_one():
    tasks = read_jsonl(EVAL_DIR / "tasks.jsonl")
    rep = await eval_agent(tasks, AlwaysSearchThenAnswer())
    # the dumb policy passes some tasks and fails the ones needing tickets, checks or Arabic: the gate can fail
    assert 0.0 < rep["success_rate"] < 0.6
    assert rep["runs"] == len(tasks)


async def test_retrieval_eval_baseline_holds():
    rep = await eval_retrieval(read_jsonl(EVAL_DIR / "retrieval.jsonl"))
    assert rep["recall@3"] >= 0.8  # baseline measured 2026-11-26: 0.857
