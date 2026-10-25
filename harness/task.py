"""The task schema (task.yaml), validated with pydantic, and task discovery."""

from __future__ import annotations

import re
from functools import cached_property
from pathlib import Path
from typing import Any, Literal

import yaml
from pydantic import BaseModel, ConfigDict, Field, field_validator, model_validator

from .paths import CODEBASES, TASKS

Language = Literal["python", "typescript"]
Category = Literal["bug_fix", "pr_derived", "write_tests", "flaky_test", "ci_triage", "code_review"]
Difficulty = Literal["easy", "medium", "hard"]
NegativeCheckName = Literal[
    "no_hidden_test_access",
    "no_test_deletion",
    "no_skip_or_xfail",
    "no_hardcoded_expected_values",
    "no_network",
    "no_retry_or_sleep_masking",
]

CATEGORY_PREFIX = {
    "bug_fix": "bf",
    "pr_derived": "pr",
    "write_tests": "wt",
    "flaky_test": "fl",
    "ci_triage": "ci",
    "code_review": "cr",
}
CATEGORY_PRIMARY = {
    "bug_fix": "hidden_tests",
    "pr_derived": "hidden_tests",
    "ci_triage": "hidden_tests",
    "write_tests": "mutation",
    "flaky_test": "repeated_runs",
    "code_review": "review_findings",
}


class _Strict(BaseModel):
    model_config = ConfigDict(extra="forbid")


class Setup(_Strict):
    apply_patch: str | None = "bug.patch"
    remove_paths: list[str] = Field(default_factory=list)


class ReviewDefect(_Strict):
    """A defect seeded into a code-review diff, located by file and line range."""

    id: str
    file: str
    lines: tuple[int, int]
    summary: str

    @model_validator(mode="after")
    def _ordered(self) -> ReviewDefect:
        if self.lines[0] > self.lines[1] or self.lines[0] < 1:
            raise ValueError(f"defect {self.id}: bad line range {self.lines}")
        return self


class Primary(_Strict):
    type: Literal["hidden_tests", "mutation", "repeated_runs", "review_findings"]
    fail_to_pass: list[str] = Field(default_factory=list)
    pass_to_pass: list[str] = Field(default_factory=list)
    # write_tests
    min_mutant_kill_rate: float | None = None
    test_files: list[str] = Field(default_factory=list)
    # flaky_test
    runs: int | None = None
    # code_review
    defects: list[ReviewDefect] = Field(default_factory=list)
    max_false_positives: int | None = None
    line_tolerance: int = 3

    @model_validator(mode="after")
    def _per_type(self) -> Primary:
        if self.type == "hidden_tests" and not self.fail_to_pass:
            raise ValueError("hidden_tests needs at least one fail_to_pass test")
        if self.type == "mutation":
            if self.min_mutant_kill_rate is None or not (0 < self.min_mutant_kill_rate <= 1):
                raise ValueError("mutation needs min_mutant_kill_rate in (0, 1]")
            if not self.test_files:
                raise ValueError("mutation needs test_files (where the agent writes tests)")
        if self.type == "repeated_runs" and (self.runs is None or self.runs < 2):
            raise ValueError("repeated_runs needs runs >= 2")
        if self.type == "review_findings":
            if not self.defects:
                raise ValueError("review_findings needs at least one seeded defect")
            if self.max_false_positives is None:
                raise ValueError("review_findings needs max_false_positives")
        return self


class AutoCheck(_Strict):
    name: str
    params: dict[str, Any] = Field(default_factory=dict)


class RubricItem(_Strict):
    id: str
    criterion: str
    weight: float = Field(gt=0)
    grader: Literal["judge", "auto"]
    check: AutoCheck | None = None

    @model_validator(mode="after")
    def _auto_has_check(self) -> RubricItem:
        if self.grader == "auto" and self.check is None:
            raise ValueError(f"rubric item {self.id}: auto items need a check")
        if self.grader == "judge" and self.check is not None:
            raise ValueError(f"rubric item {self.id}: judge items take no check")
        return self


class Limits(_Strict):
    max_steps: int = Field(default=40, ge=1)
    timeout_s: int = Field(default=900, ge=30)


class Source(_Strict):
    """Where a PR-derived task comes from in target/history/<library>."""

    library: Literal["shopcore", "ledgerkit"]
    pr: int
    commit: str


class Task(_Strict):
    id: str
    title: str
    language: Language
    category: Category
    difficulty: Difficulty
    prompt: str
    setup: Setup = Field(default_factory=Setup)
    test_cmd: str
    primary: Primary
    rubric: list[RubricItem] = Field(min_length=2, max_length=4)
    negative_checks: list[NegativeCheckName]
    limits: Limits = Field(default_factory=Limits)
    reference: str = "reference.patch"
    flawed: list[str] = Field(min_length=2)
    mutants: list[str] = Field(default_factory=list)
    cheats: list[str] = Field(default_factory=list)
    env: dict[str, str] = Field(default_factory=dict)
    source: Source | None = None

    # Set by load_task, not part of the YAML.
    root: Path | None = Field(default=None, exclude=True)

    @field_validator("id")
    @classmethod
    def _id_format(cls, value: str) -> str:
        if not re.fullmatch(r"(bf|pr|wt|fl|ci|cr)_\d{3}_[a-z0-9_]+", value):
            raise ValueError(f"task id {value!r} must look like bf_001_short_name")
        return value

    @field_validator("prompt")
    @classmethod
    def _prompt_not_blank(cls, value: str) -> str:
        if len(value.strip()) < 40:
            raise ValueError("prompt is too short to be a real task description")
        return value

    @model_validator(mode="after")
    def _consistent(self) -> Task:
        prefix = CATEGORY_PREFIX[self.category]
        if not self.id.startswith(prefix + "_"):
            raise ValueError(f"{self.id}: category {self.category} tasks use the {prefix}_ prefix")
        expected = CATEGORY_PRIMARY[self.category]
        if self.primary.type != expected:
            raise ValueError(f"{self.id}: {self.category} tasks use primary type {expected}")
        if self.category == "write_tests" and len(self.mutants) < 3:
            raise ValueError(f"{self.id}: write_tests tasks need at least 3 mutants")
        if self.category != "write_tests" and self.mutants:
            raise ValueError(f"{self.id}: only write_tests tasks have mutants")
        if self.category == "pr_derived" and self.source is None:
            raise ValueError(f"{self.id}: pr_derived tasks must name their source commit")
        ids = [item.id for item in self.rubric]
        if len(ids) != len(set(ids)):
            raise ValueError(f"{self.id}: duplicate rubric item ids")
        if len(set(self.negative_checks)) != len(self.negative_checks):
            raise ValueError(f"{self.id}: duplicate negative checks")
        return self

    # -- convenience ------------------------------------------------------
    @property
    def codebase(self) -> str:
        return CODEBASES[self.language]

    @property
    def dir(self) -> Path:
        assert self.root is not None, "task was not loaded from disk"
        return self.root

    def path(self, relative: str) -> Path:
        return self.dir / relative

    @property
    def hidden_tests_dir(self) -> Path:
        return self.dir / "hidden_tests"

    @cached_property
    def rubric_weight(self) -> float:
        return sum(item.weight for item in self.rubric)


def load_task(task_dir: Path) -> Task:
    with open(task_dir / "task.yaml", encoding="utf-8") as handle:
        data = yaml.safe_load(handle)
    task = Task.model_validate(data)
    if task.id != task_dir.name:
        raise ValueError(f"task id {task.id!r} does not match its directory {task_dir.name!r}")
    task.root = task_dir.resolve()
    return task


def discover_tasks(root: Path = TASKS, selected: list[str] | None = None) -> list[Task]:
    """Load every task under ``root`` (sorted by id), optionally filtered by id or prefix."""
    tasks = []
    for task_dir in sorted(p for p in root.iterdir() if (p / "task.yaml").exists()) if root.exists() else []:
        if selected and not any(task_dir.name == s or task_dir.name.startswith(s) for s in selected):
            continue
        tasks.append(load_task(task_dir))
    return tasks
