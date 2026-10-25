import csv
import json

from analysis.report import main as report_main


def make_record(participant, task, run, passed, category="bug_fix", language="python", dry=False, cost=0.1, **kw):
    record = {
        "run_id": "run-test", "dry_run": dry, "task_id": task, "category": category, "language": language,
        "difficulty": "easy", "model": participant, "participant": participant, "harness": "shared-loop",
        "provider": "anthropic", "run_index": run, "status": "ok", "primary_pass": int(passed),
        "task_score": 1.0 if passed else 0.0, "rubric_score": 1.0 if passed else 0.0, "penalty": 0.0,
        "steps": 10, "cost_usd": cost, "judge_cost_usd": 0.01, "negative_checks": [],
        "rubric": [{"id": "r", "grader": "judge", "weight": 1, "verdict": "pass" if passed else "fail",
                    "rationale": "because", "judge_model": "j",
                    "cross_check": {"verdict": "pass" if passed else "fail"}}],
        "diff": "" if not passed and run == 0 else "diff --git a/src/x.py b/src/x.py\n+++ b/src/x.py\n+x = 1\n",
        "stop_reason": "submitted",
        "primary": {"type": "hidden_tests", "details": {"fail_to_pass": {"t": "passed" if passed else "failed"},
                                                         "suite": {}, "pass_to_pass": {"failures": {}}}},
        "harness_commit": "abc123",
    }
    record.update(kw)
    return record


def write(path, records):
    path.write_text("".join(json.dumps(r) + "\n" for r in records))


def test_report_numbers_come_from_runs(tmp_path):
    records = []
    for t in range(6):
        for run in range(3):
            records.append(make_record("model-a", f"bf_00{t}_x", run, passed=t < 3,
                                       category=["bug_fix", "code_review"][t % 2],
                                       language=["python", "typescript"][t % 2]))
            records.append(make_record("model-b", f"bf_00{t}_x", run, passed=(t == 0 and run < 2)))
    runs = tmp_path / "runs.jsonl"
    write(runs, records)
    out = tmp_path / "results.md"
    assert report_main(["--runs", str(runs), "--out", str(out)]) == 0
    text = out.read_text()
    assert "DRY RUN" not in text
    assert "| `model-a` | shared-loop | 18 | 50.0%" in text
    assert "pass^3" in text and "Pairwise differences" in text
    assert "## Failure case studies" in text and text.count("### Case ") >= 5
    assert "raw agreement **100.0%**" in text
    assert (tmp_path / "charts" / "pass_at_1.png").stat().st_size > 1000
    rows = list(csv.DictReader(open(tmp_path / "summary.csv")))
    overall = [r for r in rows if r["participant"] == "model-a" and r["slice"] == "overall"][0]
    assert float(overall["pass_at_1"]) == 0.5 and float(overall["mean_cost_usd"]) == 0.1


def test_dry_runs_are_labelled_and_excluded_once_real_runs_exist(tmp_path):
    dry = tmp_path / "dry.jsonl"
    write(dry, [make_record("fake-oracle", "bf_001_x", 0, True, dry=True)])
    out = tmp_path / "results.md"
    report_main(["--runs", str(dry), "--out", str(out), "--no-charts"])
    assert "DRY RUN: these numbers come from scripted fake models" in out.read_text()
    real = tmp_path / "real.jsonl"
    write(real, [make_record("model-a", "bf_001_x", 0, True)])
    report_main(["--runs", str(dry), str(real), "--out", str(out), "--no-charts"])
    text = out.read_text()
    assert "DRY RUN" not in text and "fake-oracle" not in text and "model-a" in text


def test_unknown_costs_are_shown_as_na(tmp_path):
    runs = tmp_path / "r.jsonl"
    write(runs, [make_record("m", "bf_001_x", 0, True, cost=None)])
    out = tmp_path / "results.md"
    report_main(["--runs", str(runs), "--out", str(out), "--no-charts"])
    assert "n/a" in out.read_text()


def test_skipped_participants_are_reported_but_not_scored(tmp_path):
    runs = tmp_path / "r.jsonl"
    skipped = make_record("claude-code/x", "bf_001_x", 0, False, status="skipped", error="`claude` CLI not found")
    write(runs, [make_record("m", "bf_001_x", 0, True), skipped])
    out = tmp_path / "results.md"
    report_main(["--runs", str(runs), "--out", str(out), "--no-charts"])
    text = out.read_text()
    assert "Skipped participants" in text and "| `claude-code/x`" not in text
