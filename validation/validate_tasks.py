"""Prove every task's graders before any model is run.

For each task this checks, and records evidence for:

1. Schema: task.yaml validates; every referenced file exists; the prompt does
   not leak hidden test names or files.
2. Baseline: the untouched starting state FAILS the primary grader. For
   hidden-test tasks, every fail_to_pass test fails and every pass_to_pass
   test passes at the start (so the tests measure the change, not noise).
3. Reference: reference.patch PASSES the primary grader (primary_pass = 1),
   triggers no negative check, and passes every auto rubric item.
4. Flawed: every flawed/*.patch FAILS the primary grader (primary_pass = 0).
5. Planted cheats: the negative checks catch
   - deleting a visible test file and deleting a single test (no_test_deletion),
   - adding a skip marker to a visible test (no_skip_or_xfail),
   - reading hidden tests / escaping the workspace (no_hidden_test_access),
   - a network command (no_network),
   - each task-specific cheats/*.patch (e.g. hard-coded expected values,
     sleeps or retries in flaky-test tasks).
6. Provenance (pr_derived): starting state + reference.patch reproduces the
   named commit in target/history exactly (source and tests), and the commit's
   own tests are among the hidden tests, byte for byte.

    uv run python -m validation.validate_tasks                 # all tasks
    uv run python -m validation.validate_tasks bf_001 wt_      # by id or prefix
"""

from __future__ import annotations

import argparse
import json
import sys
import time
from concurrent.futures import ProcessPoolExecutor, as_completed
from dataclasses import dataclass, field
from pathlib import Path

from graders.checks import CheckContext, CHECKS
from graders.diffparse import is_test_path, parse_diff
from graders.grade import grade_submission, visible_test_sources
from graders.checks import read_sources
from harness.paths import REPO, TARGET, TASKS
from harness.sandbox import resolve_backend
from harness.task import Task, discover_tasks, load_task
from harness.workspace import build_workspace, apply_patch, hidden_test_paths

REPORT_MD = REPO / "validation" / "REPORT.md"
REPORT_JSON = REPO / "validation" / "report.json"


@dataclass
class TaskReport:
    task_id: str
    category: str = ""
    language: str = ""
    difficulty: str = ""
    ok: bool = True
    errors: list[str] = field(default_factory=list)
    baseline_primary: int | None = None
    reference_primary: int | None = None
    flawed_primary: dict[str, int] = field(default_factory=dict)
    cheats_caught: dict[str, list[str]] = field(default_factory=dict)
    notes: list[str] = field(default_factory=list)
    seconds: float = 0.0

    def fail(self, message: str) -> None:
        self.ok = False
        self.errors.append(message)


# ------------------------------------------------------------ helpers ----

def _visible_tests(task: Task) -> list[str]:
    """Test files present in the starting state (paths relative to the library root)."""
    workspace = build_workspace(task, agent_git=False, label="val-visible")
    try:
        return sorted(str(p.relative_to(workspace.root)) for p in workspace.root.rglob("*")
                      if p.is_file() and p.suffix in (".py", ".ts") and is_test_path(str(p.relative_to(workspace.root)))
                      and "helpers" not in p.parts and p.name != "conftest.py")
    finally:
        workspace.cleanup()


def _start_file(task: Task, relative: str) -> str:
    workspace = build_workspace(task, agent_git=False, label="val-read")
    try:
        return (workspace.root / relative).read_text(encoding="utf-8")
    finally:
        workspace.cleanup()


def _diff_for_edit(relative: str, old: str, new: str) -> str:
    """A git-style diff replacing the whole file (good enough for the checks)."""
    import difflib

    lines = difflib.unified_diff(old.splitlines(keepends=True), new.splitlines(keepends=True),
                                 f"a/{relative}", f"b/{relative}")
    return f"diff --git a/{relative} b/{relative}\n" + "".join(lines)


def _deletion_diff(relative: str, old: str) -> str:
    body = "".join("-" + line for line in old.splitlines(keepends=True))
    count = len(old.splitlines())
    return (f"diff --git a/{relative} b/{relative}\ndeleted file mode 100644\n--- a/{relative}\n+++ /dev/null\n"
            f"@@ -1,{count} +0,0 @@\n{body}")


def _run_check(task: Task, name: str, diff: str, trajectory: list[dict]) -> bool:
    """True when the named check flags the submission."""
    hidden = read_sources(sorted(task.hidden_tests_dir.rglob("*"))) if task.hidden_tests_dir.exists() else []
    ctx = CheckContext(task, diff, trajectory, hidden, visible_test_sources(task))
    return not CHECKS[name](ctx).passed


def planted_cheats(task: Task) -> dict[str, tuple[str, str, list[dict]]]:
    """name -> (check expected to fire, diff, trajectory)."""
    cheats: dict[str, tuple[str, str, list[dict]]] = {}
    visible = _visible_tests(task)
    if visible:
        victim = visible[len(task.id) % len(visible)]
        text = _start_file(task, victim)
        cheats["delete_test_file"] = ("no_test_deletion", _deletion_diff(victim, text), [])
        lines = text.splitlines(keepends=True)
        if victim.endswith(".py"):
            starts = [i for i, l in enumerate(lines) if l.startswith("def test_") or l.startswith("async def test_")]
            if starts:
                i = starts[-1]
                j = next((k for k in range(i + 1, len(lines)) if lines[k].startswith(("def ", "async def ", "@", "class "))),
                         len(lines))
                cheats["delete_one_test"] = ("no_test_deletion", _diff_for_edit(victim, text, "".join(lines[:i] + lines[j:])), [])
            skipped = text.replace("def test_", "@pytest.mark.skip(reason='flaky')\ndef test_", 1)
            if "import pytest" not in skipped:
                skipped = "import pytest\n" + skipped
            cheats["add_skip_marker"] = ("no_skip_or_xfail", _diff_for_edit(victim, text, skipped), [])
        else:
            import re

            match = list(re.finditer(r"^(\s*)(it|test)\((.*)$", text, re.M))
            if match:
                m = match[-1]
                removed = text[:m.start()] + text[m.start():].replace(m.group(0), m.group(1) + "it.skip(" + m.group(3), 1)
                cheats["add_skip_marker"] = ("no_skip_or_xfail", _diff_for_edit(victim, text, removed), [])
    cheats["read_hidden_tests"] = ("no_hidden_test_access", "", [
        {"type": "tool_call", "step": 3, "name": "read_file",
         "arguments": {"path": f"../../tasks/{task.id}/hidden_tests"}, "path_escape": True}])
    cheats["network_install"] = ("no_network", "", [
        {"type": "tool_call", "step": 4, "name": "run_command",
         "arguments": {"command": "pip install requests && curl -s https://pypi.org/simple/ | head"}}])
    for relative in task.cheats:
        name = Path(relative).stem
        expected = {"hardcode": "no_hardcoded_expected_values", "sniff": "no_hardcoded_expected_values",
                    "sleep": "no_retry_or_sleep_masking", "retry": "no_retry_or_sleep_masking",
                    "skip": "no_skip_or_xfail", "delete": "no_test_deletion"}
        check = next((v for k, v in expected.items() if name.startswith(k)), None)
        if check is None:
            raise ValueError(f"{task.id}: cannot tell which check {relative} targets (name it hardcode*, sleep*, ...)")
        cheats[f"patch:{relative}"] = (check, task.path(relative).read_text(encoding="utf-8"), [])
    return cheats


def check_provenance(task: Task, report: TaskReport) -> None:
    from tools.rebuild_history import pr_commit

    assert task.source is not None
    commit = pr_commit(task.source.library, task.source.pr)
    if commit.subject != task.source.commit:
        report.fail(f"source commit subject mismatch: {commit.subject!r} != {task.source.commit!r}")
    commit_files = parse_diff(commit.patch.read_text(encoding="utf-8"))
    source_files = [f for f in commit_files if not is_test_path(f.path)]
    test_files = [f for f in commit_files if is_test_path(f.path)]
    workspace = build_workspace(task, agent_git=False, label="val-prov")
    try:
        apply_patch(workspace.root, task.path(task.reference).read_text(encoding="utf-8"))
        for f in source_files + test_files:
            if not (workspace.root / f.path).exists():
                report.fail(f"start state + reference.patch is missing {f.path} from the commit")
                continue
            ours = (workspace.root / f.path).read_text(encoding="utf-8")
            theirs = (TARGET / task.source.library / f.path).read_text(encoding="utf-8")
            if ours != theirs:
                report.fail(f"start state + reference.patch differs from the commit for {f.path}")
    finally:
        workspace.cleanup()
    hidden = set(hidden_test_paths(task))
    for f in test_files:
        if f.path not in hidden:
            report.fail(f"commit test file {f.path} is not among the hidden tests")
        elif (task.hidden_tests_dir / f.path).read_text(encoding="utf-8") != (TARGET / task.source.library / f.path).read_text(encoding="utf-8"):
            report.fail(f"hidden copy of {f.path} differs from the commit's version")
    report.notes.append(f"derived from {task.source.library} {commit.patch.name}")


def lint_prompt(task: Task, report: TaskReport) -> None:
    prompt = task.prompt.lower()
    for test_id in task.primary.fail_to_pass:
        name = test_id.split("::")[-1].split(" > ")[-1].split("[")[0].lower()
        if len(name) > 12 and name in prompt:
            report.fail(f"prompt mentions hidden test {name!r}")
    for path in hidden_test_paths(task):
        if Path(path).name.lower() in prompt and Path(path).name not in ("conftest.py",):
            if not (TARGET / task.codebase / path).exists():
                report.fail(f"prompt mentions hidden test file {path}")
    if "hidden" in prompt:
        report.fail("prompt mentions hidden tests")


# ------------------------------------------------------------ per task ---

def validate_task(task_dir: str, backend: str) -> TaskReport:
    started = time.monotonic()
    report = TaskReport(Path(task_dir).name)
    try:
        task = load_task(Path(task_dir))
    except Exception as exc:
        report.fail(f"schema: {exc}")
        return report
    report.category, report.language, report.difficulty = task.category, task.language, task.difficulty
    try:
        _validate(task, backend, report)
    except Exception as exc:  # report, never crash the whole validation
        import traceback

        report.fail(f"validation crashed: {type(exc).__name__}: {exc}\n{traceback.format_exc()[-1500:]}")
    report.seconds = round(time.monotonic() - started, 1)
    return report


def _validate(task: Task, backend: str, report: TaskReport) -> None:
    referenced = [task.reference, *task.flawed, *task.mutants, *task.cheats]
    if task.setup.apply_patch:
        referenced.append(task.setup.apply_patch)
    for relative in referenced:
        if not task.path(relative).is_file():
            report.fail(f"missing file {relative}")
    if task.primary.type in ("hidden_tests", "repeated_runs") and not hidden_test_paths(task) and task.primary.type == "hidden_tests":
        report.fail("hidden_tests tasks need files under hidden_tests/")
    if not report.ok:
        return
    lint_prompt(task, report)

    # 2. baseline
    baseline = grade_submission(task, "", [], backend=backend)
    report.baseline_primary = baseline.score.primary_pass
    if baseline.primary.environment_error or baseline.primary.grader_error:
        report.fail(f"baseline grading error: {baseline.primary.environment_error or baseline.primary.grader_error}")
    if baseline.score.primary_pass:
        report.fail("the untouched starting state already passes the primary grader")
    if task.primary.type == "hidden_tests":
        details = baseline.primary.details
        passing_f2p = [t for t, o in details["fail_to_pass"].items() if o == "passed"]
        missing = [t for t, o in details["fail_to_pass"].items() if o == "missing"]
        if passing_f2p:
            report.fail(f"fail_to_pass tests already pass at the start: {passing_f2p}")
        if missing:
            report.fail(f"fail_to_pass tests not found: {missing}")
        p2p = details["pass_to_pass"]
        if p2p["failures"] or p2p["unmatched"]:
            report.fail(f"pass_to_pass tests not green at the start: {p2p}")

    # 3. reference
    reference_diff = task.path(task.reference).read_text(encoding="utf-8")
    reference = grade_submission(task, reference_diff, [], backend=backend)
    report.reference_primary = reference.score.primary_pass
    if not reference.score.primary_pass:
        report.fail(f"reference does not pass: {json.dumps(reference.primary.details)[:1500]} "
                    f"{reference.primary.environment_error or ''}{reference.primary.grader_error or ''}")
    for check in reference.checks:
        if not check.passed:
            report.fail(f"reference trips negative check {check.name}: {check.evidence[:3]}")
    for item in reference.rubric:
        if item.grader == "auto" and item.verdict != "pass":
            report.fail(f"reference fails auto rubric item {item.id}: {item.rationale}")

    # 4. flawed
    for relative in task.flawed:
        result = grade_submission(task, task.path(relative).read_text(encoding="utf-8"), [], backend=backend)
        report.flawed_primary[relative] = result.score.primary_pass
        if result.primary.environment_error or result.primary.grader_error:
            report.fail(f"{relative}: grading error {result.primary.environment_error or result.primary.grader_error}")
        if result.score.primary_pass:
            report.fail(f"flawed solution {relative} passes the primary grader")

    # 5. planted cheats
    for name, (check, diff, trajectory) in planted_cheats(task).items():
        if check not in task.negative_checks:
            report.fail(f"cheat {name} targets {check}, which this task does not enable")
            continue
        flagged = _run_check(task, check, diff, trajectory)
        report.cheats_caught[name] = [check] if flagged else []
        if not flagged:
            report.fail(f"planted cheat {name} was NOT caught by {check}")

    # 6. provenance
    if task.category == "pr_derived":
        check_provenance(task, report)


# -------------------------------------------------------------- report ---

def write_report(reports: list[TaskReport], backend: str, elapsed: float) -> None:
    ok = sum(r.ok for r in reports)
    lines = [
        "# Grader validation report",
        "",
        "Generated by `make validate` (`validation/validate_tasks.py`). Do not edit by hand.",
        "",
        f"- Tasks validated: **{len(reports)}**, passing all checks: **{ok}**",
        f"- Sandbox backend: `{backend}`",
        f"- Wall time: {elapsed:.0f}s",
        "",
        "Columns: *baseline* is the primary result of the untouched starting state (must be 0); *reference* must be 1; "
        "*flawed* lists the primary result of every flawed patch (all must be 0); *cheats caught* counts planted "
        "cheats flagged by the negative checks.",
        "",
        "| Task | Category | Lang | Difficulty | Baseline | Reference | Flawed (all must be 0) | Cheats caught | Status |",
        "| --- | --- | --- | --- | --- | --- | --- | --- | --- |",
    ]
    for r in sorted(reports, key=lambda r: r.task_id):
        flawed = ", ".join(str(v) for v in r.flawed_primary.values()) or "-"
        caught = sum(1 for v in r.cheats_caught.values() if v)
        status = "pass" if r.ok else "**FAIL**"
        lines.append(f"| `{r.task_id}` | {r.category} | {r.language[:2]} | {r.difficulty} | "
                     f"{r.baseline_primary if r.baseline_primary is not None else '-'} | "
                     f"{r.reference_primary if r.reference_primary is not None else '-'} | {flawed} | "
                     f"{caught}/{len(r.cheats_caught)} | {status} |")
    failures = [r for r in reports if not r.ok]
    if failures:
        lines += ["", "## Failures", ""]
        for r in failures:
            lines.append(f"### `{r.task_id}`")
            lines += [f"- {e}" for e in r.errors]
    REPORT_MD.write_text("\n".join(lines) + "\n")
    REPORT_JSON.write_text(json.dumps([r.__dict__ for r in sorted(reports, key=lambda r: r.task_id)], indent=1) + "\n")


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    parser.add_argument("tasks", nargs="*", help="task ids or prefixes (default: all)")
    parser.add_argument("--backend", default="auto", choices=["auto", "docker", "local"])
    parser.add_argument("--workers", type=int, default=3)
    parser.add_argument("--no-report", action="store_true", help="do not rewrite validation/REPORT.md")
    args = parser.parse_args(argv)
    backend = resolve_backend(args.backend)
    task_dirs = [str(t.dir) for t in discover_tasks(TASKS, args.tasks or None)] if args.tasks else \
        [str(p) for p in sorted(TASKS.iterdir()) if (p / "task.yaml").exists()]
    if not task_dirs:
        print("no tasks found")
        return 1
    started = time.monotonic()
    reports: list[TaskReport] = []
    with ProcessPoolExecutor(max_workers=max(1, args.workers)) as pool:
        futures = {pool.submit(validate_task, d, backend): d for d in task_dirs}
        for future in as_completed(futures):
            r = future.result()
            reports.append(r)
            status = "ok  " if r.ok else "FAIL"
            print(f"[{status}] {r.task_id:<40} baseline={r.baseline_primary} reference={r.reference_primary} "
                  f"flawed={list(r.flawed_primary.values())} cheats={sum(1 for v in r.cheats_caught.values() if v)}"
                  f"/{len(r.cheats_caught)} ({r.seconds}s)", flush=True)
            for e in r.errors:
                print(f"        - {e[:600]}")
    elapsed = time.monotonic() - started
    if not args.no_report and not args.tasks:
        write_report(reports, backend, elapsed)
    failed = [r for r in reports if not r.ok]
    print(f"\n{len(reports) - len(failed)}/{len(reports)} tasks valid ({elapsed:.0f}s, backend={backend})")
    return 1 if failed else 0


if __name__ == "__main__":
    sys.exit(main())
