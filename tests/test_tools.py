import pytest

from harness.config import SandboxConfig
from harness.models import ToolCall
from harness.sandbox import LocalSandbox
from harness.tools import TOOL_SPECS, ToolExecutor


@pytest.fixture
def executor(tmp_path):
    root = tmp_path / "work"
    (root / "src").mkdir(parents=True)
    (root / "src" / "a.py").write_text("\n".join(f"line {i}" for i in range(1, 3001)) + "\n")
    (root / "node_modules").mkdir()
    (root / "node_modules" / "junk.js").write_text("x")
    return ToolExecutor(root, LocalSandbox(root, isolation="none"), SandboxConfig(output_limit_chars=200))


def call(executor, name, **args):
    return executor.execute(ToolCall("id", name, args))


def test_tool_specs_are_the_five_tools():
    assert [t.name for t in TOOL_SPECS] == ["list_files", "read_file", "write_file", "run_command", "submit"]
    for spec in TOOL_SPECS:
        assert spec.parameters["type"] == "object"


def test_list_files_skips_dependency_dirs(executor):
    out = call(executor, "list_files", path=".")
    assert "src/a.py" in out.content and "node_modules" not in out.content


def test_read_file_numbers_lines_and_pages(executor):
    out = call(executor, "read_file", path="src/a.py", start_line=10, end_line=12)
    assert out.content.splitlines()[0].strip() == "10| line 10"
    assert "[lines 10-12 of 3000]" in out.content
    whole = call(executor, "read_file", path="src/a.py")
    assert "[lines 1-2000 of 3000]" in whole.content


def test_write_creates_directories(executor):
    out = call(executor, "write_file", path="pkg/new/mod.py", content="x = 1\n")
    assert not out.is_error
    assert (executor.root / "pkg/new/mod.py").read_text() == "x = 1\n"


def test_run_command_reports_exit_code_and_truncates(executor):
    out = call(executor, "run_command", command="seq 1 5000; exit 4")
    assert out.is_error and out.content.startswith("exit code 4")
    assert "truncated" in out.content and out.content.rstrip().endswith("5000")


def test_run_command_timeout_is_capped(executor):
    executor.config = SandboxConfig(command_timeout_s=1)
    out = call(executor, "run_command", command="sleep 5", timeout_s=999)
    assert "timeout" in out.content


def test_submit_records_summary(executor):
    out = call(executor, "submit", summary="done")
    assert out.submitted and executor.submit_summary == "done"


def test_bad_calls_are_errors_not_crashes(executor):
    assert call(executor, "rm_rf").is_error
    assert call(executor, "read_file").is_error  # missing argument
    assert call(executor, "read_file", path="missing.py").is_error
    assert executor.execute(ToolCall("id", "write_file", {"__invalid_json__": "{"})).is_error


def test_sandbox_workdir_prefix_is_accepted(tmp_path):
    root = tmp_path / "work"
    root.mkdir()
    (root / "f.txt").write_text("ok")

    class FakeSandbox:
        workdir = "/work"

    executor = ToolExecutor(root, FakeSandbox())
    assert "ok" in call(executor, "read_file", path="/work/f.txt").content
