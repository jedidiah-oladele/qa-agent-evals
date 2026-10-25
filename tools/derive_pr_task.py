"""Derive a PR-derived task skeleton from a merged PR in a target library's history.

    uv run python -m tools.derive_pr_task ledgerkit 21 pr_016_invoice_void --difficulty easy

What it produces in ``tasks/<task_id>/``:

* ``bug.patch``       the commit's *source* changes reverted on top of the
                      current library (later commits stay in place).
* ``reference.patch`` the whole commit (source changes plus the tests it
                      added), re-expressed against that starting state, so
                      ``start + reference == HEAD`` for every file the commit
                      touched.
* ``hidden_tests/``   the test files the commit added, byte for byte. They are
                      also listed in ``setup.remove_paths`` so the agent starts
                      without them.
* ``task.yaml``       a skeleton whose prompt is the PR description and whose
                      fail_to_pass list is every test in the commit's test
                      files. Edge-case hidden tests, flawed solutions and the
                      rubric are written by hand afterwards.

``validation/validate_tasks.py`` re-checks the provenance on every run.
"""

from __future__ import annotations

import argparse
import shutil
import subprocess
import tempfile
from pathlib import Path

import yaml

from graders.diffparse import is_test_path, parse_diff
from harness.paths import TARGET, TASKS
from harness.workspace import apply_patch, tool_root

from .rebuild_history import commit_message, pr_commit


def _diff_dirs(before: Path, after: Path, paths: list[str]) -> str:
    chunks = []
    for relative in paths:
        a, b = before / relative, after / relative
        result = subprocess.run(
            [
                "git",
                "diff",
                "--no-index",
                "--no-color",
                str(a) if a.exists() else "/dev/null",
                str(b) if b.exists() else "/dev/null",
            ],
            capture_output=True,
            text=True,
        )
        text = result.stdout
        if not text:
            continue
        text = text.replace(f"a{a}", f"a/{relative}").replace(f"b{b}", f"b/{relative}")
        text = text.replace(str(a), relative).replace(str(b), relative)
        chunks.append(text)
    return "".join(chunks)


def _literal_strings(dumper: yaml.SafeDumper, value: str) -> yaml.ScalarNode:
    style = "|" if "\n" in value else None
    return dumper.represent_scalar("tag:yaml.org,2002:str", value, style=style)


yaml.SafeDumper.add_representer(str, _literal_strings)


def derive(library: str, pr: int, task_id: str, difficulty: str, language: str) -> Path:
    commit = pr_commit(library, pr)
    files = parse_diff(commit.patch.read_text(encoding="utf-8"))
    source = [f for f in files if not is_test_path(f.path)]
    tests = [f for f in files if is_test_path(f.path)]
    source_patch = "".join(f.text + "\n" for f in source)

    scratch = Path(tempfile.mkdtemp(prefix="derive-", dir=tool_root()))
    try:
        head = scratch / "head"
        start = scratch / "start"
        ignore = shutil.ignore_patterns("node_modules", "__pycache__", ".pytest_cache", ".ruff_cache")
        shutil.copytree(TARGET / library, head, ignore=ignore)
        shutil.copytree(TARGET / library, start, ignore=ignore)
        apply_patch(start, source_patch, reverse=True)
        paths = [f.path for f in source]
        bug = _diff_dirs(head, start, paths)
        # The reference is the whole commit: its source change plus the tests
        # the PR added (which the starting state removes via remove_paths).
        for f in tests:
            (start / f.path).unlink(missing_ok=True)
        reference = _diff_dirs(start, head, paths + [f.path for f in tests])
    finally:
        shutil.rmtree(scratch, ignore_errors=True)

    task_dir = TASKS / task_id
    (task_dir / "hidden_tests").mkdir(parents=True, exist_ok=True)
    (task_dir / "flawed").mkdir(exist_ok=True)
    (task_dir / "bug.patch").write_text(bug)
    (task_dir / "reference.patch").write_text(reference)
    for f in tests:
        dest = task_dir / "hidden_tests" / f.path
        dest.parent.mkdir(parents=True, exist_ok=True)
        shutil.copy(TARGET / library / f.path, dest)

    message = commit_message(commit.patch)
    title, _, body = message.partition("\n\n")
    yaml_path = task_dir / "task.yaml"
    if not yaml_path.exists():
        skeleton = {
            "id": task_id,
            "title": title.split(" (#")[0],
            "language": language,
            "category": "pr_derived",
            "difficulty": difficulty,
            "prompt": f"Implement this pull request.\n\n**{title.split(' (#')[0]}**\n\n{body.strip()}\n",
            "setup": {"apply_patch": "bug.patch", "remove_paths": [f.path for f in tests]},
            "test_cmd": "pytest -q" if language == "python" else "npx vitest run",
            "primary": {"type": "hidden_tests", "fail_to_pass": ["TODO"], "pass_to_pass": ["tests/"]},
            "rubric": [],
            "negative_checks": [
                "no_hidden_test_access",
                "no_test_deletion",
                "no_skip_or_xfail",
                "no_hardcoded_expected_values",
                "no_network",
            ],
            "limits": {"max_steps": 40, "timeout_s": 900},
            "reference": "reference.patch",
            "flawed": [],
            "source": {"library": library, "pr": pr, "commit": commit.subject},
        }
        yaml_path.write_text(yaml.safe_dump(skeleton, sort_keys=False, width=100))
    print(f"derived {task_id} from {commit.patch.name}: {len(source)} source file(s), {len(tests)} test file(s)")
    return task_dir


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    parser.add_argument("library", choices=["shopcore", "ledgerkit"])
    parser.add_argument("pr", type=int)
    parser.add_argument("task_id")
    parser.add_argument("--difficulty", default="medium", choices=["easy", "medium", "hard"])
    args = parser.parse_args()
    language = "python" if args.library == "shopcore" else "typescript"
    derive(args.library, args.pr, args.task_id, args.difficulty, language)


if __name__ == "__main__":
    main()
