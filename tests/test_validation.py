"""Validation itself: a good task passes; broken tasks are caught."""

import shutil

from harness.paths import TASKS
from validation.validate_tasks import planted_cheats, validate_task


def test_pilot_tasks_validate():
    for task_id in ("bf_001_tax_half_even", "pr_016_invoice_void"):
        report = validate_task(str(TASKS / task_id), "local")
        assert report.ok, report.errors
        assert report.reference_primary == 1 and set(report.flawed_primary.values()) == {0}
        assert all(report.cheats_caught.values())


def test_planted_cheats_cover_the_required_kinds(py_task):
    kinds = {check for check, _, _ in planted_cheats(py_task).values()}
    assert {"no_test_deletion", "no_skip_or_xfail", "no_hardcoded_expected_values", "no_hidden_test_access",
            "no_network"} <= kinds


def test_a_flawed_patch_that_passes_is_reported(tmp_path):
    clone = tmp_path / "bf_001_tax_half_even"
    shutil.copytree(TASKS / "bf_001_tax_half_even", clone)
    shutil.copy(clone / "reference.patch", clone / "flawed" / "float_round.patch")  # "flawed" == reference
    report = validate_task(str(clone), "local")
    assert not report.ok
    assert any("flawed solution flawed/float_round.patch passes" in e for e in report.errors)


def test_a_reference_that_fails_is_reported(tmp_path):
    clone = tmp_path / "bf_001_tax_half_even"
    shutil.copytree(TASKS / "bf_001_tax_half_even", clone)
    shutil.copy(clone / "flawed" / "round_up.patch", clone / "reference.patch")
    report = validate_task(str(clone), "local")
    assert not report.ok and any("reference does not pass" in e for e in report.errors)
