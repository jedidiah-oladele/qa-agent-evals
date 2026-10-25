"""Provider adapters behind one interface, plus token and cost accounting.

Every agent model runs through the *same* loop (``harness/agent_loop.py``)
with the same system prompt and tools; an adapter only translates the neutral
conversation format to and from one provider's API:

* ``AnthropicAdapter``: Messages API with client tools, adaptive thinking
  (the default for Claude Opus 5.5 / Sonnet 5.5), a pinned ``effort`` and
  automatic prompt caching. Assistant turns are replayed exactly as returned,
  including thinking blocks, as the API requires.
* ``OpenAIAdapter``: Responses API with function tools, ``store=False`` and
  encrypted reasoning items replayed between turns.

Temperature is left at each provider's default. Server-side refusal
fallbacks to *other* models are deliberately not enabled: a fallback would
silently grade a different model than the one in the results table. A refusal
ends the episode and is recorded as such.

Neutral conversation entries::

    {"role": "user", "content": str}
    {"role": "assistant", "text": str, "tool_calls": [ToolCall...], "payload": <provider-native>}
    {"role": "tool_results", "results": [{"id", "name", "content", "is_error"}]}
"""

from __future__ import annotations

import json
import os
from abc import ABC, abstractmethod
from dataclasses import asdict, dataclass, field
from typing import Any

from .config import AgentModel, Pricing


class ModelError(RuntimeError):
    """The provider failed after the SDK's own retries (or refused)."""

    def __init__(self, message: str, *, kind: str = "api") -> None:
        super().__init__(message)
        self.kind = kind  # api | rate_limit | auth | refusal | bad_request | missing_key


@dataclass
class Usage:
    input_tokens: int = 0  # uncached input
    output_tokens: int = 0  # includes reasoning/thinking tokens
    cache_read_tokens: int = 0
    cache_write_tokens: int = 0

    def __add__(self, other: Usage) -> Usage:
        return Usage(
            self.input_tokens + other.input_tokens,
            self.output_tokens + other.output_tokens,
            self.cache_read_tokens + other.cache_read_tokens,
            self.cache_write_tokens + other.cache_write_tokens,
        )

    @property
    def total(self) -> int:
        return self.input_tokens + self.output_tokens + self.cache_read_tokens + self.cache_write_tokens

    def to_dict(self) -> dict[str, int]:
        return asdict(self)


def cost_usd(usage: Usage, pricing: Pricing | None) -> float | None:
    """USD cost from token counts; None when the price is unknown (never guessed)."""
    if pricing is None:
        return None
    return round(
        (
            usage.input_tokens * pricing.input
            + usage.output_tokens * pricing.output
            + usage.cache_read_tokens * pricing.cache_read
            + usage.cache_write_tokens * pricing.cache_write
        )
        / 1_000_000,
        6,
    )


@dataclass
class ToolCall:
    id: str
    name: str
    arguments: dict[str, Any]


@dataclass
class ModelTurn:
    text: str
    tool_calls: list[ToolCall]
    usage: Usage
    stop_reason: str
    payload: Any = None
    raw_id: str | None = None
    extra: dict[str, Any] = field(default_factory=dict)


@dataclass
class ToolSpec:
    name: str
    description: str
    parameters: dict[str, Any]


def require_key(variable: str) -> str:
    value = os.environ.get(variable, "")
    if not value:
        raise ModelError(f"{variable} is not set; real runs read API keys from the environment", kind="missing_key")
    return value


class ModelAdapter(ABC):
    def __init__(self, spec: AgentModel) -> None:
        self.spec = spec

    @property
    def model_id(self) -> str:
        return self.spec.model_id

    @abstractmethod
    def next_turn(self, system: str, tools: list[ToolSpec], messages: list[dict]) -> ModelTurn: ...


# ------------------------------------------------------------- anthropic ---


def _dump(block: Any) -> dict:
    if isinstance(block, dict):
        return block
    return block.model_dump(mode="json", exclude_none=True)


class AnthropicAdapter(ModelAdapter):
    def __init__(self, spec: AgentModel, client: Any | None = None) -> None:
        super().__init__(spec)
        if client is None:
            import anthropic

            client = anthropic.Anthropic(api_key=require_key("ANTHROPIC_API_KEY"), max_retries=6, timeout=600)
        self.client = client

    @staticmethod
    def to_provider(messages: list[dict]) -> list[dict]:
        converted: list[dict] = []
        for entry in messages:
            if entry["role"] == "user":
                converted.append({"role": "user", "content": entry["content"]})
            elif entry["role"] == "assistant":
                content = entry.get("payload")
                if content is None:  # e.g. replayed from a non-Anthropic transcript
                    content = ([{"type": "text", "text": entry["text"]}] if entry.get("text") else []) + [
                        {"type": "tool_use", "id": c.id, "name": c.name, "input": c.arguments}
                        for c in entry.get("tool_calls", [])
                    ]
                converted.append({"role": "assistant", "content": content})
            elif entry["role"] == "tool_results":
                converted.append(
                    {
                        "role": "user",
                        "content": [
                            {
                                "type": "tool_result",
                                "tool_use_id": r["id"],
                                "content": r["content"],
                                "is_error": bool(r.get("is_error")),
                            }
                            for r in entry["results"]
                        ],
                    }
                )
        return converted

    def request(self, system: str, tools: list[ToolSpec], messages: list[dict]) -> dict:
        body: dict[str, Any] = {
            "model": self.spec.model_id,
            "max_tokens": self.spec.max_output_tokens,
            "system": system,
            "tools": [{"name": t.name, "description": t.description, "input_schema": t.parameters} for t in tools],
            "messages": self.to_provider(messages),
            "cache_control": {"type": "ephemeral"},
        }
        if self.spec.effort:
            body["output_config"] = {"effort": self.spec.effort}
        return body

    def next_turn(self, system: str, tools: list[ToolSpec], messages: list[dict]) -> ModelTurn:
        import anthropic

        try:
            response = self.client.messages.create(**self.request(system, tools, messages))
        except anthropic.RateLimitError as exc:
            raise ModelError(str(exc), kind="rate_limit") from exc
        except anthropic.AuthenticationError as exc:
            raise ModelError(str(exc), kind="auth") from exc
        except anthropic.BadRequestError as exc:
            raise ModelError(str(exc), kind="bad_request") from exc
        except anthropic.APIError as exc:
            raise ModelError(str(exc), kind="api") from exc
        texts, calls = [], []
        for block in response.content:
            if block.type == "text":
                texts.append(block.text)
            elif block.type == "tool_use":
                calls.append(ToolCall(block.id, block.name, dict(block.input or {})))
        u = response.usage
        usage = Usage(
            input_tokens=getattr(u, "input_tokens", 0) or 0,
            output_tokens=getattr(u, "output_tokens", 0) or 0,
            cache_read_tokens=getattr(u, "cache_read_input_tokens", 0) or 0,
            cache_write_tokens=getattr(u, "cache_creation_input_tokens", 0) or 0,
        )
        if response.stop_reason == "refusal":
            details = getattr(response, "stop_details", None)
            category = getattr(details, "category", None) if details else None
            turn = ModelTurn(
                "\n".join(texts),
                [],
                usage,
                "refusal",
                [_dump(b) for b in response.content],
                response.id,
                {"refusal_category": category},
            )
            return turn
        return ModelTurn(
            "\n".join(texts),
            calls,
            usage,
            response.stop_reason or "end_turn",
            [_dump(b) for b in response.content],
            response.id,
        )


# ---------------------------------------------------------------- openai ---


class OpenAIAdapter(ModelAdapter):
    def __init__(self, spec: AgentModel, client: Any | None = None) -> None:
        super().__init__(spec)
        if client is None:
            import openai

            client = openai.OpenAI(api_key=require_key("OPENAI_API_KEY"), max_retries=6, timeout=600)
        self.client = client

    @staticmethod
    def to_provider(messages: list[dict]) -> list[dict]:
        items: list[dict] = []
        for entry in messages:
            if entry["role"] == "user":
                items.append({"role": "user", "content": entry["content"]})
            elif entry["role"] == "assistant":
                payload = entry.get("payload")
                if payload is None:
                    if entry.get("text"):
                        items.append({"role": "assistant", "content": entry["text"]})
                    items += [
                        {"type": "function_call", "call_id": c.id, "name": c.name, "arguments": json.dumps(c.arguments)}
                        for c in entry.get("tool_calls", [])
                    ]
                else:
                    items.extend(payload)
            elif entry["role"] == "tool_results":
                items += [
                    {"type": "function_call_output", "call_id": r["id"], "output": r["content"]}
                    for r in entry["results"]
                ]
        return items

    def request(self, system: str, tools: list[ToolSpec], messages: list[dict]) -> dict:
        body: dict[str, Any] = {
            "model": self.spec.model_id,
            "instructions": system,
            "input": self.to_provider(messages),
            "tools": [
                {
                    "type": "function",
                    "name": t.name,
                    "description": t.description,
                    "parameters": t.parameters,
                    "strict": False,
                }
                for t in tools
            ],
            "max_output_tokens": self.spec.max_output_tokens,
            "store": False,
            "include": ["reasoning.encrypted_content"],
        }
        if self.spec.effort:
            body["reasoning"] = {"effort": self.spec.effort}
        return body

    def next_turn(self, system: str, tools: list[ToolSpec], messages: list[dict]) -> ModelTurn:
        import openai

        try:
            response = self.client.responses.create(**self.request(system, tools, messages))
        except openai.RateLimitError as exc:
            raise ModelError(str(exc), kind="rate_limit") from exc
        except openai.AuthenticationError as exc:
            raise ModelError(str(exc), kind="auth") from exc
        except openai.BadRequestError as exc:
            raise ModelError(str(exc), kind="bad_request") from exc
        except openai.APIError as exc:
            raise ModelError(str(exc), kind="api") from exc
        texts, calls, payload = [], [], []
        refused = False
        for item in response.output:
            payload.append(_dump(item))
            if item.type == "message":
                for part in item.content:
                    if part.type == "output_text":
                        texts.append(part.text)
                    elif part.type == "refusal":
                        refused = True
                        texts.append(getattr(part, "refusal", ""))
            elif item.type == "function_call":
                try:
                    arguments = json.loads(item.arguments or "{}")
                except json.JSONDecodeError:
                    arguments = {"__invalid_json__": item.arguments}
                calls.append(ToolCall(item.call_id, item.name, arguments))
        u = response.usage
        cached = getattr(getattr(u, "input_tokens_details", None), "cached_tokens", 0) or 0
        usage = Usage(
            input_tokens=(u.input_tokens or 0) - cached, output_tokens=u.output_tokens or 0, cache_read_tokens=cached
        )
        status = getattr(response, "status", "completed")
        stop = (
            "refusal"
            if refused
            else ("tool_use" if calls else ("max_tokens" if status == "incomplete" else "end_turn"))
        )
        return ModelTurn("\n".join(texts), calls, usage, stop, payload, response.id)


def make_adapter(spec: AgentModel, client: Any | None = None, task: Any | None = None, run_index: int = 0):
    if spec.provider == "anthropic":
        return AnthropicAdapter(spec, client)
    if spec.provider == "openai":
        return OpenAIAdapter(spec, client)
    from .fake_model import FakeModel

    return FakeModel(spec, task=task, run_index=run_index)


def complete_text(
    provider: str, model_id: str, system: str, prompt: str, *, max_tokens: int = 2000, client: Any | None = None
) -> tuple[str, Usage]:
    """One plain completion (used by the rubric judge)."""
    if provider == "anthropic":
        import anthropic

        client = client or anthropic.Anthropic(api_key=require_key("ANTHROPIC_API_KEY"), max_retries=6)
        response = client.messages.create(
            model=model_id, max_tokens=max_tokens, system=system, messages=[{"role": "user", "content": prompt}]
        )
        text = "".join(b.text for b in response.content if b.type == "text")
        u = response.usage
        return text, Usage(
            u.input_tokens or 0,
            u.output_tokens or 0,
            getattr(u, "cache_read_input_tokens", 0) or 0,
            getattr(u, "cache_creation_input_tokens", 0) or 0,
        )
    if provider == "openai":
        import openai

        client = client or openai.OpenAI(api_key=require_key("OPENAI_API_KEY"), max_retries=6)
        response = client.responses.create(
            model=model_id, instructions=system, input=prompt, max_output_tokens=max_tokens, store=False
        )
        u = response.usage
        cached = getattr(getattr(u, "input_tokens_details", None), "cached_tokens", 0) or 0
        return response.output_text, Usage((u.input_tokens or 0) - cached, u.output_tokens or 0, cached)
    raise ValueError(f"unknown judge provider {provider!r}")
