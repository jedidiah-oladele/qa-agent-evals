"""The one tool-use loop every model runs through.

Same system prompt, same tools, same step and time limits for every model; the
only per-model code is the adapter that talks to the provider. A *step* is one
model turn (which may contain several tool calls).
"""

from __future__ import annotations

import time
from collections.abc import Callable
from dataclasses import dataclass, field

from .models import ModelError, ModelTurn, ToolCall, ToolSpec, Usage
from .task import Task
from .tools import TOOL_SPECS, ToolExecutor

SYSTEM_PROMPT = """You are a software engineer working on a task in a sandboxed copy of a code repository.

Tools: list_files, read_file, write_file, run_command and submit. Relative paths
are resolved from the repository root, which is also the working directory of
run_command. There is no network access, and nothing outside the repository is
available. The repository is a git checkout with a single commit, so `git diff`
shows your changes.

The project's test command is: {test_cmd}

Work the way a careful engineer would: read the relevant code, reproduce the
problem when there is one, make focused changes, and run the tests. Your work is
checked by automated tests and reviewers. When you are done, call submit exactly
once with a short summary. You have at most {max_steps} turns."""

NUDGE = "Continue working with the tools. When your changes are complete, call the submit tool."


@dataclass
class Episode:
    stop_reason: str  # submitted | max_steps | timeout | no_tool_calls | refusal | model_error
    steps: int
    usage: Usage
    trajectory: list[dict]
    wall_time_s: float
    error: str | None = None
    error_kind: str | None = None
    submit_summary: str | None = None
    tool_calls: int = 0
    transcript: list[dict] = field(default_factory=list, repr=False)


def system_prompt(task: Task) -> str:
    return SYSTEM_PROMPT.format(test_cmd=task.test_cmd, max_steps=task.limits.max_steps)


def _preview(text: str, limit: int = 400) -> str:
    return text if len(text) <= limit else text[:limit] + f"... [{len(text) - limit} more chars]"


def run_episode(task: Task, adapter, executor: ToolExecutor, *, tools: list[ToolSpec] | None = None,
                clock: Callable[[], float] = time.monotonic) -> Episode:
    tools = tools or TOOL_SPECS
    system = system_prompt(task)
    messages: list[dict] = [{"role": "user", "content": task.prompt.strip()}]
    trajectory: list[dict] = []
    usage = Usage()
    start = clock()
    nudged = False
    stop_reason = "max_steps"
    error = error_kind = None
    steps = 0
    calls_made = 0

    for step in range(1, task.limits.max_steps + 1):
        if clock() - start > task.limits.timeout_s:
            stop_reason = "timeout"
            break
        steps = step
        try:
            turn: ModelTurn = adapter.next_turn(system, tools, messages)
        except ModelError as exc:
            stop_reason, error, error_kind = "model_error", str(exc)[:500], exc.kind
            trajectory.append({"type": "model_error", "step": step, "kind": exc.kind, "error": str(exc)[:500]})
            break
        usage = usage + turn.usage
        trajectory.append({"type": "model_turn", "step": step, "text": _preview(turn.text, 1500),
                           "stop_reason": turn.stop_reason, "usage": turn.usage.to_dict(),
                           "tool_calls": len(turn.tool_calls), **({"extra": turn.extra} if turn.extra else {})})
        messages.append({"role": "assistant", "text": turn.text, "tool_calls": turn.tool_calls,
                         "payload": turn.payload})
        if turn.stop_reason == "refusal":
            stop_reason = "refusal"
            break
        if not turn.tool_calls:
            if nudged:
                stop_reason = "no_tool_calls"
                break
            nudged = True
            messages.append({"role": "user", "content": NUDGE})
            continue
        results = []
        submitted = False
        for call in turn.tool_calls:
            outcome = executor.execute(call)
            calls_made += 1
            trajectory.append({"type": "tool_call", "step": step, "name": call.name,
                               "arguments": _truncate_args(call), "is_error": outcome.is_error,
                               "path_escape": outcome.path_escape, "output": _preview(outcome.content)})
            results.append({"id": call.id, "name": call.name, "content": outcome.content,
                            "is_error": outcome.is_error})
            submitted = submitted or outcome.submitted
        messages.append({"role": "tool_results", "results": results})
        if submitted:
            stop_reason = "submitted"
            break
        if clock() - start > task.limits.timeout_s:
            stop_reason = "timeout"
            break

    return Episode(stop_reason=stop_reason, steps=steps, usage=usage, trajectory=trajectory,
                   wall_time_s=round(clock() - start, 2), error=error, error_kind=error_kind,
                   submit_summary=executor.submit_summary, tool_calls=calls_made, transcript=messages)


def _truncate_args(call: ToolCall) -> dict:
    out = {}
    for key, value in call.arguments.items():
        text = value if isinstance(value, str) else repr(value)
        out[key] = text if len(text) <= 2000 or key == "command" else text[:2000] + f"... [{len(text)} chars]"
    return out
