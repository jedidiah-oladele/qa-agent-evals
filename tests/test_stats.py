import pytest

from analysis.stats import (
    bootstrap,
    cohen_kappa,
    headline_success,
    paired_difference,
    pass_at_1,
    pass_at_k,
    pass_hat,
    pass_hat_k,
    per_task,
)


def test_pass_hat_k_estimator():
    assert pass_hat_k(5, 5, 5) == 1.0
    assert pass_hat_k(4, 5, 5) == 0.0
    assert pass_hat_k(4, 5, 2) == pytest.approx(6 / 10)
    assert pass_at_k(1, 5, 1) == pytest.approx(0.2)
    assert pass_at_k(1, 5, 5) == 1.0
    with pytest.raises(ValueError):
        pass_hat_k(1, 2, 3)


def test_pass_at_1_point_estimate_and_ci():
    clusters = {"a": [1, 1, 1], "b": [0, 0, 0], "c": [1, 0, 1], "d": [1, 1, 0]}
    est = pass_at_1(clusters, samples=2000, seed=1)
    assert est.value == pytest.approx((1 + 0 + 2 / 3 + 2 / 3) / 4)
    assert est.low <= est.value <= est.high and est.n_tasks == 4
    assert pass_at_1(clusters, samples=2000, seed=1) == est  # deterministic for a seed


def test_pass_hat_requires_all_runs_to_pass():
    clusters = {"a": [1, 1, 1], "b": [1, 1, 0]}
    assert pass_hat(clusters, 3, samples=500).value == 0.5


def test_bootstrap_resamples_tasks_not_runs():
    # One task with many runs must not shrink the interval as if runs were independent.
    clusters = {"a": [1] * 100, "b": [0] * 100}
    est = pass_at_1(clusters, samples=2000, seed=0)
    assert est.low == 0.0 and est.high == 1.0


def test_paired_difference():
    a = {"t1": [1, 1], "t2": [1, 0], "t3": [0, 0]}
    b = {"t1": [0, 0], "t2": [1, 0], "t3": [0, 0], "t4": [1, 1]}
    d = paired_difference(a, b, samples=1000)
    assert d.value == pytest.approx(1 / 3) and d.n_tasks == 3


def test_cohen_kappa():
    assert cohen_kappa([("pass", "pass"), ("fail", "fail")]) == 1.0
    assert cohen_kappa([("pass", "fail"), ("fail", "pass")]) == pytest.approx(-1.0)
    assert cohen_kappa([("pass", "error")]) is None


def test_empty_bootstrap():
    assert bootstrap({}, lambda g: 0.0).n_tasks == 0


def _flagged(task_id, primary=1):
    return {
        "task_id": task_id,
        "primary_pass": primary,
        "negative_checks": [{"name": "no_skip_or_xfail", "passed": False, "evidence": ["tests/a.py:3: skip"]}],
    }


def test_detected_cheating_scores_zero_even_when_the_primary_grader_passes():
    """A model that cheats on every run must not get credit for green tests."""
    records = [_flagged(f"t{i}") for i in range(4)]
    headline = pass_at_1(per_task(records, value=headline_success), samples=200, seed=0)
    unflagged = pass_at_1(per_task(records, "primary_pass"), samples=200, seed=0)
    assert headline.value == 0.0
    assert all(headline_success(r) == 0 for r in records)
    assert unflagged.value == 1.0


def test_unflagged_primary_pass_still_counts():
    records = [
        {"task_id": "ok", "primary_pass": 1, "negative_checks": [{"name": "no_network", "passed": True}]},
        _flagged("cheat"),
        {"task_id": "miss", "primary_pass": 0, "negative_checks": []},
    ]
    clusters = per_task(records, value=headline_success)
    assert clusters["ok"] == [1.0]
    assert clusters["cheat"] == [0.0]
    assert clusters["miss"] == [0.0]
    assert pass_hat(clusters, 1, samples=100, seed=0).value == pytest.approx(1 / 3)
