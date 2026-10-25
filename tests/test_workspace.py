import shutil

from graders.diffparse import parse_diff
from harness.paths import REPO
from harness.workspace import build_workspace, copy_hidden_tests, hidden_test_paths


def test_workspace_is_outside_the_repo_and_in_starting_state(py_task):
    with build_workspace(py_task) as ws:
        assert REPO not in ws.root.resolve().parents
        assert "r.quantize(unit)" in (ws.root / "src/shopcore/tax.py").read_text()  # bug applied
        assert (ws.root / ".git").is_dir()  # agent convenience repo
        assert ws.diff() == ""


def test_diff_captures_edits_new_and_deleted_files(py_task):
    with build_workspace(py_task) as ws:
        (ws.root / "src/shopcore/tax.py").write_text("x = 1\n")
        (ws.root / "NOTES.md").write_text("hello\n")
        (ws.root / "tests/test_money.py").unlink()
        (ws.root / "src/shopcore/__pycache__").mkdir(exist_ok=True)
        (ws.root / "src/shopcore/__pycache__/junk.pyc").write_bytes(b"\0")
        files = {f.path: f.status for f in parse_diff(ws.diff())}
        assert files == {"src/shopcore/tax.py": "modified", "NOTES.md": "added", "tests/test_money.py": "deleted"}


def test_deleting_the_agent_git_dir_does_not_hide_changes(py_task):
    with build_workspace(py_task) as ws:
        shutil.rmtree(ws.root / ".git")
        (ws.root / "src/shopcore/tax.py").write_text("x = 2\n")
        assert "src/shopcore/tax.py" in ws.diff()


def test_typescript_workspace_links_node_modules_without_diffing_them(ts_task):
    from harness.sandbox import local_node_modules

    with build_workspace(ts_task, node_modules=local_node_modules()) as ws:
        modules = ws.root / "node_modules"
        assert modules.is_dir() and not modules.is_symlink()
        assert (modules / "vitest").is_symlink()
        assert ws.diff() == ""
        assert not (ws.root / "tests/invoice-void.test.ts").exists()  # removed by setup


def test_hidden_tests_are_only_copied_for_grading(py_task):
    with build_workspace(py_task) as ws:
        for relative in hidden_test_paths(py_task):
            assert not (ws.root / relative).exists()
        copied = copy_hidden_tests(py_task, ws.root)
        assert copied == hidden_test_paths(py_task)
