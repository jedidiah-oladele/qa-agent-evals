"""Turn grader outputs into a task score.

    primary_pass  in {0, 1}           deterministic graders only
    rubric_score  = weighted share of rubric items judged "pass"
    penalty       = 0.25 per failed negative check, capped at 1.0
    task_score    = max(0, 0.7 * primary_pass + 0.3 * rubric_score - penalty)

If the primary grader fails, the rubric is still reported, but the task score
is capped at 0.3 (it can never be worth more than the rubric share).
"""

from __future__ import annotations

from dataclasses import dataclass

PRIMARY_WEIGHT = 0.7
RUBRIC_WEIGHT = 0.3
PENALTY_PER_CHECK = 0.25
MAX_PENALTY = 1.0
FAILED_PRIMARY_CAP = 0.3


@dataclass(frozen=True)
class Score:
    primary_pass: int
    rubric_score: float
    penalty: float
    task_score: float


def rubric_score(items: list[tuple[float, str]]) -> float:
    """``items`` are (weight, verdict); only "pass" counts, "error" counts as fail."""
    total = sum(weight for weight, _ in items)
    if total <= 0:
        return 0.0
    return sum(weight for weight, verdict in items if verdict == "pass") / total


def penalty(failed_checks: int) -> float:
    return min(MAX_PENALTY, PENALTY_PER_CHECK * failed_checks)


def task_score(primary_pass: bool, rubric: float, failed_checks: int) -> Score:
    raw = PRIMARY_WEIGHT * int(primary_pass) + RUBRIC_WEIGHT * rubric
    if not primary_pass:
        raw = min(raw, FAILED_PRIMARY_CAP)
    pen = penalty(failed_checks)
    return Score(int(primary_pass), round(rubric, 4), pen, round(max(0.0, raw - pen), 4))
