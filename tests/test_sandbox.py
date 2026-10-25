import subprocess

import pytest

from harness.config import SandboxConfig
from harness.sandbox import (
    DockerSandbox,
    LocalSandbox,
    SandboxError,
    bwrap_available,
    docker_available,
    docker_image_present,
    docker_run_args,
    resolve_backend,
)
from harness.workspace import build_workspace


@pytest.fixture
def workspace(tmp_path):
    root = tmp_path / "work"
    root.mkdir()
    (root / "hello.txt").write_text("hi\n")
    return root


@pytest.mark.parametrize(
    "isolation",
    ["none", pytest.param("bwrap", marks=pytest.mark.skipif(not bwrap_available(), reason="bubblewrap not usable"))],
)
def test_local_exec_basics(workspace, isolation):
    sandbox = LocalSandbox(workspace, isolation=isolation)
    result = sandbox.exec("cat hello.txt && echo err >&2 && exit 3", timeout_s=20)
    assert result.exit_code == 3
    assert "hi" in result.stdout and "err" in result.stderr
    assert sandbox.exec("echo new > made.txt", timeout_s=20).exit_code == 0
    assert (workspace / "made.txt").read_text() == "new\n"


def test_local_exec_timeout_kills_the_process_group(workspace):
    sandbox = LocalSandbox(workspace, isolation="none")
    result = sandbox.exec("sleep 30 & sleep 30", timeout_s=1)
    assert result.timed_out and result.exit_code == 124
    assert result.duration_s < 10


def test_output_is_truncated_from_the_front(workspace):
    sandbox = LocalSandbox(workspace, SandboxConfig(output_limit_chars=100), isolation="none")
    result = sandbox.exec("seq 1 100000", timeout_s=30)
    assert "truncated" in result.stdout and result.stdout.rstrip().endswith("100000")


def test_environment_is_scrubbed(workspace, monkeypatch):
    monkeypatch.setenv("SECRET_TOKEN", "do-not-leak")
    sandbox = LocalSandbox(workspace, isolation="none")
    assert "do-not-leak" not in sandbox.exec("env", timeout_s=20).stdout


@pytest.mark.skipif(not bwrap_available(), reason="bubblewrap not usable")
def test_bwrap_sees_only_the_workspace_and_toolchains(workspace):
    sandbox = LocalSandbox(workspace, isolation="bwrap")
    assert sandbox.workdir == "/work"
    listing = sandbox.exec("ls /home /root 2>&1; ls /work", timeout_s=20).output
    assert "hello.txt" in listing
    assert sandbox.exec("python -c 'import pytest' && node --version", timeout_s=30).exit_code == 0


def test_pytest_and_vitest_run_in_the_sandbox(py_task, ts_task):
    from graders.runners import run_tests
    from harness.sandbox import local_node_modules

    with build_workspace(py_task) as ws:
        report = run_tests(LocalSandbox(ws.root), "python", paths=["tests/test_money.py"], timeout_s=120)
        assert report.all_green and len(report.outcomes) > 10
    with build_workspace(ts_task, node_modules=local_node_modules()) as ws:
        report = run_tests(LocalSandbox(ws.root), "typescript", paths=["tests/money.test.ts"], timeout_s=180)
        assert report.all_green and len(report.outcomes) > 10


def test_docker_run_args_enforce_isolation(tmp_path):
    args = docker_run_args("c1", tmp_path, SandboxConfig(cpus=1.5, memory_mb=1024, pids=128), network=False)
    joined = " ".join(args)
    assert "--network none" in joined
    assert "--cpus 1.5" in joined and "--memory 1024m" in joined and "--pids-limit 128" in joined
    assert "--cap-drop ALL" in joined and "--read-only" in joined and "no-new-privileges" in joined
    mounts = [args[i + 1] for i, a in enumerate(args) if a == "-v"]
    assert mounts == [f"{tmp_path}:/work:rw"], "only the workspace may be mounted"
    assert "--network bridge" in " ".join(docker_run_args("c2", tmp_path, SandboxConfig(), network=True))


def test_backend_resolution_without_docker(monkeypatch):
    if docker_available():
        pytest.skip("Docker is available here")
    assert resolve_backend("auto") == "local"
    with pytest.raises(SandboxError):
        resolve_backend("docker")


needs_docker = pytest.mark.skipif(not docker_image_present(), reason="Docker daemon or sandbox image not available")


@pytest.mark.docker
@needs_docker
def test_docker_sandbox_isolation(py_task):
    with build_workspace(py_task) as ws:
        sandbox = DockerSandbox(ws.root)
        try:
            assert sandbox.exec("cat src/shopcore/tax.py | head -1", timeout_s=60).exit_code == 0
            hidden = next(py_task.hidden_tests_dir.rglob("*.py"))
            leak = sandbox.exec(f"cat {hidden}", timeout_s=30)
            assert leak.exit_code != 0
            net = sandbox.exec(
                "python -c \"import socket; socket.create_connection(('1.1.1.1', 53), timeout=3)\"", timeout_s=30
            )
            assert net.exit_code != 0
            assert sandbox.exec("sleep 20", timeout_s=2).timed_out
        finally:
            sandbox.close()
        names = subprocess.run(["docker", "ps", "-a", "--format", "{{.Names}}"], capture_output=True, text=True)
        assert sandbox.name not in names.stdout


@pytest.mark.docker
@needs_docker
def test_docker_runs_both_test_suites(py_task, ts_task):
    from graders.runners import run_tests
    from harness.sandbox import node_modules_for

    with build_workspace(py_task) as ws:
        with DockerSandbox(ws.root) as sandbox:
            assert run_tests(sandbox, "python", paths=["tests/test_money.py"]).all_green
    with build_workspace(ts_task, node_modules=node_modules_for("docker")) as ws:
        with DockerSandbox(ws.root) as sandbox:
            assert run_tests(sandbox, "typescript", paths=["tests/money.test.ts"]).all_green
