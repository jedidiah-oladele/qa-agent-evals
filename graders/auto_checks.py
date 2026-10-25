"""Deterministic rubric items (``grader: auto``).

Each check takes the grading context and the item's ``params`` and returns
``(passed, rationale)``. Rationales are specific enough to audit by hand.
"""

from __future__ import annotations

import fnmatch
import re
from collections.abc import Callable

from .context import GradeContext
from .diffparse import filter_diff, is_test_path, parse_diff
from .review import match_review, parse_findings
from .runners import run_tests

AutoResult = tuple[bool, str]


def _content_lines(text: str) -> list[str]:
    lines = []
    for line in text.splitlines():
        stripped = line.strip()
        if stripped and not stripped.startswith("#") and not re.fullmatch(r"[-=*_`]{3,}", stripped):
            lines.append(stripped)
    return lines


def doc_lines(ctx: GradeContext, file: str, min_lines: int, max_lines: int) -> AutoResult:
    """A written artifact exists with between min and max lines of content (headings excluded)."""
    text = ctx.artifacts.get(file)
    if text is None:
        return False, f"{file} was not created"
    count = len(_content_lines(text))
    ok = min_lines <= count <= max_lines
    return ok, f"{file} has {count} content line(s); required {min_lines}-{max_lines}"


def regression_test(ctx: GradeContext, paths: list[str] | None = None) -> AutoResult:
    """The diff adds or changes tests, and at least one of them fails on the starting code.

    Runs only the agent's changed test files against the starting state (bug
    intact, source changes discarded), so passing means the new tests really
    detect the reported problem.
    """
    changed = [
        f.path
        for f in parse_diff(ctx.diff)
        if f.new_path
        and is_test_path(f.path)
        and f.path.endswith((".py", ".ts"))
        and (not paths or any(fnmatch.fnmatch(f.path, p) for p in paths))
    ]
    if not changed:
        return False, "the diff adds or changes no test files"
    with ctx.environment(diff=ctx.test_only_diff()) as (_, sandbox):
        report = run_tests(sandbox, ctx.task.language, paths=changed, timeout_s=300)
    if report.failing or report.collection_errors:
        failing = report.failing[:3] or sorted(report.collection_errors)[:3]
        return True, f"on the starting code, changed tests fail as they should: {failing}"
    return False, f"changed tests {changed} all pass on the unfixed starting code, so they do not catch the bug"


def diff_scope(ctx: GradeContext, allowed: list[str], allow_tests: bool = True) -> AutoResult:
    """Every changed non-test file matches one of the allowed globs."""
    outside = []
    for f in parse_diff(ctx.diff):
        if allow_tests and is_test_path(f.path):
            continue
        if f.path in ("TRIAGE.md", "REVIEW.md"):
            continue
        if not any(fnmatch.fnmatch(f.path, glob) for glob in allowed):
            outside.append(f.path)
    if outside:
        return False, f"changes files outside {allowed}: {outside}"
    return True, f"all source changes are within {allowed}"


def touches(ctx: GradeContext, required: list[str]) -> AutoResult:
    changed = {f.path for f in parse_diff(ctx.diff)}
    missing = [p for p in required if not any(fnmatch.fnmatch(c, p) for c in changed)]
    if missing:
        return False, f"does not change {missing}"
    return True, f"changes {required}"


def tests_only(ctx: GradeContext) -> AutoResult:
    """write_tests tasks: the library source is left alone."""
    source = [f.path for f in parse_diff(ctx.diff) if not is_test_path(f.path)]
    if source:
        return False, f"modifies non-test files: {source}"
    return True, "only test files changed"


def min_tests(ctx: GradeContext, file: str, count: int) -> AutoResult:
    tests_diff = filter_diff(ctx.diff, lambda p: p == file)
    pattern = re.compile(r"^\s*(?:async\s+)?def\s+test_\w+|^\s*(?:it|test)(?:\.each\(.*\))?\s*\(")
    found = sum(1 for f in parse_diff(tests_diff) for _, line in f.added if pattern.match(line))
    return found >= count, f"{file} defines {found} test(s); expected at least {count}"


def review_false_positives(ctx: GradeContext, max: int) -> AutoResult:  # noqa: A002 - mirrors the YAML key
    review = ctx.artifacts.get("REVIEW.md")
    if review is None:
        return False, "REVIEW.md was not written"
    primary = ctx.task.primary
    result = match_review(review, primary.defects, primary.line_tolerance)
    ok = len(result.false_positives) <= max
    return ok, f"{len(result.false_positives)} finding(s) match no seeded defect (allowed {max})"


def review_format(ctx: GradeContext) -> AutoResult:
    review = ctx.artifacts.get("REVIEW.md")
    if review is None:
        return False, "REVIEW.md was not written"
    findings = parse_findings(review)
    if not findings:
        return False, "REVIEW.md has no findings in the required `- path:line - explanation` format"
    return True, f"{len(findings)} finding(s) in the required format"


AUTO_CHECKS: dict[str, Callable[..., AutoResult]] = {
    "doc_lines": doc_lines,
    "regression_test": regression_test,
    "diff_scope": diff_scope,
    "touches": touches,
    "tests_only": tests_only,
    "min_tests": min_tests,
    "review_false_positives": review_false_positives,
    "review_format": review_format,
}
