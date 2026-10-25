"""Task authoring helper: edit a scratch checkout, save the change as a task patch.

    uv run python -m tools.author checkout bf_001_tax_half_even --clean   # clean target library
    uv run python -m tools.author checkout bf_001_tax_half_even           # the task's starting state
    #   ... edit files under .scratch/author/<task_id>/ ...
    uv run python -m tools.author save bf_001_tax_half_even bug.patch     # writes tasks/<id>/bug.patch, resets
    uv run python -m tools.author apply bf_001_tax_half_even reference.patch  # re-apply a saved patch to edit it
    uv run python -m tools.author tests bf_001_tax_half_even reference.patch  # test ids + outcomes (with hidden tests)

Patches are plain ``git diff`` output relative to the library root.
"""

from __future__ import annotations

import argparse
import os
import shutil
import subprocess
import sys
from pathlib import Path

from harness.paths import SCRATCH, TARGET, TASKS
from harness.task import load_task

AUTHOR = SCRATCH / "author"
IGNORE = shutil.ignore_patterns("node_modules", "__pycache__", ".pytest_cache", ".ruff_cache", ".git")
ENV = dict(os.environ, GIT_AUTHOR_NAME="author", GIT_AUTHOR_EMAIL="a@a", GIT_COMMITTER_NAME="author",
           GIT_COMMITTER_EMAIL="a@a", GIT_CONFIG_GLOBAL=os.devnull)


def git(cwd: Path, *args: str, input_text: str | None = None) -> str:
    result = subprocess.run(["git", *args], cwd=cwd, env=ENV, input=input_text, capture_output=True, text=True)
    if result.returncode != 0:
        sys.exit(f"git {' '.join(args)}: {result.stderr}")
    return result.stdout


def library_for(task_id: str, explicit: str | None) -> str:
    if explicit:
        return explicit
    yaml_path = TASKS / task_id / "task.yaml"
    if yaml_path.exists():
        return load_task(TASKS / task_id).codebase
    sys.exit("task.yaml not found; pass --lib shopcore|ledgerkit")


def checkout(task_id: str, clean: bool, lib: str | None) -> Path:
    dest = AUTHOR / task_id
    if dest.exists():
        shutil.rmtree(dest)
    library = library_for(task_id, lib)
    shutil.copytree(TARGET / library, dest, ignore=IGNORE)
    if not clean:
        task = load_task(TASKS / task_id)
        patch = task.path(task.setup.apply_patch) if task.setup.apply_patch else None
        if patch and patch.exists() and patch.read_text().strip():
            subprocess.run(["git", "apply", "--whitespace=nowarn", str(patch)], cwd=dest, check=True,
                           env=dict(ENV, GIT_DIR=str(dest / ".nogit")))
        for relative in task.setup.remove_paths:
            target = dest / relative
            shutil.rmtree(target) if target.is_dir() else target.unlink(missing_ok=True)
    if library == "ledgerkit":
        from harness.workspace import link_node_modules

        link_node_modules(dest, str((TARGET / "ledgerkit" / "node_modules").resolve()))
    git(dest, "init", "-q")
    (dest / ".git" / "info" / "exclude").write_text("node_modules\n__pycache__\n.pytest_cache\n.qa_grader\n")
    git(dest, "add", "-A")
    git(dest, "commit", "-q", "-m", "base")
    print(dest)
    return dest


def save(task_id: str, relative: str, keep: bool) -> None:
    dest = AUTHOR / task_id
    git(dest, "add", "-A")
    diff = git(dest, "diff", "--cached", "--binary", "--no-color")
    out = TASKS / task_id / relative
    out.parent.mkdir(parents=True, exist_ok=True)
    out.write_text(diff)
    print(f"wrote {out.relative_to(TASKS.parent)} ({len(diff.splitlines())} lines)")
    if keep:
        git(dest, "reset", "-q")
    else:
        git(dest, "reset", "-q", "--hard")
        git(dest, "clean", "-qfd")


def apply(task_id: str, relative: str) -> None:
    dest = AUTHOR / task_id
    git(dest, "apply", "--whitespace=nowarn", input_text=(TASKS / task_id / relative).read_text())
    print(f"applied {relative} to {dest}")


def list_tests(task_id: str, relative: str | None, hidden: bool) -> None:
    """Run the suite on start state + an optional patch and print each test id with its outcome."""
    from graders.context import GradeContext
    from graders.runners import run_tests
    from harness.sandbox import resolve_backend

    task = load_task(TASKS / task_id)
    diff = (TASKS / task_id / relative).read_text() if relative else ""
    ctx = GradeContext(task, diff, backend=resolve_backend("auto"))
    with ctx.environment(hidden=hidden) as (_, sandbox):
        report = run_tests(sandbox, task.language, timeout_s=600)
    for test_id, outcome in sorted(report.outcomes.items()):
        print(f"{outcome:8} {test_id}")
    for name, error in report.collection_errors.items():
        print(f"COLLECTION ERROR {name}: {error[:500]}")
    if report.runner_error:
        print("RUNNER ERROR", report.runner_error, report.output_tail[-2000:])


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    sub = parser.add_subparsers(dest="cmd", required=True)
    c = sub.add_parser("checkout")
    c.add_argument("task_id")
    c.add_argument("--clean", action="store_true")
    c.add_argument("--lib")
    s = sub.add_parser("save")
    s.add_argument("task_id")
    s.add_argument("patch")
    s.add_argument("--keep", action="store_true", help="keep the edits in the scratch checkout")
    a = sub.add_parser("apply")
    a.add_argument("task_id")
    a.add_argument("patch")
    t = sub.add_parser("tests", help="list test ids and outcomes for start state + patch (+ hidden tests)")
    t.add_argument("task_id")
    t.add_argument("patch", nargs="?")
    t.add_argument("--no-hidden", action="store_true")
    args = parser.parse_args()
    if args.cmd == "tests":
        list_tests(args.task_id, args.patch, not args.no_hidden)
        return
    if args.cmd == "checkout":
        checkout(args.task_id, args.clean, args.lib)
    elif args.cmd == "save":
        save(args.task_id, args.patch, args.keep)
    else:
        apply(args.task_id, args.patch)


if __name__ == "__main__":
    main()
