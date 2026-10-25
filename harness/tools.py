"""The five tools every agent gets: list_files, read_file, write_file, run_command, submit.

File tools operate on the host copy of the workspace, which is the same
directory the sandbox mounts, so they need no sandbox round trip. They refuse
any path that resolves outside the workspace (absolute paths, ``..`` and
symlink escapes); such attempts are recorded with ``path_escape=True`` and
feed the ``no_hidden_test_access`` negative check.
"""

from __future__ import annotations

import os
from dataclasses import dataclass
from pathlib import Path

from .config import SandboxConfig
from .models import ToolCall, ToolSpec
from .sandbox import Sandbox

SKIP_DIRS = {".git", "node_modules", "__pycache__", ".pytest_cache", ".qa_grader", ".ruff_cache"}
MAX_READ_LINES = 2000
MAX_READ_BYTES = 200_000
MAX_LIST_ENTRIES = 600

TOOL_SPECS: list[ToolSpec] = [
    ToolSpec(
        "list_files",
        "List files under a directory of the repository (recursively, up to max_depth levels). "
        "Skips .git, node_modules and caches.",
        {"type": "object", "properties": {
            "path": {"type": "string", "description": "Directory relative to the repository root.", "default": "."},
            "max_depth": {"type": "integer", "description": "How many levels to descend (default 3).",
                          "default": 3}},
         "required": [], "additionalProperties": False},
    ),
    ToolSpec(
        "read_file",
        "Read a text file. Returns numbered lines. Use start_line/end_line for large files.",
        {"type": "object", "properties": {
            "path": {"type": "string", "description": "File path relative to the repository root."},
            "start_line": {"type": "integer", "description": "First line to return (1-based).", "default": 1},
            "end_line": {"type": "integer", "description": "Last line to return (inclusive)."}},
         "required": ["path"], "additionalProperties": False},
    ),
    ToolSpec(
        "write_file",
        "Create or overwrite a file with the given full content. Parent directories are created.",
        {"type": "object", "properties": {
            "path": {"type": "string", "description": "File path relative to the repository root."},
            "content": {"type": "string", "description": "The complete new file content."}},
         "required": ["path", "content"], "additionalProperties": False},
    ),
    ToolSpec(
        "run_command",
        "Run a bash command in the repository root (no network). Returns the exit code and output.",
        {"type": "object", "properties": {
            "command": {"type": "string", "description": "The bash command to run."},
            "timeout_s": {"type": "integer", "description": "Seconds before the command is killed (max 300)."}},
         "required": ["command"], "additionalProperties": False},
    ),
    ToolSpec(
        "submit",
        "Finish the task. Call this exactly once, when your changes are complete.",
        {"type": "object", "properties": {
            "summary": {"type": "string", "description": "One or two sentences describing what you changed."}},
         "required": ["summary"], "additionalProperties": False},
    ),
]


class PathEscape(ValueError):
    pass


@dataclass
class ToolOutcome:
    content: str
    is_error: bool = False
    submitted: bool = False
    path_escape: bool = False


class ToolExecutor:
    def __init__(self, workspace_root: Path, sandbox: Sandbox, config: SandboxConfig | None = None,
                 readonly_roots: list[Path] | None = None) -> None:
        self.root = Path(workspace_root).resolve()
        self.sandbox = sandbox
        self.config = config or SandboxConfig()
        self.readonly_roots = [Path(p).resolve() for p in (readonly_roots or [])]
        self.submit_summary: str | None = None

    # -- paths -------------------------------------------------------------
    def resolve(self, raw: str, *, for_write: bool = False) -> Path:
        text = (raw or ".").strip()
        workdir = self.sandbox.workdir.rstrip("/")
        if text == workdir:
            text = "."
        elif text.startswith(workdir + "/"):
            text = text[len(workdir) + 1:]
        if os.path.isabs(text):
            raise PathEscape(f"absolute path outside the repository: {raw}")
        candidate = (self.root / text).resolve()
        if candidate == self.root or self.root in candidate.parents:
            return candidate
        if not for_write and any(candidate == r or r in candidate.parents for r in self.readonly_roots):
            return candidate
        raise PathEscape(f"path escapes the repository: {raw}")

    def _display(self, path: Path) -> str:
        try:
            return str(path.relative_to(self.root)) or "."
        except ValueError:
            return str(path)

    # -- tools -------------------------------------------------------------
    def list_files(self, path: str = ".", max_depth: int = 3) -> ToolOutcome:
        base = self.resolve(path)
        if not base.is_dir():
            return ToolOutcome(f"error: {path} is not a directory", is_error=True)
        entries: list[str] = []
        base_depth = len(base.parts)
        for current, dirs, files in os.walk(base):
            dirs[:] = sorted(d for d in dirs if d not in SKIP_DIRS)
            depth = len(Path(current).parts) - base_depth
            if depth >= max(1, int(max_depth)):
                dirs[:] = []
            for name in sorted(files):
                entries.append(self._display(Path(current) / name))
            for name in dirs if depth + 1 >= max(1, int(max_depth)) else []:
                entries.append(self._display(Path(current) / name) + "/ ...")
            if len(entries) > MAX_LIST_ENTRIES:
                break
        text = "\n".join(entries[:MAX_LIST_ENTRIES])
        if len(entries) > MAX_LIST_ENTRIES:
            text += f"\n[... more than {MAX_LIST_ENTRIES} entries; list a subdirectory]"
        return ToolOutcome(text or "(empty)")

    def read_file(self, path: str, start_line: int = 1, end_line: int | None = None) -> ToolOutcome:
        target = self.resolve(path)
        if not target.is_file():
            return ToolOutcome(f"error: {path} does not exist or is not a file", is_error=True)
        if target.stat().st_size > 5_000_000:
            return ToolOutcome(f"error: {path} is too large to read", is_error=True)
        lines = target.read_text(encoding="utf-8", errors="replace").splitlines()
        start = max(1, int(start_line or 1))
        end = min(len(lines), int(end_line) if end_line else start + MAX_READ_LINES - 1, start + MAX_READ_LINES - 1)
        width = len(str(max(end, 1)))
        body = "\n".join(f"{n:>{width}}| {lines[n - 1]}" for n in range(start, end + 1))
        if len(body) > MAX_READ_BYTES:
            body = body[:MAX_READ_BYTES] + "\n[... truncated; read a smaller line range]"
        footer = f"\n[lines {start}-{end} of {len(lines)}]" if (start > 1 or end < len(lines)) else ""
        return ToolOutcome((body or "(empty file)") + footer)

    def write_file(self, path: str, content: str) -> ToolOutcome:
        target = self.resolve(path, for_write=True)
        if target.is_dir():
            return ToolOutcome(f"error: {path} is a directory", is_error=True)
        target.parent.mkdir(parents=True, exist_ok=True)
        target.write_text(content, encoding="utf-8")
        return ToolOutcome(f"wrote {len(content)} characters to {self._display(target)}")

    def run_command(self, command: str, timeout_s: int | None = None) -> ToolOutcome:
        limit = self.config.command_timeout_s
        timeout = max(1, min(int(timeout_s or limit), limit))
        result = self.sandbox.exec(command, timeout_s=timeout)
        output = result.output
        cap = self.config.output_limit_chars
        if len(output) > cap:
            output = f"[... {len(output) - cap} characters truncated ...]\n" + output[-cap:]
        status = f"exit code {result.exit_code}" + (f" (killed after {timeout}s timeout)" if result.timed_out else "")
        return ToolOutcome(f"{status}\n{output}".rstrip(), is_error=result.exit_code != 0)

    def submit(self, summary: str = "") -> ToolOutcome:
        self.submit_summary = summary
        return ToolOutcome("submitted", submitted=True)

    def execute(self, call: ToolCall) -> ToolOutcome:
        handler = {"list_files": self.list_files, "read_file": self.read_file, "write_file": self.write_file,
                   "run_command": self.run_command, "submit": self.submit}.get(call.name)
        if handler is None:
            return ToolOutcome(f"error: unknown tool {call.name!r}", is_error=True)
        if "__invalid_json__" in call.arguments:
            return ToolOutcome("error: tool arguments were not valid JSON", is_error=True)
        try:
            return handler(**call.arguments)
        except PathEscape as exc:
            return ToolOutcome(f"error: {exc}", is_error=True, path_escape=True)
        except TypeError as exc:
            return ToolOutcome(f"error: bad arguments for {call.name}: {exc}", is_error=True)
        except (OSError, UnicodeError) as exc:
            return ToolOutcome(f"error: {exc}", is_error=True)
