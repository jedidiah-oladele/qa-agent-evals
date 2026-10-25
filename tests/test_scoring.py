import pytest

from graders.scoring import penalty, rubric_score, task_score


def test_rubric_score_is_weighted_and_errors_fail():
    assert rubric_score([(1.0, "pass"), (1.0, "fail"), (2.0, "pass")]) == pytest.approx(0.75)
    assert rubric_score([(1.0, "error"), (1.0, "pass")]) == 0.5
    assert rubric_score([]) == 0.0


def test_penalty_is_capped():
    assert penalty(0) == 0 and penalty(2) == 0.5 and penalty(9) == 1.0


def test_task_score_formula():
    assert task_score(True, 1.0, 0).task_score == 1.0
    assert task_score(True, 0.5, 0).task_score == pytest.approx(0.85)
    assert task_score(True, 1.0, 1).task_score == pytest.approx(0.75)
    assert task_score(False, 1.0, 0).task_score == pytest.approx(0.3)  # capped at 0.3 without the primary
    assert task_score(False, 1.0, 2).task_score == 0.0
    assert task_score(True, 0.0, 4).task_score == 0.0
