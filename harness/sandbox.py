"""Isolated execution environments for agent commands and grading.

Two backends share one interface:

``DockerSandbox`` (preferred)
    One container per episode from ``harness/docker/Dockerfile``:
    ``--network none``, CPU/memory/PID limits, all capabilities dropped,
    read-only root filesystem, non-root user. Only the workspace directory is
    mounted (at ``/work``). Hidden tests live in the task directory, which is
    never mounted; grading uses a *different* container and workspace.

``LocalSandbox`` (fallback when no Docker daemon is reachable)
    Runs commands in the workspace with a scrubbed environment, a new process
    group, ``RLIMIT_CPU``/``RLIMIT_FSIZE``/``RLIMIT_NOFILE`` limits and a hard
    wall-clock timeout. When bubblewrap (``bwrap``) works on the host - the
    usual case on Linux - every command runs inside a fresh mount, PID, IPC,
    UTS, user and **network** namespace that contains only system directories
    (read-only), the Python/Node toolchains (read-only) and the workspace
    (mounted at ``/work``). The repository, and therefore ``tasks/*/hidden_tests``,
    simply does not exist inside it. Without bubblewrap the fallback still never
    copies hidden tests into the workspace and the file tools refuse paths
    outside it, but a shell command could read the host filesystem; the
    ``isolation`` attribute records which level was used and every result
    carries it.
"""

from __future__ import annotations

import os
import resource
import shutil
import signal
import subprocess
import sys
import tempfile
import time
import uuid
from abc import ABC, abstractmethod
from dataclasses import dataclass
from functools import lru_cache
from pathlib import Path
from typing import Literal

from .config import SandboxConfig
from .paths import REPO, TARGET

DOCKER_IMAGE = "qa-agent-evals-sandbox:1"
SANDBOX_WORKDIR = "/work"
Backend = Literal["auto", "docker", "local"]


class SandboxError(RuntimeError):
    """The sandbox itself failed (an environment error, not an agent error)."""


@dataclass
class ExecResult:
    exit_code: int
    stdout: str
    stderr: str
    timed_out: bool
    duration_s: float

    @property
    def output(self) -> str:
        if self.stderr and self.stdout:
            return f"{self.stdout.rstrip()}\n{self.stderr}"
        return self.stdout or self.stderr


def _tail(path: Path, limit: int) -> str:
    size = path.stat().st_size
    with open(path, "rb") as handle:
        if size > limit:
            handle.seek(size - limit)
            data = handle.read()
            return f"[... {size - limit} bytes truncated ...]\n" + data.decode("utf-8", "replace")
        return handle.read().decode("utf-8", "replace")


class Sandbox(ABC):
    backend: str = "abstract"
    isolation: str = "none"

    def __init__(self, workspace_root: Path, config: SandboxConfig | None = None,
                 env: dict[str, str] | None = None) -> None:
        self.workspace_root = Path(workspace_root)
        self.config = config or SandboxConfig()
        self.env = dict(env or {})

    @property
    @abstractmethod
    def workdir(self) -> str:
        """The workspace path as seen by commands running in the sandbox."""

    @abstractmethod
    def exec(self, command: str, *, timeout_s: int | None = None, env: dict[str, str] | None = None) -> ExecResult:
        """Run ``command`` with bash in the workspace."""

    def close(self) -> None:  # noqa: B027 - optional hook
        pass

    def __enter__(self) -> Sandbox:
        return self

    def __exit__(self, *exc: object) -> None:
        self.close()


# ---------------------------------------------------------------- local ----

def _toolchain_paths() -> dict[str, Path]:
    """Host paths the sandbox needs read-only: interpreter, venv, node, node_modules."""
    paths: dict[str, Path] = {}
    venv = Path(sys.prefix)
    paths["venv"] = venv
    paths["python_base"] = Path(sys.base_prefix).resolve()
    # venv interpreters are symlinks, sometimes through a versionless alias
    # directory (uv: cpython-3.12-... -> cpython-3.12.15-...). Bind every hop.
    link = venv / "bin" / "python"
    for hop in range(8):
        if not link.is_symlink():
            break
        target = Path(os.readlink(link))
        link = target if target.is_absolute() else (link.parent / target)
        paths[f"python_hop{hop}"] = link.parent.parent
    node = shutil.which("node")
    if node:
        node_real = Path(node).resolve()
        paths["node_home"] = node_real.parent.parent
    modules = TARGET / "ledgerkit" / "node_modules"
    if modules.exists():
        paths["node_modules"] = modules.resolve()
    return paths


def local_node_modules() -> str:
    return str((TARGET / "ledgerkit" / "node_modules").resolve())


def _sandbox_path_env(paths: dict[str, Path], workdir: str) -> str:
    entries = [f"{workdir}/node_modules/.bin", str(paths["venv"] / "bin")]
    if "node_home" in paths:
        entries.append(str(paths["node_home"] / "bin"))
    entries += ["/usr/local/bin", "/usr/bin", "/bin"]
    return ":".join(entries)


@lru_cache
def bwrap_available() -> bool:
    """True when bubblewrap exists *and* can create namespaces on this host."""
    if not shutil.which("bwrap") or not sys.platform.startswith("linux"):
        return False
    try:
        probe = subprocess.run(
            ["bwrap", "--ro-bind", "/usr", "/usr", *_system_binds(), "--proc", "/proc", "--dev", "/dev",
             "--unshare-all", "--die-with-parent", "true"],
            capture_output=True, timeout=15,
        )
    except (OSError, subprocess.TimeoutExpired):
        return False
    return probe.returncode == 0


def _system_binds() -> list[str]:
    args: list[str] = []
    for name in ("bin", "lib", "lib64", "sbin", "lib32"):
        path = Path("/") / name
        if path.is_symlink():
            args += ["--symlink", os.readlink(path), str(path)]
        elif path.is_dir():
            args += ["--ro-bind", str(path), str(path)]
    for etc in ("passwd", "group", "hosts", "nsswitch.conf", "localtime", "ssl", "ca-certificates",
                "alternatives", "ld.so.cache", "ld.so.conf", "ld.so.conf.d"):
        path = Path("/etc") / etc
        if path.exists():
            args += ["--ro-bind", str(path), str(path)]
    return args


class LocalSandbox(Sandbox):
    backend = "local"

    def __init__(self, workspace_root: Path, config: SandboxConfig | None = None,
                 env: dict[str, str] | None = None, *, isolation: Literal["auto", "bwrap", "none"] = "auto",
                 network: bool = False, extra_ro_binds: list[Path] | None = None) -> None:
        super().__init__(workspace_root, config, env)
        if isolation == "auto":
            isolation = "bwrap" if bwrap_available() else "none"
        if isolation == "bwrap" and not bwrap_available():
            raise SandboxError("bubblewrap isolation requested but bwrap is not usable on this host")
        self.isolation = isolation
        self.network = network
        self._paths = _toolchain_paths()
        for i, path in enumerate(extra_ro_binds or []):
            self._paths[f"extra{i}"] = Path(path)

    @property
    def workdir(self) -> str:
        return SANDBOX_WORKDIR if self.isolation == "bwrap" else str(self.workspace_root)

    def _environment(self, extra: dict[str, str] | None) -> dict[str, str]:
        env = {
            "PATH": _sandbox_path_env(self._paths, self.workdir),
            "HOME": "/tmp" if self.isolation == "bwrap" else str(self._home()),
            "TMPDIR": "/tmp" if self.isolation == "bwrap" else str(self._home()),
            "LANG": "C.UTF-8",
            "LC_ALL": "C.UTF-8",
            "PYTHONDONTWRITEBYTECODE": "1",
            "PYTHONHASHSEED": "0",
            "NO_COLOR": "1",
            "FORCE_COLOR": "0",
            "CI": "1",
            "TZ": "UTC",
        }
        env.update(self.env)
        env.update(extra or {})
        return env

    def _home(self) -> Path:
        home = self.workspace_root.parent / "home"
        home.mkdir(exist_ok=True)
        return home

    def _argv(self, command: str, env: dict[str, str]) -> list[str]:
        if self.isolation != "bwrap":
            return ["bash", "-c", command]
        args = ["bwrap", "--ro-bind", "/usr", "/usr", *_system_binds(),
                "--proc", "/proc", "--dev", "/dev", "--tmpfs", "/tmp",
                "--bind", str(self.workspace_root), SANDBOX_WORKDIR]
        for path in dict.fromkeys(self._paths.values()):
            if path.exists():
                args += ["--ro-bind", str(path), str(path)]
        args += ["--unshare-all", "--die-with-parent", "--new-session", "--hostname", "sandbox",
                 "--chdir", SANDBOX_WORKDIR, "--clearenv"]
        if self.network:
            args.append("--share-net")
        for key, value in env.items():
            args += ["--setenv", key, value]
        return args + ["bash", "-c", command]

    def exec(self, command: str, *, timeout_s: int | None = None, env: dict[str, str] | None = None) -> ExecResult:
        timeout = timeout_s or self.config.command_timeout_s
        environment = self._environment(env)
        argv = self._argv(command, environment)
        cpu_limit = timeout + 5

        def limits() -> None:
            os.setsid()
            resource.setrlimit(resource.RLIMIT_CPU, (cpu_limit, cpu_limit + 5))
            resource.setrlimit(resource.RLIMIT_FSIZE, (512 * 1024 * 1024,) * 2)
            soft, hard = resource.getrlimit(resource.RLIMIT_NOFILE)
            resource.setrlimit(resource.RLIMIT_NOFILE, (min(4096, hard), hard))

        with tempfile.TemporaryDirectory(prefix="exec-") as tmp:
            out_path, err_path = Path(tmp) / "out", Path(tmp) / "err"
            start = time.monotonic()
            timed_out = False
            with open(out_path, "wb") as out, open(err_path, "wb") as err:
                try:
                    process = subprocess.Popen(
                        argv, cwd=self.workspace_root, env=environment if self.isolation != "bwrap" else
                        {"PATH": os.environ.get("PATH", "/usr/bin:/bin")},
                        stdin=subprocess.DEVNULL, stdout=out, stderr=err, preexec_fn=limits,
                    )
                except OSError as exc:
                    raise SandboxError(f"could not start command: {exc}") from exc
                try:
                    exit_code = process.wait(timeout=timeout)
                except subprocess.TimeoutExpired:
                    timed_out = True
                    try:
                        os.killpg(process.pid, signal.SIGKILL)
                    except ProcessLookupError:
                        pass
                    exit_code = process.wait()
            duration = time.monotonic() - start
            limit = self.config.output_limit_chars * 4
            return ExecResult(
                exit_code=124 if timed_out else exit_code,
                stdout=_tail(out_path, limit),
                stderr=_tail(err_path, limit),
                timed_out=timed_out,
                duration_s=round(duration, 3),
            )


# --------------------------------------------------------------- docker ----

@lru_cache
def docker_available() -> bool:
    if not shutil.which("docker"):
        return False
    try:
        probe = subprocess.run(["docker", "info", "--format", "{{.ServerVersion}}"], capture_output=True, timeout=20)
    except (OSError, subprocess.TimeoutExpired):
        return False
    return probe.returncode == 0


def docker_image_present(image: str = DOCKER_IMAGE) -> bool:
    if not docker_available():
        return False
    probe = subprocess.run(["docker", "image", "inspect", image], capture_output=True)
    return probe.returncode == 0


def docker_run_args(name: str, workspace_root: Path, config: SandboxConfig, *, network: bool,
                    image: str = DOCKER_IMAGE) -> list[str]:
    """The ``docker run`` command for one sandbox container (pure; unit-tested)."""
    uid, gid = (os.getuid(), os.getgid()) if hasattr(os, "getuid") else (1000, 1000)
    return [
        "docker", "run", "-d", "--rm", "--name", name,
        "--network", "bridge" if network else "none",
        "--cpus", str(config.cpus),
        "--memory", f"{config.memory_mb}m", "--memory-swap", f"{config.memory_mb}m",
        "--pids-limit", str(config.pids),
        "--cap-drop", "ALL", "--security-opt", "no-new-privileges",
        "--read-only", "--tmpfs", "/tmp:rw,exec,size=512m",
        "--user", f"{uid}:{gid}",
        "-e", "HOME=/tmp", "-e", "TZ=UTC", "-e", "CI=1", "-e", "PYTHONDONTWRITEBYTECODE=1",
        "-v", f"{workspace_root}:{SANDBOX_WORKDIR}:rw",
        "-w", SANDBOX_WORKDIR,
        image, "sleep", "infinity",
    ]


class DockerSandbox(Sandbox):
    backend = "docker"
    isolation = "docker"
    node_modules = "/opt/ledgerkit/node_modules"

    def __init__(self, workspace_root: Path, config: SandboxConfig | None = None,
                 env: dict[str, str] | None = None, *, network: bool = False, image: str = DOCKER_IMAGE) -> None:
        super().__init__(workspace_root, config, env)
        if not docker_available():
            raise SandboxError("Docker daemon is not reachable")
        self.name = f"qa-evals-{uuid.uuid4().hex[:12]}"
        args = docker_run_args(self.name, self.workspace_root, self.config, network=network, image=image)
        started = subprocess.run(args, capture_output=True, text=True)
        if started.returncode != 0:
            raise SandboxError(f"docker run failed: {started.stderr.strip()}")
        self._closed = False
        if (self.workspace_root / "package.json").exists() and not (self.workspace_root / "node_modules").exists():
            src = self.node_modules
            self.exec(f"mkdir -p node_modules && ln -s {src}/* {src}/.bin node_modules/", timeout_s=60)

    @property
    def workdir(self) -> str:
        return SANDBOX_WORKDIR

    def exec(self, command: str, *, timeout_s: int | None = None, env: dict[str, str] | None = None) -> ExecResult:
        timeout = timeout_s or self.config.command_timeout_s
        args = ["docker", "exec"]
        for key, value in {**self.env, **(env or {})}.items():
            args += ["-e", f"{key}={value}"]
        args += [self.name, "timeout", "-s", "KILL", str(timeout), "bash", "-c", command]
        start = time.monotonic()
        try:
            result = subprocess.run(args, capture_output=True, timeout=timeout + 30)
        except subprocess.TimeoutExpired as exc:
            raise SandboxError(f"docker exec did not return within {timeout + 30}s") from exc
        duration = time.monotonic() - start
        timed_out = result.returncode in (124, 137) and duration >= timeout - 1
        limit = self.config.output_limit_chars * 4
        stdout = result.stdout.decode("utf-8", "replace")[-limit:]
        stderr = result.stderr.decode("utf-8", "replace")[-limit:]
        if result.returncode == 125 or "No such container" in stderr:
            raise SandboxError(f"docker exec failed: {stderr.strip()}")
        return ExecResult(124 if timed_out else result.returncode, stdout, stderr, timed_out, round(duration, 3))

    def close(self) -> None:
        if not self._closed:
            subprocess.run(["docker", "rm", "-f", self.name], capture_output=True)
            self._closed = True


# -------------------------------------------------------------- factory ----

def resolve_backend(backend: Backend) -> Literal["docker", "local"]:
    if backend == "auto":
        return "docker" if docker_image_present() else "local"
    if backend == "docker" and not docker_available():
        raise SandboxError("backend=docker requested but no Docker daemon is reachable")
    return backend


def node_modules_for(backend: Literal["docker", "local"]) -> str:
    return DockerSandbox.node_modules if backend == "docker" else local_node_modules()


def create_sandbox(workspace_root: Path, backend: Literal["docker", "local"], *,
                   config: SandboxConfig | None = None, env: dict[str, str] | None = None,
                   network: bool = False, extra_ro_binds: list[Path] | None = None) -> Sandbox:
    if backend == "docker":
        return DockerSandbox(workspace_root, config, env, network=network)
    return LocalSandbox(workspace_root, config, env, network=network, extra_ro_binds=extra_ro_binds)


def assert_outside_repo(path: Path) -> None:
    if REPO in Path(path).resolve().parents:
        raise SandboxError(f"workspace {path} must not be inside the repository")
