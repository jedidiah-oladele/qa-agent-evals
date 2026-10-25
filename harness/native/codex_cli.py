"""OpenAI Codex CLI (`codex`) in non-interactive exec mode.

Invocation (``--json`` prints one JSON event per line):

    codex exec --json --model <id> --skip-git-repo-check --full-auto <prompt>

Command and file-change items are mapped onto the shared tool names, and
``turn.completed`` usage events are summed. The event schema is parsed
defensively: unknown events are ignored rather than failing the run.
"""

from __future__ import annotations

from harness.models import Usage
from harness.task import Task

from .base import NativeHarness, NativeResult, json_lines, quote


class CodexHarness(NativeHarness):
    cli = "codex"
    key_env = "OPENAI_API_KEY"

    def command(self, task: Task) -> str:
        return " ".join([quote(self.cli_path or self.cli), "exec", "--json", "--model", quote(self.model_id),
                         "--skip-git-repo-check", "--full-auto", quote(self.prompt(task))])

    def parse(self, output: str, task: Task) -> NativeResult:
        trajectory: list[dict] = []
        usage = Usage()
        turns = 0
        error = None
        stop = "no_result"
        for event in json_lines(output):
            kind = event.get("type", "")
            item = event.get("item") or {}
            if kind == "turn.completed":
                turns += 1
                u = event.get("usage") or {}
                cached = u.get("cached_input_tokens", 0) or 0
                usage = usage + Usage((u.get("input_tokens", 0) or 0) - cached, u.get("output_tokens", 0) or 0, cached)
                stop = "submitted"
            elif kind in ("turn.failed", "error"):
                error = str(event.get("error") or event.get("message") or kind)[:500]
                stop = "error"
            elif kind == "item.completed" and item.get("type") == "command_execution":
                trajectory.append({"type": "tool_call", "step": turns + 1, "name": "run_command",
                                   "arguments": {"command": item.get("command", "")}, "path_escape": False})
            elif kind == "item.completed" and item.get("type") == "file_change":
                for change in item.get("changes", []) or [{}]:
                    trajectory.append({"type": "tool_call", "step": turns + 1, "name": "write_file",
                                       "arguments": {"path": change.get("path", "")}, "path_escape": False})
            elif kind == "item.completed" and item.get("type") == "agent_message":
                trajectory.append({"type": "model_turn", "step": turns + 1, "text": str(item.get("text", ""))[:1500]})
        steps = max(turns, sum(1 for t in trajectory if t["type"] == "tool_call"))
        return NativeResult(stop, steps, usage, trajectory, 0.0, None, error)
