"""Shared plumbing for running vendor coding-agent CLIs headless in the sandbox.

A native harness gets the same task prompt, the same starting workspace and
the same graders as the shared loop; only the agent loop and tools are the
vendor's own. The CLI needs to reach its vendor's API, so these sandboxes are
started with network access (``network=True``) - the one difference from
shared-loop runs, recorded in every result. Hidden tests are still never
mounted, and grading still happens in a separate, network-less sandbox.

If the CLI is not installed (on the host for the local backend, in the image
for Docker), the run is recorded with ``status: skipped`` and a reason; it is
never silently dropped and never counted in pass rates.
"""

from __future__ import annotations

import json
import shlex
import shutil
from dataclasses import dataclass, field

from harness.agent_loop import system_prompt
from harness.models import Usage
from harness.sandbox import Sandbox
from harness.task import Task


@dataclass
class NativeResult:
    stop_reason: str
    steps: int
    usage: Usage
    trajectory: list[dict]
    wall_time_s: float
    cost_usd: float | None = None
    error: str | None = None
    raw_tail: str = ""
    extra: dict = field(default_factory=dict)


class NativeHarness:
    cli = ""
    key_env = ""

    def __init__(self, model_id: str, cli_path: str | None = None) -> None:
        self.model_id = model_id
        self.cli_path = cli_path or shutil.which(self.cli)

    def available(self) -> bool:
        return self.cli_path is not None

    def skip_reason(self) -> str:
        return f"`{self.cli}` CLI not found on PATH"

    def prompt(self, task: Task) -> str:
        return f"{system_prompt(task)}\n\n---\n\n{task.prompt.strip()}"

    def command(self, task: Task) -> str:
        raise NotImplementedError

    def parse(self, output: str, task: Task) -> NativeResult:
        raise NotImplementedError

    def run(self, task: Task, sandbox: Sandbox, api_key: str) -> NativeResult:
        result = sandbox.exec(self.command(task), timeout_s=task.limits.timeout_s,
                              env={self.key_env: api_key, "HOME": "/tmp" if sandbox.workdir == "/work" else
                                   str(sandbox.workspace_root.parent / "home")})
        parsed = self.parse(result.stdout, task)
        parsed.wall_time_s = result.duration_s
        if result.timed_out:
            parsed.stop_reason = "timeout"
        if result.exit_code not in (0, None) and parsed.error is None and parsed.stop_reason != "timeout":
            parsed.error = f"{self.cli} exited with {result.exit_code}: {result.stderr[-500:]}"
        parsed.raw_tail = (result.stdout + result.stderr)[-2000:]
        return parsed


def json_lines(output: str):
    for line in output.splitlines():
        line = line.strip()
        if not line.startswith("{"):
            continue
        try:
            yield json.loads(line)
        except json.JSONDecodeError:
            continue


def quote(text: str) -> str:
    return shlex.quote(text)
