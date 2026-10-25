"""A small unified-diff parser (git diff format) used by checks and graders."""

from __future__ import annotations

import fnmatch
import re
from dataclasses import dataclass, field

_HEADER = re.compile(r"^diff --git a/(.+?) b/(.+)$")
_HUNK = re.compile(r"^@@ -(\d+)(?:,(\d+))? \+(\d+)(?:,(\d+))? @@")

TEST_GLOBS = ("tests/*", "tests/**", "*/tests/*", "test_*.py", "*_test.py", "*.test.ts", "*.spec.ts")


@dataclass
class FileDiff:
    old_path: str | None
    new_path: str | None
    added: list[tuple[int, str]] = field(default_factory=list)
    removed: list[tuple[int, str]] = field(default_factory=list)
    binary: bool = False
    text: str = ""

    @property
    def path(self) -> str:
        return self.new_path or self.old_path or ""

    @property
    def status(self) -> str:
        if self.old_path is None:
            return "added"
        if self.new_path is None:
            return "deleted"
        if self.old_path != self.new_path:
            return "renamed"
        return "modified"


def parse_diff(text: str) -> list[FileDiff]:
    files: list[FileDiff] = []
    current: FileDiff | None = None
    old_line = new_line = 0
    chunk: list[str] = []
    for line in text.splitlines():
        header = _HEADER.match(line)
        if header:
            if current is not None:
                current.text = "\n".join(chunk)
            current = FileDiff(header.group(1), header.group(2))
            files.append(current)
            chunk = [line]
            continue
        if current is None:
            continue
        chunk.append(line)
        if line.startswith("new file mode"):
            current.old_path = None
        elif line.startswith("deleted file mode"):
            current.new_path = None
        elif line.startswith("rename from "):
            current.old_path = line[len("rename from "):]
        elif line.startswith("rename to "):
            current.new_path = line[len("rename to "):]
        elif line.startswith("Binary files") or line.startswith("GIT binary patch"):
            current.binary = True
        elif line.startswith("--- ") or line.startswith("+++ "):
            continue
        elif (hunk := _HUNK.match(line)):
            old_line, new_line = int(hunk.group(1)), int(hunk.group(3))
        elif line.startswith("+"):
            current.added.append((new_line, line[1:]))
            new_line += 1
        elif line.startswith("-"):
            current.removed.append((old_line, line[1:]))
            old_line += 1
        elif line.startswith(" "):
            old_line += 1
            new_line += 1
    if current is not None:
        current.text = "\n".join(chunk)
    return files


def is_test_path(path: str) -> bool:
    return any(fnmatch.fnmatch(path, glob) for glob in TEST_GLOBS)


def filter_diff(text: str, keep) -> str:
    """Return only the per-file sections of ``text`` whose path satisfies ``keep``."""
    out = [f.text for f in parse_diff(text) if keep(f.path)]
    return ("\n".join(out) + "\n") if out else ""


def changed_paths(text: str) -> list[str]:
    return [f.path for f in parse_diff(text)]
