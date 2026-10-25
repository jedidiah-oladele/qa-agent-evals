"""End-to-end dry-run episodes (fake models, real sandbox and graders)."""

from harness.config import models_config, run_config
from harness.run import SHARED_HARNESS, Participant, judges_for, participants, run_one

REQUIRED_FIELDS = {"task_id", "model", "run_index", "primary_pass", "rubric", "negative_checks", "steps", "tokens",
                   "cost_usd", "wall_time_s", "diff"}


def fake(key):
    config = models_config()
    agent = config.agent(key)
    return Participant(agent.key, SHARED_HARNESS, agent)


def run(task, key, run_index=0):
    judges = judges_for(models_config(), run_config(), dry_run=True, skip=False)
    return run_one("test", fake(key), task, run_index, backend="local", run_cfg=run_config(), judges=judges,
                   dry_run=True)


def test_oracle_episode_passes_and_record_has_required_fields(py_task):
    record = run(py_task, "fake-oracle")
    assert REQUIRED_FIELDS <= set(record)
    assert record["primary_pass"] == 1 and record["task_score"] > 0.7
    assert all(c["passed"] for c in record["negative_checks"])
    assert all("rationale" in item for item in record["rubric"])
    assert record["dry_run"] is True and record["sandbox"]["network"] == "none"
    assert "src/shopcore/tax.py" in record["diff"]


def test_cheater_is_caught_and_scores_zero(ts_task):
    record = run(ts_task, "fake-cheater")
    flagged = {c["name"] for c in record["negative_checks"] if not c["passed"]}
    assert {"no_hidden_test_access", "no_skip_or_xfail"} <= flagged
    assert record["task_score"] == 0.0


def test_participants_in_dry_run_are_only_fakes():
    plist = participants(models_config(), dry_run=True, models=None, harnesses="all")
    assert [p.key for p in plist] == ["fake-oracle", "fake-mixed", "fake-cheater"]
    real = participants(models_config(), dry_run=False, models=None, harnesses="all")
    assert {p.model.model_id for p in real} == {"claude-opus-5-5", "claude-sonnet-5-5", "gpt-6-astra"}
    assert {p.harness for p in real} == {"shared-loop", "claude_code", "codex_cli"}


def test_real_run_refuses_without_keys(capsys):
    from harness.run import main

    assert main(["--tasks", "bf_001", "--k", "1", "--yes", "--harnesses", "shared"]) == 2
    assert "missing API keys" in capsys.readouterr().out
