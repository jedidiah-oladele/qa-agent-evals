"""Shared state for grading one submission (a final diff plus its trajectory)."""

from __future__ import annotations

from collections.abc import Iterator
from contextlib import contextmanager
from dataclasses import dataclass, field
from typing import Literal

from harness.config import RunConfig, run_config
from harness.sandbox import Sandbox, create_sandbox, node_modules_for
from harness.task import Task
from harness.workspace import PatchError, Workspace, apply_patch, build_workspace, copy_hidden_tests

from .diffparse import filter_diff, is_test_path

ARTIFACTS = ("TRIAGE.md", "REVIEW.md")


@dataclass
class GradeContext:
    task: Task
    diff: str
    trajectory: list[dict] = field(default_factory=list)
    backend: Literal["docker", "local"] = "local"
    config: RunConfig = field(default_factory=run_config)
    artifacts: dict[str, str] = field(default_factory=dict)
    notes: list[str] = field(default_factory=list)

    def __post_init__(self) -> None:
        if not self.artifacts:
            self.artifacts = artifacts_from_diff(self.diff)

    @contextmanager
    def environment(self, *, diff: str | None = None, hidden: bool = False, apply_bug: bool = True,
                    extra_env: dict[str, str] | None = None) -> Iterator[tuple[Workspace, Sandbox]]:
        """A fresh grading workspace + sandbox. ``diff`` defaults to the submission."""
        workspace = build_workspace(self.task, node_modules=node_modules_for(self.backend), agent_git=False,
                                    apply_bug=apply_bug, label="grade")
        try:
            patch = self.diff if diff is None else diff
            apply_patch(workspace.root, patch)
            if hidden:
                copy_hidden_tests(self.task, workspace.root)
            sandbox = create_sandbox(workspace.root, self.backend, config=self.config.sandbox,
                                     env={**self.task.env, **(extra_env or {})})
            try:
                yield workspace, sandbox
            finally:
                sandbox.close()
        finally:
            workspace.cleanup()

    def test_only_diff(self) -> str:
        return filter_diff(self.diff, is_test_path)


def artifacts_from_diff(diff: str) -> dict[str, str]:
    """Recover the full text of TRIAGE.md / REVIEW.md when the diff adds them."""
    from .diffparse import parse_diff

    found = {}
    for f in parse_diff(diff):
        if f.path in ARTIFACTS and f.new_path is not None and f.status == "added":
            found[f.path] = "\n".join(text for _, text in f.added) + "\n"
    return found


__all__ = ["GradeContext", "PatchError", "artifacts_from_diff"]
