"""Native CLI adapters, exercised with fake `claude` / `codex` executables (never the real CLIs)."""

import json
import stat

import pytest

from harness.native import ClaudeCodeHarness, CodexHarness
from harness.sandbox import LocalSandbox
from harness.workspace import build_workspace

CLAUDE_EVENTS = [
    {"type": "system", "subtype": "init"},
    {"type": "assistant", "message": {"content": [{"type": "text", "text": "Reading"},
                                                  {"type": "tool_use", "name": "Read", "input": {"file_path": "src/shopcore/tax.py"}}]}},
    {"type": "assistant", "message": {"content": [{"type": "tool_use", "name": "Bash", "input": {"command": "pytest -q"}}]}},
    {"type": "result", "subtype": "success", "num_turns": 2, "total_cost_usd": 0.42, "is_error": False,
     "usage": {"input_tokens": 1000, "output_tokens": 200, "cache_read_input_tokens": 5000,
               "cache_creation_input_tokens": 300}},
]
CODEX_EVENTS = [
    {"type": "thread.started"},
    {"type": "item.completed", "item": {"type": "command_execution", "command": "pytest -q"}},
    {"type": "item.completed", "item": {"type": "file_change", "changes": [{"path": "src/a.py"}]}},
    {"type": "turn.completed", "usage": {"input_tokens": 3000, "cached_input_tokens": 2000, "output_tokens": 400}},
]


def fake_cli(tmp_path, name, events, edit=None):
    script = tmp_path / name
    lines = "\n".join(f"echo {json.dumps(json.dumps(e))}" for e in events)
    script.write_text(f"#!/bin/bash\n{edit or ''}\n{lines}\n")
    script.chmod(script.stat().st_mode | stat.S_IEXEC)
    return str(script)


def test_claude_code_command_and_parse(py_task):
    harness = ClaudeCodeHarness("claude-opus-5-5", cli_path="/opt/bin/claude")
    command = harness.command(py_task)
    assert "--model claude-opus-5-5" in command and "--output-format stream-json" in command
    assert f"--max-turns {py_task.limits.max_steps}" in command and "WebFetch" in command
    result = harness.parse("\n".join(json.dumps(e) for e in CLAUDE_EVENTS), py_task)
    assert result.stop_reason == "submitted" and result.steps == 2 and result.cost_usd == 0.42
    assert result.usage.cache_read_tokens == 5000
    names = [e["name"] for e in result.trajectory if e["type"] == "tool_call"]
    assert names == ["read_file", "run_command"]


def test_codex_parse(py_task):
    result = CodexHarness("gpt-6-astra", cli_path="/x/codex").parse(
        "noise\n" + "\n".join(json.dumps(e) for e in CODEX_EVENTS), py_task)
    assert result.usage.input_tokens == 1000 and result.usage.cache_read_tokens == 2000
    assert [e["name"] for e in result.trajectory if e["type"] == "tool_call"] == ["run_command", "write_file"]


def test_native_run_in_a_sandbox_with_a_fake_cli(tmp_path, py_task):
    cli = fake_cli(tmp_path, "claude", CLAUDE_EVENTS, edit='echo "# touched" >> src/shopcore/tax.py')
    harness = ClaudeCodeHarness("claude-opus-5-5", cli_path=cli)
    with build_workspace(py_task) as ws:
        sandbox = LocalSandbox(ws.root, isolation="none", network=True)
        result = harness.run(py_task, sandbox, api_key="test-key-not-real")
        assert result.stop_reason == "submitted" and result.error is None
        assert "# touched" in ws.diff()


def test_missing_cli_is_skipped_cleanly(py_task):
    from harness.config import models_config
    from harness.run import Participant, run_one
    from harness.config import run_config

    config = models_config()
    native = config.native_harnesses[0]
    p = Participant(native.key, native.adapter, config.agent(native.model_key), native)
    import harness.native.base as base

    original = base.shutil.which
    base.shutil.which = lambda name: None
    try:
        record = run_one("t", p, py_task, 0, backend="local", run_cfg=run_config(), judges=None, dry_run=False)
    finally:
        base.shutil.which = original
    assert record["status"] == "skipped" and "not found" in record["error"]


@pytest.mark.parametrize("cls", [ClaudeCodeHarness, CodexHarness])
def test_availability_follows_the_path(cls):
    assert cls("m", cli_path="/definitely/missing").available() is True  # explicit path is trusted
    harness = cls("m")
    assert harness.available() == (harness.cli_path is not None)
