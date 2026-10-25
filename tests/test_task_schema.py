import copy

import pytest
import yaml
from pydantic import ValidationError

from harness.paths import TASKS
from harness.task import Task, discover_tasks

BASE = yaml.safe_load((TASKS / "bf_001_tax_half_even" / "task.yaml").read_text())


def make(**changes):
    data = copy.deepcopy(BASE)
    for key, value in changes.items():
        data[key] = value
    return Task.model_validate(data)


def test_every_task_loads_and_matches_its_directory():
    tasks = discover_tasks(TASKS)
    assert tasks, "no tasks found"
    assert len({t.id for t in tasks}) == len(tasks)
    for task in tasks:
        assert task.dir.name == task.id


def test_base_example_is_valid():
    assert make().primary.type == "hidden_tests"


@pytest.mark.parametrize(
    "changes",
    [
        {"id": "bug_001_x"},
        {"id": "pr_001_wrong_prefix"},
        {"category": "write_tests"},
        {"difficulty": "trivial"},
        {"rubric": BASE["rubric"][:1]},
        {"rubric": BASE["rubric"] * 2},
        {"flawed": ["flawed/only_one.patch"]},
        {"prompt": "too short"},
        {"negative_checks": ["no_network", "no_network"]},
        {"negative_checks": ["no_such_check"]},
        {"primary": {"type": "hidden_tests", "fail_to_pass": []}},
        {"unknown_field": 1},
    ],
)
def test_invalid_tasks_are_rejected(changes):
    with pytest.raises(ValidationError):
        make(**changes)


def test_auto_rubric_items_need_a_check():
    rubric = copy.deepcopy(BASE["rubric"])
    rubric[1].pop("check")
    with pytest.raises(ValidationError):
        make(rubric=rubric)


def test_write_tests_needs_mutants_and_test_files():
    with pytest.raises(ValidationError):
        make(id="wt_999_x", category="write_tests",
             primary={"type": "mutation", "min_mutant_kill_rate": 0.8, "test_files": ["tests/test_x.py"]})
    task = make(id="wt_999_x", category="write_tests", mutants=["m/a.patch", "m/b.patch", "m/c.patch"],
                primary={"type": "mutation", "min_mutant_kill_rate": 0.8, "test_files": ["tests/test_x.py"]})
    assert task.primary.min_mutant_kill_rate == 0.8


def test_pr_derived_needs_a_source():
    with pytest.raises(ValidationError):
        make(id="pr_999_x", category="pr_derived")


def test_review_defects_need_ordered_lines():
    with pytest.raises(ValidationError):
        make(id="cr_999_x", category="code_review",
             primary={"type": "review_findings", "max_false_positives": 1,
                      "defects": [{"id": "d", "file": "a.py", "lines": [10, 5], "summary": "x"}]})


def test_task_set_spread():
    """The benchmark covers both languages in every category except flaky_test."""
    tasks = discover_tasks(TASKS)
    if len(tasks) < 30:
        pytest.skip("full task set not present")
    by_category = {}
    for t in tasks:
        by_category.setdefault(t.category, set()).add(t.language)
    for category, languages in by_category.items():
        if category != "flaky_test":
            assert languages == {"python", "typescript"}, category
