"""A small provider-neutral interface for tool-calling chat models.

Two real adapters (Anthropic Messages API, and any OpenAI-compatible Chat Completions endpoint: OpenAI,
OpenRouter, vLLM, Ollama) and one test double (ScriptedLLM) that replays fixed responses.
"""

from __future__ import annotations

import json
from collections.abc import Sequence
from dataclasses import dataclass, field
from typing import Any, Literal, Protocol


@dataclass
class ToolCall:
    id: str
    name: str
    args: dict[str, Any]


@dataclass
class Usage:
    input_tokens: int = 0
    output_tokens: int = 0

    def add(self, other: Usage) -> None:
        self.input_tokens += other.input_tokens
        self.output_tokens += other.output_tokens


@dataclass
class Message:
    role: Literal["user", "assistant", "tool"]
    content: str = ""
    tool_calls: list[ToolCall] = field(default_factory=list)  # assistant only
    tool_call_id: str = ""  # tool only


@dataclass
class LLMResponse:
    text: str
    tool_calls: list[ToolCall]
    usage: Usage


class LLM(Protocol):
    name: str

    async def complete(self, system: str, messages: Sequence[Message], tools: list[dict[str, Any]]) -> LLMResponse: ...


# ------------------------------------------------------------------ Anthropic


class AnthropicLLM:
    def __init__(self, model: str, client: Any | None = None, max_tokens: int = 1024) -> None:
        if not model:
            raise ValueError("set LLM_MODEL")
        if client is None:
            import anthropic

            client = anthropic.AsyncAnthropic()
        self.client, self.model, self.max_tokens = client, model, max_tokens
        self.name = f"anthropic:{model}"

    @staticmethod
    def to_wire(messages: Sequence[Message]) -> list[dict[str, Any]]:
        out: list[dict[str, Any]] = []
        for m in messages:
            if m.role == "user":
                out.append({"role": "user", "content": m.content})
            elif m.role == "assistant":
                blocks: list[dict[str, Any]] = [{"type": "text", "text": m.content}] if m.content else []
                blocks += [{"type": "tool_use", "id": c.id, "name": c.name, "input": c.args} for c in m.tool_calls]
                out.append({"role": "assistant", "content": blocks})
            else:  # tool results travel in a user turn; consecutive results share one turn
                block = {"type": "tool_result", "tool_use_id": m.tool_call_id, "content": m.content}
                if out and out[-1]["role"] == "user" and isinstance(out[-1]["content"], list):
                    out[-1]["content"].append(block)
                else:
                    out.append({"role": "user", "content": [block]})
        return out

    async def complete(self, system: str, messages: Sequence[Message], tools: list[dict[str, Any]]) -> LLMResponse:
        resp = await self.client.messages.create(
            model=self.model,
            max_tokens=self.max_tokens,
            system=system,
            messages=self.to_wire(messages),
            tools=[{"name": t["name"], "description": t["description"], "input_schema": t["parameters"]}
                   for t in tools],
            tool_choice={"type": "any"},
        )
        text = "".join(b.text for b in resp.content if b.type == "text")
        calls = [ToolCall(b.id, b.name, dict(b.input)) for b in resp.content if b.type == "tool_use"]
        return LLMResponse(text, calls, Usage(resp.usage.input_tokens, resp.usage.output_tokens))


# ------------------------------------------------------------------ OpenAI-compatible


class OpenAICompatLLM:
    def __init__(self, model: str, base_url: str | None = None, client: Any | None = None) -> None:
        if not model:
            raise ValueError("set LLM_MODEL")
        if client is None:
            import openai

            client = openai.AsyncOpenAI(base_url=base_url, max_retries=6, timeout=120)
        self.client, self.model = client, model
        self.name = f"openai:{model}"

    @staticmethod
    def to_wire(system: str, messages: Sequence[Message]) -> list[dict[str, Any]]:
        out: list[dict[str, Any]] = [{"role": "system", "content": system}]
        for m in messages:
            if m.role == "user":
                out.append({"role": "user", "content": m.content})
            elif m.role == "assistant":
                msg: dict[str, Any] = {"role": "assistant", "content": m.content or None}
                if m.tool_calls:
                    msg["tool_calls"] = [
                        {"id": c.id, "type": "function",
                         "function": {"name": c.name, "arguments": json.dumps(c.args, ensure_ascii=False)}}
                        for c in m.tool_calls
                    ]
                out.append(msg)
            else:
                out.append({"role": "tool", "tool_call_id": m.tool_call_id, "content": m.content})
        return out

    async def complete(self, system: str, messages: Sequence[Message], tools: list[dict[str, Any]]) -> LLMResponse:
        resp = await self.client.chat.completions.create(
            model=self.model,
            messages=self.to_wire(system, messages),
            tools=[{"type": "function", "function": t} for t in tools],
            tool_choice="required",
        )
        msg = resp.choices[0].message
        calls = []
        for c in msg.tool_calls or []:
            try:
                args = json.loads(c.function.arguments or "{}")
            except json.JSONDecodeError:
                args = {"__unparseable__": c.function.arguments}
            calls.append(ToolCall(c.id, c.function.name, args if isinstance(args, dict) else {"__value__": args}))
        u = resp.usage
        usage = Usage(u.prompt_tokens, u.completion_tokens) if u else Usage()
        return LLMResponse(msg.content or "", calls, usage)


# ------------------------------------------------------------------ test double


class ScriptedLLM:
    """Replays a fixed list of responses. For tests only: it proves the loop, not the model."""

    def __init__(self, script: list[LLMResponse]) -> None:
        self.script = list(script)
        self.calls: list[list[Message]] = []
        self.name = "scripted"

    async def complete(self, system: str, messages: Sequence[Message], tools: list[dict[str, Any]]) -> LLMResponse:
        self.calls.append(list(messages))
        if not self.script:
            raise RuntimeError("ScriptedLLM ran out of responses")
        return self.script.pop(0)


def build_llm(provider: str, model: str, base_url: str | None = None) -> LLM:
    if provider == "anthropic":
        return AnthropicLLM(model)
    if provider == "openai":
        return OpenAICompatLLM(model, base_url=base_url)
    raise ValueError(f"unknown LLM_PROVIDER {provider!r} (anthropic | openai)")
