"""Rebuild the git history of the target libraries from committed patch series.

Nested ``.git`` directories cannot be committed inside this repository, so
each target library's history lives in ``target/history/<lib>/`` as a
``git format-patch`` series. This script replays a series with ``git am``
into ``.history/<lib>`` (git-ignored) and checks that the result is
byte-for-byte identical to ``target/<lib>/``.

Commits are replayed with fixed author/committer identities and dates, so the
rebuilt commit hashes are the same on every machine.

    uv run python -m tools.rebuild_history            # rebuild and verify both
    uv run python -m tools.rebuild_history shopcore   # one library
"""

from __future__ import annotations

import argparse
import filecmp
import os
import re
import shutil
import subprocess
import sys
from dataclasses import dataclass
from pathlib import Path

REPO = Path(__file__).resolve().parent.parent
TARGET = REPO / "target"
HISTORY_OUT = REPO / ".history"
LIBRARIES = ("shopcore", "ledgerkit")
IGNORED = {"node_modules", "__pycache__", ".pytest_cache", ".ruff_cache", ".git"}


@dataclass(frozen=True)
class HistoryCommit:
    index: int
    patch: Path
    subject: str
    pr: int | None


def patch_series(lib: str) -> list[Path]:
    return sorted((TARGET / "history" / lib).glob("*.patch"))


def commits(lib: str) -> list[HistoryCommit]:
    """Parse the patch series into commit metadata (subject, PR number)."""
    result = []
    for i, patch in enumerate(patch_series(lib), start=1):
        text = patch.read_text(encoding="utf-8")
        subject = _subject(text, patch.stem)
        pr = re.search(r"\(#(\d+)\)$", subject)
        result.append(HistoryCommit(i, patch, subject, int(pr.group(1)) if pr else None))
    return result


def _subject(text: str, fallback: str) -> str:
    header = text.split("\n\n", 1)[0] + "\n"
    match = re.search(r"^Subject: (?:\[PATCH[^\]]*\] )?(.+?)\n(?!\s)", header, re.M | re.S)
    return " ".join(match.group(1).split()) if match else fallback


def commit_message(patch: Path) -> str:
    """Full commit message (subject + body) of a patch in the series."""
    text = patch.read_text(encoding="utf-8")
    body = text.split("\n\n", 1)[1].split("\n---\n", 1)[0]
    return _subject(text, patch.stem) + "\n\n" + body.strip() + "\n"


def pr_commit(lib: str, pr: int) -> HistoryCommit:
    for commit in commits(lib):
        if commit.pr == pr:
            return commit
    raise KeyError(f"{lib}: no commit for PR #{pr}")


def _env() -> dict[str, str]:
    env = dict(os.environ)
    env.update(
        GIT_COMMITTER_NAME="Jedidiah Oladele",
        GIT_COMMITTER_EMAIL="66447747+jedidiah-oladele@users.noreply.github.com",
        GIT_CONFIG_GLOBAL=os.devnull,
        GIT_CONFIG_NOSYSTEM="1",
    )
    return env


def rebuild(lib: str, dest: Path | None = None) -> Path:
    dest = dest or HISTORY_OUT / lib
    if dest.exists():
        shutil.rmtree(dest)
    dest.mkdir(parents=True)
    env = _env()
    subprocess.run(["git", "init", "-q", "-b", "main"], cwd=dest, check=True, env=env)
    subprocess.run(
        ["git", "-c", "user.name=x", "-c", "user.email=x@x", "am", "-q", "--committer-date-is-author-date",
         *[str(p) for p in patch_series(lib)]],
        cwd=dest, check=True, env=env,
    )
    return dest


def tree_differences(a: Path, b: Path) -> list[str]:
    """Relative paths that differ between two directory trees (ignoring caches)."""
    diffs: list[str] = []

    def walk(cmp: filecmp.dircmp, prefix: str) -> None:
        for name in cmp.left_only + cmp.right_only:
            if name not in IGNORED:
                diffs.append(prefix + name)
        for name in cmp.diff_files:
            diffs.append(prefix + name)
        for name, sub in cmp.subdirs.items():
            if name not in IGNORED:
                walk(sub, prefix + name + "/")

    walk(filecmp.dircmp(a, b, ignore=list(IGNORED)), "")
    # dircmp compares shallowly by stat; recheck contents to be exact.
    return [d for d in diffs if not ((a / d).is_file() and (b / d).is_file() and filecmp.cmp(a / d, b / d, False))]


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    parser.add_argument("libs", nargs="*", default=list(LIBRARIES))
    args = parser.parse_args(argv)
    ok = True
    for lib in args.libs:
        dest = rebuild(lib)
        diffs = tree_differences(dest, TARGET / lib)
        head = subprocess.run(["git", "rev-parse", "--short", "HEAD"], cwd=dest, capture_output=True, text=True)
        count = len(patch_series(lib))
        if diffs:
            ok = False
            print(f"{lib}: {count} commits replayed, but tree differs from target/{lib}: {diffs}")
        else:
            print(f"{lib}: {count} commits replayed into {dest.relative_to(REPO)} (HEAD {head.stdout.strip()}), "
                  f"tree matches target/{lib}")
    return 0 if ok else 1


if __name__ == "__main__":
    sys.exit(main())
