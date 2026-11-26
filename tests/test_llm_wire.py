"""The adapters' message conversion, checked without calling any API."""

from types import SimpleNamespace

from helpdesk.llm import AnthropicLLM, Message, OpenAICompatLLM, ToolCall


def convo():
    return [
        Message("user", "hi"),
        Message("assistant", "", tool_calls=[ToolCall("a", "search_runbooks", {"query": "vpn"}),
                                             ToolCall("b", "check_service", {"name": "mail"})]),
        Message("tool", '{"r":1}', tool_call_id="a"),
        Message("tool", '{"r":2}', tool_call_id="b"),
    ]


def test_anthropic_groups_tool_results_in_one_user_turn():
    wire = AnthropicLLM.to_wire(convo())
    assert [m["role"] for m in wire] == ["user", "assistant", "user"]
    assert [b["tool_use_id"] for b in wire[2]["content"]] == ["a", "b"]
    first = wire[1]["content"][0]
    assert first == {"type": "tool_use", "id": "a", "name": "search_runbooks", "input": {"query": "vpn"}}


def test_openai_wire_has_system_and_tool_messages():
    wire = OpenAICompatLLM.to_wire("sys", convo())
    assert wire[0] == {"role": "system", "content": "sys"}
    assert wire[2]["tool_calls"][1]["function"]["name"] == "check_service"
    assert [m["role"] for m in wire[3:]] == ["tool", "tool"]


async def test_anthropic_parses_response_with_fake_client():
    class FakeMessages:
        async def create(self, **kw):
            self.kw = kw
            return SimpleNamespace(
                content=[SimpleNamespace(type="text", text="thinking"),
                         SimpleNamespace(type="tool_use", id="t1", name="get_ticket", input={"ticket_id": 3})],
                usage=SimpleNamespace(input_tokens=11, output_tokens=7))

    fake = SimpleNamespace(messages=FakeMessages())
    llm = AnthropicLLM("test-model", client=fake)
    r = await llm.complete("sys", [Message("user", "hi")], [{"name": "get_ticket", "description": "d",
                                                            "parameters": {"type": "object"}}])
    assert r.tool_calls[0].args == {"ticket_id": 3} and r.usage.output_tokens == 7
    assert fake.messages.kw["tool_choice"] == {"type": "any"}
