"""Acceptance test: no hidden test file is ever readable from inside the agent sandbox.

Covers every task in the repository, through every channel the agent has:
the starting workspace contents, the file tools (relative, absolute, ``..``
and symlink escapes) and shell commands run in the sandbox.
"""

from __future__ import annotations

import hashlib
import os

import pytest

from harness.models import ToolCall
from harness.paths import TASKS
from harness.sandbox import LocalSandbox, bwrap_available, local_node_modules
from harness.task import discover_tasks
from harness.tools import ToolExecutor
from harness.workspace import build_workspace

TASK_LIST = discover_tasks(TASKS)
HIDDEN = [(t, p) for t in TASK_LIST for p in sorted(t.hidden_tests_dir.rglob("*")) if p.is_file()]


def _digest(path) -> str:
    return hashlib.sha256(path.read_bytes()).hexdigest()


@pytest.mark.parametrize("task", TASK_LIST, ids=lambda t: t.id)
def test_starting_workspace_contains_no_hidden_test_content(task):
    hidden_digests = {_digest(p) for p in task.hidden_tests_dir.rglob("*") if p.is_file()}
    if not hidden_digests:
        pytest.skip("task has no hidden tests")
    with build_workspace(task, node_modules=local_node_modules()) as ws:
        for path in ws.root.rglob("*"):
            if (
                path.is_file()
                and not path.is_symlink()
                and ".git" not in path.parts
                and "node_modules" not in path.parts
            ):
                assert _digest(path) not in hidden_digests, f"{path} has the same content as a hidden test"
        # The repository (and so tasks/) is not an ancestor of the workspace.
        assert TASKS.resolve() not in ws.root.resolve().parents


@pytest.fixture
def agent_env(py_task):
    with build_workspace(py_task) as ws:
        sandbox = LocalSandbox(ws.root)
        yield ws, sandbox, ToolExecutor(ws.root, sandbox)


def _read(executor, path):
    return executor.execute(ToolCall("t", "read_file", {"path": path}))


@pytest.mark.parametrize(
    "task,hidden",
    HIDDEN[:12] or [pytest.param(None, None, marks=pytest.mark.skip)],
    ids=lambda x: getattr(x, "id", None) or getattr(x, "name", ""),
)
def test_file_tools_refuse_hidden_test_paths(task, hidden, agent_env):
    ws, _, executor = agent_env
    attempts = [
        str(hidden),  # absolute host path
        os.path.relpath(hidden, ws.root),  # relative path climbing out with ..
        f"../../{hidden.relative_to(TASKS.parent)}",
        "/work/../" + str(hidden).lstrip("/"),
    ]
    for attempt in attempts:
        outcome = _read(executor, attempt)
        assert outcome.is_error and outcome.path_escape, attempt
        assert hidden.read_text()[:40] not in outcome.content


def test_symlink_escape_is_refused(agent_env, py_task):
    ws, _, executor = agent_env
    hidden = next(p for p in py_task.hidden_tests_dir.rglob("*.py"))
    (ws.root / "innocent.py").symlink_to(hidden)
    outcome = _read(executor, "innocent.py")
    assert outcome.is_error and outcome.path_escape
    outcome = executor.execute(ToolCall("t", "list_files", {"path": "../.."}))
    assert outcome.is_error and outcome.path_escape


def test_write_tools_cannot_escape(agent_env):
    ws, _, executor = agent_env
    outcome = executor.execute(ToolCall("t", "write_file", {"path": "../escape.txt", "content": "x"}))
    assert outcome.is_error and outcome.path_escape
    assert not (ws.root.parent / "escape.txt").exists()


@pytest.mark.skipif(not bwrap_available(), reason="bubblewrap not usable on this host")
def test_shell_commands_cannot_read_hidden_tests(agent_env, py_task):
    ws, sandbox, _ = agent_env
    assert sandbox.isolation == "bwrap"
    hidden = next(p for p in py_task.hidden_tests_dir.rglob("*.py"))
    result = sandbox.exec(
        f"cat {hidden}; ls {TASKS}; find / -name '*hidden*' -path '*tasks*' 2>/dev/null | head", timeout_s=60
    )
    assert hidden.read_text()[:40] not in result.output
    assert "No such file or directory" in result.output
    # A symlink created inside the sandbox resolves inside the sandbox, where the target does not exist.
    result = sandbox.exec(f"ln -s {hidden} leak.py && cat leak.py", timeout_s=30)
    assert result.exit_code != 0 and hidden.read_text()[:40] not in result.output


@pytest.mark.skipif(not bwrap_available(), reason="bubblewrap not usable on this host")
def test_sandbox_has_no_network(agent_env):
    _, sandbox, _ = agent_env
    result = sandbox.exec(
        "python -c \"import socket; socket.create_connection(('1.1.1.1', 53), timeout=3)\"", timeout_s=30
    )
    assert result.exit_code != 0
