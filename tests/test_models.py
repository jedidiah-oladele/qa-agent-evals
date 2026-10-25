"""Provider adapters, tested against mock SDK clients (no network, no keys)."""

from types import SimpleNamespace as NS

import pytest

from harness.config import AgentModel, Pricing, models_config
from harness.models import (
    AnthropicAdapter,
    ModelError,
    OpenAIAdapter,
    ToolCall,
    Usage,
    complete_text,
    cost_usd,
    make_adapter,
)
from harness.tools import TOOL_SPECS


class Block(NS):
    def model_dump(self, **_):
        return {k: v for k, v in vars(self).items()}


class MockAnthropic:
    def __init__(self, responses):
        self.responses = list(responses)
        self.requests = []
        self.messages = self

    def create(self, **body):
        self.requests.append(body)
        return self.responses.pop(0)


def anthropic_response(blocks, stop="tool_use", usage=None):
    usage = usage or NS(
        input_tokens=100, output_tokens=50, cache_read_input_tokens=1000, cache_creation_input_tokens=200
    )
    return NS(id="msg_1", content=blocks, stop_reason=stop, usage=usage, stop_details=None)


def spec(provider="anthropic", key="claude-opus-5-5"):
    return models_config().agent(key) if provider != "test" else AgentModel(key="t", provider="anthropic", model_id="t")


def test_model_ids_come_from_config():
    config = models_config()
    assert [a.model_id for a in config.agents] == ["claude-opus-5-5", "claude-sonnet-5-5", "gpt-6-astra"]
    assert config.judge.primary.model_id == "gpt-6.1-sol"
    assert config.judge.cross_check.model_id == "claude-sonnet-5-5"
    assert config.judge.cross_check.sample_rate == 0.2


def test_anthropic_request_and_parse():
    thinking = Block(type="thinking", thinking="", signature="sig")
    text = Block(type="text", text="Let me look.")
    use = Block(type="tool_use", id="tu_1", name="read_file", input={"path": "a.py"})
    client = MockAnthropic([anthropic_response([thinking, text, use])])
    adapter = AnthropicAdapter(spec(), client)
    turn = adapter.next_turn("SYS", TOOL_SPECS, [{"role": "user", "content": "fix it"}])
    body = client.requests[0]
    assert body["model"] == "claude-opus-5-5"
    assert body["system"] == "SYS"
    assert body["output_config"] == {"effort": "high"}
    assert body["cache_control"] == {"type": "ephemeral"}
    assert "temperature" not in body and "fallbacks" not in body
    assert [t["name"] for t in body["tools"]] == [t.name for t in TOOL_SPECS]
    assert turn.tool_calls == [ToolCall("tu_1", "read_file", {"path": "a.py"})]
    assert turn.usage == Usage(100, 50, 1000, 200)
    assert turn.payload[0]["type"] == "thinking"  # replayed unchanged next turn


def test_anthropic_replays_assistant_payload_and_groups_tool_results():
    payload = [
        {"type": "thinking", "thinking": "", "signature": "s"},
        {"type": "tool_use", "id": "a", "name": "list_files", "input": {}},
        {"type": "tool_use", "id": "b", "name": "read_file", "input": {"path": "x"}},
    ]
    messages = [
        {"role": "user", "content": "task"},
        {"role": "assistant", "text": "", "tool_calls": [], "payload": payload},
        {
            "role": "tool_results",
            "results": [
                {"id": "a", "name": "list_files", "content": "x"},
                {"id": "b", "name": "read_file", "content": "y", "is_error": True},
            ],
        },
    ]
    converted = AnthropicAdapter.to_provider(messages)
    assert converted[1] == {"role": "assistant", "content": payload}
    assert converted[2]["role"] == "user" and len(converted[2]["content"]) == 2
    assert converted[2]["content"][1] == {"type": "tool_result", "tool_use_id": "b", "content": "y", "is_error": True}


def test_anthropic_refusal_is_reported():
    response = anthropic_response([Block(type="text", text="I can't help")], stop="refusal")
    response.stop_details = NS(category="cyber")
    turn = AnthropicAdapter(spec(), MockAnthropic([response])).next_turn("s", TOOL_SPECS, [])
    assert turn.stop_reason == "refusal" and turn.extra["refusal_category"] == "cyber"


def test_anthropic_api_errors_become_model_errors():
    import anthropic
    import httpx2

    request = httpx2.Request("POST", "https://api.anthropic.com/v1/messages")
    error = anthropic.RateLimitError("slow down", response=httpx2.Response(429, request=request), body=None)

    class Failing(MockAnthropic):
        def create(self, **body):
            raise error

    with pytest.raises(ModelError) as info:
        AnthropicAdapter(spec(), Failing([])).next_turn("s", TOOL_SPECS, [])
    assert info.value.kind == "rate_limit"


class MockOpenAI:
    def __init__(self, response):
        self.response = response
        self.requests = []
        self.responses = self

    def create(self, **body):
        self.requests.append(body)
        return self.response


class Item(NS):
    def model_dump(self, **_):
        return {k: (v if not isinstance(v, list) else [vars(x) for x in v]) for k, v in vars(self).items()}


def test_openai_request_and_parse():
    output = [
        Item(type="reasoning", id="rs_1", encrypted_content="enc", summary=[]),
        Item(type="message", content=[NS(type="output_text", text="Looking")]),
        Item(type="function_call", call_id="call_1", name="run_command", arguments='{"command": "pytest"}'),
    ]
    usage = NS(input_tokens=1200, output_tokens=300, input_tokens_details=NS(cached_tokens=1000))
    client = MockOpenAI(NS(id="resp_1", output=output, usage=usage, status="completed"))
    adapter = OpenAIAdapter(spec(key="gpt-6-astra"), client)
    turn = adapter.next_turn("SYS", TOOL_SPECS, [{"role": "user", "content": "task"}])
    body = client.requests[0]
    assert body["model"] == "gpt-6-astra" and body["instructions"] == "SYS"
    assert body["store"] is False and "reasoning.encrypted_content" in body["include"]
    assert body["reasoning"] == {"effort": "high"}
    assert body["tools"][0]["type"] == "function"
    assert turn.tool_calls == [ToolCall("call_1", "run_command", {"command": "pytest"})]
    assert turn.usage == Usage(200, 300, 1000, 0)
    assert turn.text == "Looking"


def test_openai_replays_items_and_tool_outputs():
    payload = [
        {"type": "reasoning", "id": "rs"},
        {"type": "function_call", "call_id": "c", "name": "submit", "arguments": "{}"},
    ]
    items = OpenAIAdapter.to_provider(
        [
            {"role": "user", "content": "t"},
            {"role": "assistant", "text": "", "tool_calls": [], "payload": payload},
            {"role": "tool_results", "results": [{"id": "c", "name": "submit", "content": "submitted"}]},
        ]
    )
    assert items[1:3] == payload
    assert items[3] == {"type": "function_call_output", "call_id": "c", "output": "submitted"}


def test_openai_invalid_tool_json_is_flagged():
    output = [Item(type="function_call", call_id="c", name="read_file", arguments="{not json")]
    usage = NS(input_tokens=1, output_tokens=1, input_tokens_details=None)
    turn = OpenAIAdapter(
        spec(key="gpt-6-astra"), MockOpenAI(NS(id="r", output=output, usage=usage, status="completed"))
    ).next_turn("s", [], [])
    assert "__invalid_json__" in turn.tool_calls[0].arguments


def test_cost_accounting():
    pricing = Pricing(input=4.0, output=20.0, cache_read=0.2, cache_write=5.0)
    usage = Usage(input_tokens=1_000_000, output_tokens=100_000, cache_read_tokens=2_000_000, cache_write_tokens=0)
    assert cost_usd(usage, pricing) == pytest.approx(4.0 + 2.0 + 0.4)
    assert cost_usd(usage, None) is None


def test_real_adapters_refuse_to_start_without_keys():
    with pytest.raises(ModelError) as info:
        make_adapter(spec())
    assert info.value.kind == "missing_key"
    with pytest.raises(ModelError):
        make_adapter(spec(key="gpt-6-astra"))


def test_complete_text_uses_the_given_client():
    client = MockAnthropic([anthropic_response([Block(type="text", text='{"verdict": "pass"}')], stop="end_turn")])
    text, usage = complete_text("anthropic", "claude-sonnet-5-5", "sys", "prompt", client=client)
    assert text == '{"verdict": "pass"}' and client.requests[0]["model"] == "claude-sonnet-5-5"
    assert usage.output_tokens == 50
