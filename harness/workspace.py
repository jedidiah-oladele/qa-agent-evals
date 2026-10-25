"""Build task workspaces and compute the agent's diff.

A workspace is a throwaway copy of a target library in the task's starting
state. Two git repositories are involved:

* an **external** baseline repo (``<tmp>/baseline.git``) that lives outside
  the workspace, so the agent can neither see nor tamper with it. The
  authoritative final diff is computed against it.
* an in-workspace ``.git`` with a single "starting state" commit, purely for
  the agent's convenience (``git diff``, ``git status``). It has no history,
  so PR-derived tasks cannot be solved by reading ``git log``.

Hidden tests are never copied into an agent workspace. Grading builds a
*separate* workspace: starting state + the agent's diff + hidden tests.
"""

from __future__ import annotations

import fnmatch
import os
import shutil
import subprocess
import tempfile
from dataclasses import dataclass, field
from pathlib import Path

from .paths import REPO, TARGET, WORKSPACE_IGNORES
from .task import Task

_GIT_ENV = {
    "GIT_AUTHOR_NAME": "qa-agent-evals",
    "GIT_AUTHOR_EMAIL": "harness@qa-agent-evals.invalid",
    "GIT_COMMITTER_NAME": "qa-agent-evals",
    "GIT_COMMITTER_EMAIL": "harness@qa-agent-evals.invalid",
    "GIT_AUTHOR_DATE": "2026-10-01T00:00:00Z",
    "GIT_COMMITTER_DATE": "2026-10-01T00:00:00Z",
    "GIT_CONFIG_GLOBAL": os.devnull,
    "GIT_CONFIG_NOSYSTEM": "1",
}


class PatchError(RuntimeError):
    """A patch did not apply cleanly."""


def _git(args: list[str], *, cwd: Path | None = None, git_dir: Path | None = None, work_tree: Path | None = None,
         input_text: str | None = None, check: bool = True) -> subprocess.CompletedProcess[str]:
    cmd = ["git"]
    if git_dir is not None:
        cmd += ["--git-dir", str(git_dir)]
    if work_tree is not None:
        cmd += ["--work-tree", str(work_tree)]
    env = dict(os.environ, **_GIT_ENV)
    env.pop("GIT_DIR", None)
    env.pop("GIT_WORK_TREE", None)
    result = subprocess.run(cmd + args, cwd=cwd, env=env, input=input_text, capture_output=True, text=True)
    if check and result.returncode != 0:
        raise RuntimeError(f"git {' '.join(args)} failed: {result.stderr.strip()}")
    return result


def _ignore(directory: str, names: list[str]) -> set[str]:
    return {n for n in names if any(fnmatch.fnmatch(n, pattern) for pattern in WORKSPACE_IGNORES)}


def tool_root() -> Path:
    """Parent directory for workspaces: outside the repository so nested git
    commands never see this repository's own .git."""
    base = Path(os.environ.get("QA_EVALS_TMP", tempfile.gettempdir())) / "qa-agent-evals"
    base.mkdir(parents=True, exist_ok=True)
    if REPO in base.resolve().parents:
        raise RuntimeError("QA_EVALS_TMP must not be inside the repository")
    return base


@dataclass
class Workspace:
    root: Path
    container: Path
    baseline_git: Path
    _closed: bool = field(default=False, repr=False)

    def diff(self) -> str:
        """Unified diff of everything the agent changed relative to the starting state."""
        _git(["add", "-A"], git_dir=self.baseline_git, work_tree=self.root)
        result = _git(["diff", "--cached", "--binary", "--no-color", "--no-ext-diff", "HEAD"],
                      git_dir=self.baseline_git, work_tree=self.root)
        _git(["reset", "-q"], git_dir=self.baseline_git, work_tree=self.root)
        return result.stdout

    def read_text(self, relative: str) -> str | None:
        path = self.root / relative
        try:
            return path.read_text(encoding="utf-8", errors="replace") if path.is_file() else None
        except OSError:
            return None

    def cleanup(self) -> None:
        if not self._closed:
            shutil.rmtree(self.container, ignore_errors=True)
            self._closed = True

    def __enter__(self) -> Workspace:
        return self

    def __exit__(self, *exc: object) -> None:
        self.cleanup()


def apply_patch(root: Path, patch_text: str, *, git_dir: Path | None = None, reverse: bool = False) -> None:
    """Apply a unified diff with ``git apply``, treating ``root`` as the top level."""
    if not patch_text.strip():
        return
    scratch = None
    if git_dir is None:
        scratch = Path(tempfile.mkdtemp(prefix="apply-", dir=tool_root()))
        git_dir = scratch / "g.git"
        _git(["init", "-q", "--bare", str(git_dir)])
    try:
        args = ["apply", "--whitespace=nowarn", "--binary"]
        if reverse:
            args.append("--reverse")
        result = _git(args, git_dir=git_dir, work_tree=root, cwd=root, input_text=patch_text, check=False)
        if result.returncode != 0:
            raise PatchError(result.stderr.strip() or "git apply failed")
    finally:
        if scratch is not None:
            shutil.rmtree(scratch, ignore_errors=True)


def _init_baseline(container: Path, root: Path) -> Path:
    git_dir = container / "baseline.git"
    _git(["init", "-q", "--bare", str(git_dir)])
    exclude = git_dir / "info" / "exclude"
    exclude.parent.mkdir(parents=True, exist_ok=True)
    exclude.write_text("\n".join(WORKSPACE_IGNORES) + "\n")
    _git(["add", "-A"], git_dir=git_dir, work_tree=root)
    _git(["commit", "-q", "--allow-empty", "-m", "starting state"], git_dir=git_dir, work_tree=root)
    return git_dir


def _init_agent_git(root: Path) -> None:
    _git(["init", "-q", "-b", "main"], cwd=root)
    (root / ".git" / "info").mkdir(parents=True, exist_ok=True)
    (root / ".git" / "info" / "exclude").write_text("\n".join(WORKSPACE_IGNORES[1:]) + "\n")
    _git(["add", "-A"], cwd=root)
    _git(["commit", "-q", "--allow-empty", "-m", "starting state"], cwd=root)


def build_workspace(
    task: Task,
    *,
    node_modules: str | None = None,
    agent_git: bool = True,
    apply_bug: bool = True,
    label: str = "agent",
) -> Workspace:
    """Create the task's starting state in a fresh temporary directory.

    ``node_modules``: where the TypeScript toolchain lives *as seen from inside
    the sandbox*; a ``node_modules`` symlink to it is created in the workspace.
    """
    container = Path(tempfile.mkdtemp(prefix=f"{task.id}-{label}-", dir=tool_root()))
    root = container / "work"
    try:
        shutil.copytree(TARGET / task.codebase, root, ignore=_ignore, symlinks=False)
        if apply_bug and task.setup.apply_patch:
            patch_file = task.path(task.setup.apply_patch)
            text = patch_file.read_text(encoding="utf-8") if patch_file.exists() else ""
            try:
                apply_patch(root, text)
            except PatchError as exc:
                raise PatchError(f"{task.id}: {task.setup.apply_patch} does not apply: {exc}") from exc
        for relative in task.setup.remove_paths:
            target = root / relative
            if target.is_dir():
                shutil.rmtree(target)
            elif target.exists():
                target.unlink()
        baseline = _init_baseline(container, root)
        if agent_git:
            _init_agent_git(root)
        if task.language == "typescript" and node_modules:
            link_node_modules(root, node_modules)
    except BaseException:
        shutil.rmtree(container, ignore_errors=True)
        raise
    return Workspace(root=root, container=container, baseline_git=baseline)


def link_node_modules(root: Path, source: str) -> None:
    """Create ``root/node_modules`` as a real directory of symlinks into ``source``.

    The shared install stays read-only, but tools that write caches or temp
    files under node_modules (Vite writes ``.vite-temp``) write into the
    workspace instead. If ``source`` is not visible on the host (Docker), the
    sandbox creates the links itself (see ``DockerSandbox``).
    """
    target = root / "node_modules"
    source_path = Path(source)
    if not source_path.is_dir():
        return
    target.mkdir(exist_ok=True)
    for entry in source_path.iterdir():
        if entry.name.startswith(".") and entry.name != ".bin":
            continue
        link = target / entry.name
        if not link.exists():
            os.symlink(entry, link)


def copy_hidden_tests(task: Task, root: Path) -> list[str]:
    """Copy ``hidden_tests/`` over the workspace (mirroring paths). Grading only."""
    copied: list[str] = []
    source = task.hidden_tests_dir
    if not source.exists():
        return copied
    for path in sorted(source.rglob("*")):
        if path.is_file() and "__pycache__" not in path.parts:
            relative = path.relative_to(source)
            dest = root / relative
            dest.parent.mkdir(parents=True, exist_ok=True)
            shutil.copy2(path, dest)
            copied.append(str(relative))
    return copied


def hidden_test_paths(task: Task) -> list[str]:
    source = task.hidden_tests_dir
    if not source.exists():
        return []
    return sorted(str(p.relative_to(source)) for p in source.rglob("*") if p.is_file())
