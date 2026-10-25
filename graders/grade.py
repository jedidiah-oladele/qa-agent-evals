"""Grade one submission end to end: primary grader, rubric, negative checks, score."""

from __future__ import annotations

from dataclasses import dataclass, field
from typing import Literal

from harness.config import Pricing, RunConfig, run_config
from harness.paths import TARGET
from harness.task import Task

from .auto_checks import AUTO_CHECKS
from .checks import CheckResult, read_sources, run_checks
from .context import GradeContext
from .rubric_judge import Judge, Verdict, cross_check_selected, judge_item
from .scoring import Score, rubric_score, task_score
from .tests_grader import PrimaryResult, grade_primary


@dataclass
class RubricResult:
    id: str
    grader: str
    weight: float
    verdict: str
    rationale: str
    judge_model: str | None = None
    cost_usd: float | None = 0.0
    tokens: int = 0
    cross_check: dict | None = None

    def to_dict(self) -> dict:
        return {
            "id": self.id,
            "grader": self.grader,
            "weight": self.weight,
            "verdict": self.verdict,
            "rationale": self.rationale,
            "judge_model": self.judge_model,
            "cost_usd": self.cost_usd,
            "tokens": self.tokens,
            "cross_check": self.cross_check,
        }


@dataclass
class JudgeSetup:
    primary: Judge
    primary_pricing: Pricing | None = None
    cross: Judge | None = None
    cross_pricing: Pricing | None = None
    cross_rate: float = 0.0
    seed: int = 0


@dataclass
class GradeResult:
    primary: PrimaryResult
    rubric: list[RubricResult]
    checks: list[CheckResult]
    score: Score
    artifacts: dict[str, str] = field(default_factory=dict)

    @property
    def judge_cost_usd(self) -> float | None:
        costs = [r.cost_usd for r in self.rubric if r.grader == "judge"]
        costs += [r.cross_check.get("cost_usd") for r in self.rubric if r.cross_check]
        if any(c is None for c in costs):
            return None
        return round(sum(costs), 6)

    def to_dict(self) -> dict:
        return {
            "primary_pass": self.score.primary_pass,
            "primary": self.primary.to_dict(),
            "rubric": [r.to_dict() for r in self.rubric],
            "rubric_score": self.score.rubric_score,
            "negative_checks": [c.to_dict() for c in self.checks],
            "penalty": self.score.penalty,
            "task_score": self.score.task_score,
        }


def visible_test_sources(task: Task) -> list[str]:
    tests = TARGET / task.codebase / "tests"
    return read_sources(sorted(p for p in tests.rglob("*") if p.suffix in (".py", ".ts")))


def grade_rubric(ctx: GradeContext, judges: JudgeSetup | None, *, key: tuple = ()) -> list[RubricResult]:
    results = []
    for item in ctx.task.rubric:
        if item.grader == "auto":
            check = AUTO_CHECKS.get(item.check.name)
            if check is None:
                results.append(RubricResult(item.id, "auto", item.weight, "error", f"unknown check {item.check.name}"))
                continue
            try:
                ok, why = check(ctx, **item.check.params)
                results.append(RubricResult(item.id, "auto", item.weight, "pass" if ok else "fail", why, "auto"))
            except Exception as exc:  # recorded as a grader error, never crashes a run
                results.append(RubricResult(item.id, "auto", item.weight, "error", f"{type(exc).__name__}: {exc}"))
            continue
        if judges is None:
            results.append(RubricResult(item.id, "judge", item.weight, "skipped", "judge not run"))
            continue
        verdict: Verdict = judge_item(judges.primary, judges.primary_pricing, ctx.task, item, ctx.diff, ctx.artifacts)
        result = RubricResult(
            item.id,
            "judge",
            item.weight,
            verdict.verdict,
            verdict.rationale,
            verdict.model,
            verdict.cost_usd,
            verdict.usage.total,
        )
        if judges.cross is not None and cross_check_selected(judges.seed, judges.cross_rate, *key, item.id):
            second = judge_item(judges.cross, judges.cross_pricing, ctx.task, item, ctx.diff, ctx.artifacts)
            result.cross_check = second.to_dict()
        results.append(result)
    return results


def grade_submission(
    task: Task,
    diff: str,
    trajectory: list[dict] | None = None,
    *,
    backend: Literal["docker", "local"] = "local",
    judges: JudgeSetup | None = None,
    artifacts: dict[str, str] | None = None,
    config: RunConfig | None = None,
    key: tuple = (),
) -> GradeResult:
    ctx = GradeContext(task, diff, trajectory or [], backend, config or run_config(), artifacts or {})
    primary = grade_primary(ctx)
    rubric = grade_rubric(ctx, judges, key=key)
    checks = run_checks(task, diff, trajectory or [], visible_test_sources=visible_test_sources(task))
    score = task_score(
        primary.passed, rubric_score([(r.weight, r.verdict) for r in rubric]), sum(1 for c in checks if not c.passed)
    )
    return GradeResult(primary, rubric, checks, score, ctx.artifacts)
