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


class FakeDemoLLM:
    """Offline stand-in for UI work and tests (LLM_PROVIDER=fake). Not a model: it follows a fixed plan.

    search_runbooks -> check_service (if the message names a known service) -> restart_service (if it was down)
    -> create_ticket -> final_answer citing the ticket the tool returned. Stateless: the plan is read from the
    messages of the current run, so one instance serves many runs at once.
    """

    name = "fake (offline demo)"
    _SERVICE_WORDS = {"mail": ("mail", "email", "outlook", "بريد", "ايميل", "إيميل", "الإيميل"),
                      "pbx": ("phone", "pbx", "call", "هاتف", "تلفون", "التلفون"),
                      "intranet": ("intranet", "portal", "انترانت", "الإنترانت")}
    _CATEGORY_WORDS = {"network": ("vpn", "wifi", "network", "شبكة"), "email": ("mail", "بريد", "ايميل", "الإيميل"),
                       "hardware": ("printer", "طابعة", "الطابعة", "laptop"), "access": ("password", "كلمة السر"),
                       "voip": ("phone", "pbx", "هاتف"), "server": ("intranet", "server")}

    def __init__(self, delay_s: float = 0.0) -> None:
        self.delay_s = delay_s

    async def complete(self, system: str, messages: Sequence[Message], tools: list[dict[str, Any]]) -> LLMResponse:
        import asyncio

        if self.delay_s:
            await asyncio.sleep(self.delay_s)
        user = messages[0].content
        low = user.lower()
        lang = "ar" if sum(1 for ch in user if "\u0600" <= ch <= "\u06ff") > len(user) * 0.2 else "en"
        done = [c.name for m in messages if m.role == "assistant" for c in m.tool_calls]
        results = {m.tool_call_id: m.content for m in messages if m.role == "tool"}
        last = {c.name: results.get(c.id, "") for m in messages if m.role == "assistant" for c in m.tool_calls}
        known = {t["name"]: t for t in tools}
        services_desc = known.get("check_service", {}).get("description", "")
        service = next((s for s, words in self._SERVICE_WORDS.items()
                        if s in services_desc and any(w in low for w in words)), None)
        turn = len(done)

        def call(tool: str, /, **args: Any) -> LLMResponse:
            return LLMResponse("", [ToolCall(f"fake-{turn}-{tool}", tool, args)],
                               Usage(400 + 60 * turn + len(user) // 4, 40))

        if "search_runbooks" not in done:
            return call("search_runbooks", query=user[:200])
        if service and "check_service" not in done:
            return call("check_service", name=service)
        if service and '"down"' in last.get("check_service", "") and "restart_service" not in done:
            return call("restart_service", name=service, reason=f"check_service shows {service} is down")
        if "create_ticket" not in done:
            category = next((c for c, words in self._CATEGORY_WORDS.items() if any(w in low for w in words)), "other")
            down = '"down"' in last.get("check_service", "")
            title = (f"{service} is down" if down else user[:60].strip()) or "Help request"
            return call("create_ticket", title=title.ljust(5, "."), description=f"User reported: {user[:300]}",
                        priority="high" if down else "medium", category=category)
        try:
            ticket = json.loads(last.get("create_ticket", "{}")).get("ticket_id")
        except json.JSONDecodeError:
            ticket = None
        if lang == "ar":
            answer = (f"فتحت تذكرة رقم {ticket} وسيتواصل معك فريق الدعم." if ticket
                      else "سيتواصل معك فريق الدعم.")
        else:
            answer = (f"I followed the guide and opened ticket {ticket}; the support team will follow up."
                      if ticket else "The support team will follow up.")
        return call("final_answer", answer=answer, language=lang, ticket_id=ticket, needs_human=True)


def build_llm(provider: str, model: str, base_url: str | None = None) -> LLM:
    if provider == "anthropic":
        return AnthropicLLM(model)
    if provider == "openai":
        return OpenAICompatLLM(model, base_url=base_url)
    if provider == "fake":
        return FakeDemoLLM(delay_s=0.35)
    raise ValueError(f"unknown LLM_PROVIDER {provider!r} (anthropic | openai | fake)")
