"""Claude Code (`claude`) in headless print mode.

Invocation (stream-json gives one JSON event per line):

    claude -p <prompt> --model <id> --output-format stream-json --verbose \
           --max-turns <max_steps> --permission-mode bypassPermissions \
           --disallowedTools WebFetch WebSearch

Tool calls are mapped onto the shared tool names (Bash -> run_command,
Read -> read_file, Write/Edit -> write_file, Glob/Grep/LS -> list_files) so
the same negative checks and failure attribution apply. The final ``result``
event carries turns, token usage and the CLI's own cost figure.
"""

from __future__ import annotations

from harness.models import Usage
from harness.task import Task

from .base import NativeHarness, NativeResult, json_lines, quote

TOOL_MAP = {"Bash": "run_command", "Read": "read_file", "Write": "write_file", "Edit": "write_file",
            "MultiEdit": "write_file", "Glob": "list_files", "Grep": "list_files", "LS": "list_files"}


class ClaudeCodeHarness(NativeHarness):
    cli = "claude"
    key_env = "ANTHROPIC_API_KEY"

    def command(self, task: Task) -> str:
        return " ".join([
            quote(self.cli_path or self.cli), "-p", quote(self.prompt(task)), "--model", quote(self.model_id),
            "--output-format", "stream-json", "--verbose", "--max-turns", str(task.limits.max_steps),
            "--permission-mode", "bypassPermissions", "--disallowedTools", "WebFetch", "WebSearch",
        ])

    def parse(self, output: str, task: Task) -> NativeResult:
        trajectory: list[dict] = []
        steps = 0
        usage = Usage()
        cost = None
        stop = "no_result"
        error = None
        for event in json_lines(output):
            kind = event.get("type")
            if kind == "assistant":
                steps += 1
                for block in (event.get("message") or {}).get("content", []):
                    if block.get("type") == "tool_use":
                        args = block.get("input") or {}
                        name = TOOL_MAP.get(block.get("name"), block.get("name"))
                        mapped = {"command": args.get("command")} if name == "run_command" else {
                            "path": args.get("file_path") or args.get("path") or args.get("pattern") or ""}
                        trajectory.append({"type": "tool_call", "step": steps, "name": name,
                                           "native_tool": block.get("name"), "arguments": mapped,
                                           "path_escape": False})
                    elif block.get("type") == "text":
                        trajectory.append({"type": "model_turn", "step": steps, "text": block.get("text", "")[:1500]})
            elif kind == "result":
                u = event.get("usage") or {}
                usage = Usage(u.get("input_tokens", 0) or 0, u.get("output_tokens", 0) or 0,
                              u.get("cache_read_input_tokens", 0) or 0, u.get("cache_creation_input_tokens", 0) or 0)
                cost = event.get("total_cost_usd")
                steps = event.get("num_turns", steps) or steps
                subtype = event.get("subtype", "")
                stop = {"success": "submitted", "error_max_turns": "max_steps"}.get(subtype, subtype or "error")
                if event.get("is_error"):
                    error = str(event.get("result") or subtype)[:500]
        return NativeResult(stop, steps, usage, trajectory, 0.0, cost, error)
