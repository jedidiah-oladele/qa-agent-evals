"""The target libraries' commit history rebuilds exactly, and every commit is green."""

import subprocess

import pytest

from harness.paths import TARGET
from tools.rebuild_history import commits, pr_commit, rebuild, tree_differences


@pytest.mark.parametrize("lib", ["shopcore", "ledgerkit"])
def test_history_rebuilds_to_the_target_tree(lib, tmp_path):
    dest = rebuild(lib, tmp_path / lib)
    assert tree_differences(dest, TARGET / lib) == []
    log = subprocess.run(["git", "log", "--format=%an|%s"], cwd=dest, capture_output=True, text=True).stdout
    assert len(log.splitlines()) == len(commits(lib))
    assert all(line.startswith("Jedidiah Oladele|") for line in log.splitlines())


def test_pr_commits_are_discoverable():
    assert pr_commit("shopcore", 15).subject.startswith("Reuse one idempotency key")
    assert pr_commit("ledgerkit", 27).subject.startswith("Prorate mid-period plan changes")
    with pytest.raises(KeyError):
        pr_commit("ledgerkit", 999)


@pytest.mark.slow
def test_every_shopcore_commit_passes_its_suite(tmp_path):
    dest = rebuild("shopcore", tmp_path / "shopcore")
    shas = subprocess.run(["git", "rev-list", "--reverse", "HEAD"], cwd=dest, capture_output=True,
                          text=True).stdout.split()
    for sha in shas:
        subprocess.run(["git", "checkout", "-q", sha], cwd=dest, check=True)
        result = subprocess.run(["python", "-m", "pytest", "-q", "-p", "no:cacheprovider"], cwd=dest,
                                capture_output=True, text=True)
        assert result.returncode == 0, f"{sha}: {result.stdout[-500:]}"


@pytest.mark.slow
def test_every_ledgerkit_commit_passes_its_suite(tmp_path):
    from harness.workspace import link_node_modules

    dest = rebuild("ledgerkit", tmp_path / "ledgerkit")
    link_node_modules(dest, str((TARGET / "ledgerkit" / "node_modules").resolve()))
    (dest / ".git" / "info" / "exclude").write_text("node_modules\n")
    shas = subprocess.run(["git", "rev-list", "--reverse", "HEAD"], cwd=dest, capture_output=True,
                          text=True).stdout.split()
    for sha in shas:
        subprocess.run(["git", "checkout", "-q", sha], cwd=dest, check=True)
        result = subprocess.run(["node_modules/.bin/vitest", "run"], cwd=dest, capture_output=True, text=True)
        assert result.returncode == 0, f"{sha}: {result.stdout[-500:]}"
