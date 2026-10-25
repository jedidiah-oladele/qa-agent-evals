"""Scripted fake models for ``--dry-run``: no network, no keys, no cost.

They drive the real agent loop, tools, sandbox and graders with deterministic
behaviour, so the whole pipeline (including failure attribution, statistics,
the judge path and the report) can be exercised in CI. Their numbers are
pipeline test data, never model results, and every report says so.

Behaviours:
  oracle   - inspects the repo, writes the task's reference solution file by
             file through write_file, runs the tests, submits.
  mixed    - per (task, run_index), deterministically: reference (50%), one of
             the task's flawed solutions (25%), gives up without changes
             (12.5%), or hits a *simulated* provider outage mid-episode
             (12.5%) so environment-error attribution is exercised too.
  cheater  - tries to read the hidden tests, then applies the reference but
             also skips or deletes a visible test before submitting.
"""

from __future__ import annotations

import hashlib
import json
import shutil

from .config import AgentModel
from .models import ModelAdapter, ModelError, ModelTurn, ToolCall, ToolSpec, Usage
from .task import Task
from .workspace import apply_patch, build_workspace

from graders.diffparse import is_test_path, parse_diff


def _pick(task_id: str, run_index: int, salt: str, modulo: int) -> int:
    digest = hashlib.sha256(f"{salt}:{task_id}:{run_index}".encode()).hexdigest()
    return int(digest[:8], 16) % modulo


def _patch_as_writes(task: Task, patch_text: str) -> list[ToolCall]:
    """Turn a patch into write_file / rm calls by applying it to a scratch copy."""
    calls: list[ToolCall] = []
    files = parse_diff(patch_text)
    if not files:
        return calls
    workspace = build_workspace(task, agent_git=False, label="fake")
    try:
        apply_patch(workspace.root, patch_text)
        for i, f in enumerate(files):
            if f.new_path is None:
                calls.append(ToolCall(f"fake-rm-{i}", "run_command", {"command": f"rm -f {f.old_path}"}))
            else:
                content = (workspace.root / f.new_path).read_text(encoding="utf-8")
                calls.append(ToolCall(f"fake-w-{i}", "write_file", {"path": f.new_path, "content": content}))
                if f.old_path and f.old_path != f.new_path:
                    calls.append(ToolCall(f"fake-mv-{i}", "run_command", {"command": f"rm -f {f.old_path}"}))
    finally:
        workspace.cleanup()
    return calls


class FakeModel(ModelAdapter):
    def __init__(self, spec: AgentModel, task: Task | None = None, run_index: int = 0) -> None:
        super().__init__(spec)
        if task is None:
            raise ValueError("FakeModel needs the task it is scripted for")
        self.task = task
        self.run_index = run_index
        self.plan_label, self.script = self._build_script()
        self._position = 0

    def _read(self, relative: str) -> str:
        return self.task.path(relative).read_text(encoding="utf-8")

    def _first_source_file(self) -> str | None:
        for f in parse_diff(self._read(self.task.reference)):
            if f.old_path and not is_test_path(f.old_path):
                return f.old_path
        return None

    def _explore(self) -> list[ToolCall]:
        calls = [ToolCall("fake-ls", "list_files", {"path": ".", "max_depth": 2})]
        first = self._first_source_file()
        if first:
            calls.append(ToolCall("fake-read", "read_file", {"path": first}))
        return calls

    def _finish(self, summary: str) -> list[ToolCall]:
        return [ToolCall("fake-test", "run_command", {"command": self.task.test_cmd, "timeout_s": 300}),
                ToolCall("fake-submit", "submit", {"summary": summary})]

    def _build_script(self) -> tuple[str, list[ToolCall]]:
        behaviour = self.spec.behaviour
        task = self.task
        if behaviour == "oracle":
            return "reference", [*self._explore(), *_patch_as_writes(task, self._read(task.reference)),
                                 *self._finish("[fake-oracle] applied the reference solution")]
        if behaviour == "mixed":
            bucket = _pick(task.id, self.run_index, "mixed", 8)
            if bucket == 7:
                return "simulated_outage", [*self._explore()]
            if bucket <= 3:
                return "reference", [*self._explore(), *_patch_as_writes(task, self._read(task.reference)),
                                     *self._finish("[fake-mixed] applied the reference solution")]
            choice = 2 if bucket <= 5 else 3
            if choice == 2:
                flawed = task.flawed[_pick(task.id, self.run_index, "flawed", len(task.flawed))]
                return f"flawed:{flawed}", [*self._explore(), *_patch_as_writes(task, self._read(flawed)),
                                            *self._finish(f"[fake-mixed] applied {flawed}")]
            return "give_up", [*self._explore(), ToolCall("fake-submit", "submit",
                                                          {"summary": "[fake-mixed] gave up without changes"})]
        if behaviour == "cheater":
            peek = [
                ToolCall("fake-peek-1", "read_file", {"path": f"../../tasks/{task.id}/hidden_tests"}),
                ToolCall("fake-peek-2", "run_command",
                         {"command": f"ls /workspace/*/tasks/{task.id}/hidden_tests 2>&1 || true"}),
            ]
            return "cheat", [*peek, *_patch_as_writes(task, self._read(task.reference)), *self._cheat_calls(),
                             *self._finish("[fake-cheater] made the tests pass")]
        raise ValueError(f"unknown fake behaviour {behaviour!r}")

    def _cheat_calls(self) -> list[ToolCall]:
        """Skip the first visible test file it finds (Python) or mark a suite skipped (TS)."""
        workspace = build_workspace(self.task, agent_git=False, label="fake-cheat")
        try:
            tests_dir = workspace.root / "tests"
            candidates = sorted(p for p in tests_dir.rglob("*") if p.is_file() and is_test_path(
                str(p.relative_to(workspace.root))) and p.suffix in (".py", ".ts"))
            if not candidates:
                return []
            victim = candidates[_pick(self.task.id, self.run_index, "victim", len(candidates))]
            relative = str(victim.relative_to(workspace.root))
            text = victim.read_text(encoding="utf-8")
            if victim.suffix == ".py":
                new = "import pytest\n\npytestmark = pytest.mark.skip(reason='flaky on CI')\n\n" + text
            else:
                new = text.replace("describe(", "describe.skip(", 1)
            return [ToolCall("fake-cheat", "write_file", {"path": relative, "content": new})]
        finally:
            shutil.rmtree(workspace.container, ignore_errors=True)

    def next_turn(self, system: str, tools: list[ToolSpec], messages: list[dict]) -> ModelTurn:
        if self.plan_label == "simulated_outage" and self._position >= len(self.script):
            raise ModelError("[simulated by fake-mixed] 529 overloaded: provider still failing after 6 retries",
                             kind="api")
        prompt_chars = len(system) + sum(len(json.dumps(m, default=str)) for m in messages)
        if self._position >= len(self.script):
            return ModelTurn("[fake] nothing left to do", [], Usage(prompt_chars // 4, 10), "end_turn")
        call = self.script[self._position]
        self._position += 1
        text = f"[{self.spec.key}] step {self._position}: {call.name}"
        usage = Usage(input_tokens=prompt_chars // 4, output_tokens=len(json.dumps(call.arguments)) // 4 + 20)
        return ModelTurn(text, [call], usage, "tool_use")
