from harness.agent_loop import NUDGE, run_episode, system_prompt
from harness.models import ModelError, ModelTurn, ToolCall, Usage
from harness.sandbox import LocalSandbox
from harness.tools import ToolExecutor
from harness.workspace import build_workspace


class Scripted:
    def __init__(self, turns):
        self.turns = list(turns)
        self.seen = []

    def next_turn(self, system, tools, messages):
        self.seen.append((system, [t.name for t in tools], list(messages)))
        item = self.turns.pop(0) if self.turns else ModelTurn("idle", [], Usage(), "end_turn")
        if isinstance(item, Exception):
            raise item
        return item


def turn(*calls, text="", usage=Usage(10, 5)):
    return ModelTurn(text, [ToolCall(f"c{i}", n, a) for i, (n, a) in enumerate(calls)], usage, "tool_use")


def episode(task, adapter, **kw):
    with build_workspace(task) as ws:
        executor = ToolExecutor(ws.root, LocalSandbox(ws.root, isolation="none"))
        result = run_episode(task, adapter, executor, **kw)
        return result, ws.diff()


def test_same_system_prompt_and_tools_for_every_model(py_task):
    adapter = Scripted([turn(("submit", {"summary": "x"}))])
    episode(py_task, adapter)
    system, tools, messages = adapter.seen[0]
    assert system == system_prompt(py_task)
    assert tools == ["list_files", "read_file", "write_file", "run_command", "submit"]
    assert messages[0] == {"role": "user", "content": py_task.prompt.strip()}


def test_submit_ends_the_episode_and_usage_is_summed(py_task):
    adapter = Scripted([
        turn(("write_file", {"path": "NOTES.md", "content": "hi\n"})),
        turn(("run_command", {"command": "echo ok"}), ("submit", {"summary": "done"})),
    ])
    result, diff = episode(py_task, adapter)
    assert result.stop_reason == "submitted" and result.steps == 2 and result.tool_calls == 3
    assert result.usage.input_tokens == 20 and result.submit_summary == "done"
    assert "NOTES.md" in diff


def test_step_limit(py_task):
    py_task = py_task.model_copy(update={"limits": py_task.limits.model_copy(update={"max_steps": 3})})
    adapter = Scripted([turn(("list_files", {})) for _ in range(10)])
    result, _ = episode(py_task, adapter)
    assert result.stop_reason == "max_steps" and result.steps == 3


def test_nudge_once_then_stop_without_tool_calls(py_task):
    adapter = Scripted([ModelTurn("thinking", [], Usage(), "end_turn"), ModelTurn("still", [], Usage(), "end_turn")])
    result, _ = episode(py_task, adapter)
    assert result.stop_reason == "no_tool_calls"
    assert adapter.seen[1][2][-1] == {"role": "user", "content": NUDGE}


def test_model_errors_and_refusals_are_recorded(py_task):
    result, _ = episode(py_task, Scripted([ModelError("429", kind="rate_limit")]))
    assert result.stop_reason == "model_error" and result.error_kind == "rate_limit"
    result, _ = episode(py_task, Scripted([ModelTurn("no", [], Usage(), "refusal")]))
    assert result.stop_reason == "refusal"


def test_wall_clock_timeout(py_task):
    ticks = iter([0, 0, 10_000, 10_000, 10_000])
    adapter = Scripted([turn(("list_files", {})) for _ in range(5)])
    result, _ = episode(py_task, adapter, clock=lambda: next(ticks))
    assert result.stop_reason == "timeout"


def test_tool_errors_are_returned_to_the_model(py_task):
    adapter = Scripted([turn(("read_file", {"path": "../../etc/passwd"})), turn(("submit", {"summary": "x"}))])
    result, _ = episode(py_task, adapter)
    tool_events = [e for e in result.trajectory if e["type"] == "tool_call"]
    assert tool_events[0]["path_escape"] and tool_events[0]["is_error"]
    results_msg = adapter.seen[1][2][-1]
    assert results_msg["role"] == "tool_results" and results_msg["results"][0]["is_error"]
