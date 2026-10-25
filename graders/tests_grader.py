"""Primary (deterministic) graders.

* ``hidden_tests``  - fail_to_pass and pass_to_pass tests, with hidden tests added.
* ``mutation``      - the agent's tests pass on clean code and kill enough hidden mutants.
* ``repeated_runs`` - the whole suite (plus hidden tests) passes N times with
                      shuffled order, varying random seeds, hash seeds and time zones.
* ``review_findings`` - every seeded defect is located in REVIEW.md, with a
                      bounded number of findings that match no seeded defect.

A grader never raises for a bad submission: it returns ``passed=False`` with
details. ``environment_error`` is set only when the infrastructure failed.
"""

from __future__ import annotations

import fnmatch
import time
from dataclasses import dataclass, field

from harness.sandbox import SandboxError
from harness.workspace import PatchError, apply_patch

from .context import GradeContext
from .review import match_review
from .runners import TestReport, run_tests


@dataclass
class PrimaryResult:
    passed: bool
    type: str
    details: dict = field(default_factory=dict)
    environment_error: str | None = None
    grader_error: str | None = None
    duration_s: float = 0.0

    def to_dict(self) -> dict:
        return {"passed": self.passed, "type": self.type, "details": self.details,
                "environment_error": self.environment_error, "grader_error": self.grader_error,
                "duration_s": round(self.duration_s, 2)}


def expand(patterns: list[str], test_ids: list[str]) -> tuple[list[str], list[str]]:
    """Resolve pass_to_pass entries: exact ids, path prefixes ending in '/', or globs.

    Returns (resolved ids, patterns that matched nothing).
    """
    resolved: list[str] = []
    empty: list[str] = []
    for pattern in patterns:
        if pattern.endswith("/") or "*" in pattern or "?" in pattern:
            hits = [t for t in test_ids if t.startswith(pattern) or fnmatch.fnmatchcase(t, pattern)]
        else:
            hits = [pattern] if pattern in test_ids else []
            if not hits and "::" not in pattern and " > " not in pattern:
                hits = [t for t in test_ids if t.split("::")[0].split(" > ")[0] == pattern]
        if hits:
            resolved.extend(hits)
        else:
            empty.append(pattern)
    return list(dict.fromkeys(resolved)), empty


def evaluate_hidden(report: TestReport, fail_to_pass: list[str], pass_to_pass: list[str]) -> tuple[bool, dict]:
    ids = list(report.outcomes)
    f2p = {t: report.outcomes.get(t, "missing") for t in fail_to_pass}
    p2p_ids, p2p_unmatched = expand(pass_to_pass, ids)
    p2p_ids = [t for t in p2p_ids if t not in f2p]
    p2p_failures = {t: report.outcomes[t] for t in p2p_ids if not report.passed(t)}
    passed = (all(o == "passed" for o in f2p.values()) and not p2p_failures and not p2p_unmatched
              and not report.timed_out and report.runner_error is None and not report.collection_errors)
    details = {
        "fail_to_pass": f2p,
        "pass_to_pass": {"checked": len(p2p_ids), "failures": p2p_failures, "unmatched": p2p_unmatched},
        "suite": report.summary(),
    }
    if not passed:
        details["output_tail"] = report.output_tail[-2500:]
    return passed, details


def grade_hidden_tests(ctx: GradeContext) -> PrimaryResult:
    primary = ctx.task.primary
    with ctx.environment(hidden=True) as (_, sandbox):
        report = run_tests(sandbox, ctx.task.language, timeout_s=ctx.task.limits.timeout_s)
    passed, details = evaluate_hidden(report, primary.fail_to_pass, primary.pass_to_pass)
    return PrimaryResult(passed, "hidden_tests", details)


def grade_mutation(ctx: GradeContext) -> PrimaryResult:
    task, primary = ctx.task, ctx.task.primary
    # Only the agent's test changes count; source edits are discarded so the
    # tests are always judged against the clean library and the real mutants.
    tests_diff = ctx.test_only_diff()
    details: dict = {"test_files": primary.test_files, "mutants": {}}
    with ctx.environment(diff=tests_diff) as (workspace, sandbox):
        present = [p for p in primary.test_files if (workspace.root / p).is_file()]
        if not present:
            details["reason"] = f"none of {primary.test_files} exist"
            return PrimaryResult(False, "mutation", details)
        clean = run_tests(sandbox, task.language, paths=present, timeout_s=300)
        details["clean_run"] = clean.summary()
        details["tests_collected"] = len(clean.outcomes)
        if not clean.all_green:
            details["reason"] = "the tests do not pass on the clean code"
            details["output_tail"] = clean.output_tail[-2500:]
            return PrimaryResult(False, "mutation", details)
        killed = 0
        for mutant in task.mutants:
            patch = task.path(mutant).read_text(encoding="utf-8")
            try:
                apply_patch(workspace.root, patch)
            except PatchError as exc:
                return PrimaryResult(False, "mutation", details, grader_error=f"mutant {mutant} did not apply: {exc}")
            try:
                report = run_tests(sandbox, task.language, paths=present, timeout_s=120)
            finally:
                apply_patch(workspace.root, patch, reverse=True)
            is_killed = not report.all_green
            killed += is_killed
            details["mutants"][mutant] = {"killed": is_killed, "failing": report.failing[:5],
                                          "timed_out": report.timed_out}
    rate = killed / len(task.mutants)
    details["kill_rate"] = round(rate, 3)
    details["required"] = primary.min_mutant_kill_rate
    return PrimaryResult(rate >= (primary.min_mutant_kill_rate or 1.0), "mutation", details)


def grade_repeated_runs(ctx: GradeContext) -> PrimaryResult:
    task, primary = ctx.task, ctx.task.primary
    zones = ctx.config.grading.repeated_runs_timezones
    runs = []
    with ctx.environment(hidden=True) as (_, sandbox):
        for i in range(primary.runs or 0):
            seed = 1000 + i
            env = {"TZ": zones[i % len(zones)], "PYTHONHASHSEED": str(i + 1)}
            report = run_tests(sandbox, task.language, shuffle_seed=seed, env=env, timeout_s=300)
            runs.append({"run": i, "seed": seed, "tz": env["TZ"], "green": report.all_green,
                         "failing": report.failing[:5], "collection_errors": sorted(report.collection_errors)[:3],
                         "tests": len(report.outcomes)})
    failed = [r for r in runs if not r["green"]]
    details = {"runs": len(runs), "failed_runs": len(failed), "failures": failed[:8]}
    return PrimaryResult(bool(runs) and not failed, "repeated_runs", details)


def grade_review_findings(ctx: GradeContext) -> PrimaryResult:
    primary = ctx.task.primary
    review = ctx.artifacts.get("REVIEW.md")
    if review is None:
        return PrimaryResult(False, "review_findings", {"reason": "REVIEW.md was not written"})
    result = match_review(review, primary.defects, primary.line_tolerance)
    details = result.to_dict()
    details["max_false_positives"] = primary.max_false_positives
    passed = not result.missed and len(result.false_positives) <= (primary.max_false_positives or 0)
    return PrimaryResult(passed, "review_findings", details)


GRADERS = {
    "hidden_tests": grade_hidden_tests,
    "mutation": grade_mutation,
    "repeated_runs": grade_repeated_runs,
    "review_findings": grade_review_findings,
}


def grade_primary(ctx: GradeContext) -> PrimaryResult:
    start = time.monotonic()
    grader = GRADERS[ctx.task.primary.type]
    try:
        result = grader(ctx)
    except PatchError as exc:
        result = PrimaryResult(False, ctx.task.primary.type, {"reason": "submission diff did not apply"},
                               grader_error=str(exc))
    except SandboxError as exc:
        result = PrimaryResult(False, ctx.task.primary.type, {}, environment_error=str(exc))
    result.duration_s = time.monotonic() - start
    return result
