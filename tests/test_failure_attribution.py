from analysis.failure_attribution import attribute, failed

OK_CHECKS = [{"name": "no_network", "passed": True, "evidence": []}]


def record(**kw):
    base = {"task_id": "bf_001_tax_half_even", "status": "ok", "primary_pass": 0, "negative_checks": OK_CHECKS,
            "rubric": [], "diff": "diff --git a/x b/x\n", "stop_reason": "submitted", "steps": 5,
            "primary": {"type": "hidden_tests", "details": {"fail_to_pass": {"t1": "failed"}, "suite": {},
                                                             "pass_to_pass": {"failures": {}}}}}
    base.update(kw)
    return base


def label(r):
    a = attribute(r, invalid=frozenset())
    return a.label if a else None


def test_passing_runs_are_not_failures():
    assert not failed(record(primary_pass=1))
    assert label(record(primary_pass=1)) is None


def test_environment_errors():
    assert label(record(status="error", error_kind="environment", error="SandboxError: docker run failed")) \
        == "environment"
    assert label(record(stop_reason="model_error", error_kind="environment", error="529")) == "environment"
    assert label(record(primary={"type": "hidden_tests", "environment_error": "bwrap failed", "details": {}})) \
        == "environment"


def test_grader_errors():
    assert label(record(primary={"type": "hidden_tests", "grader_error": "mutant did not apply", "details": {}})) \
        == "grader"
    missing = record(primary={"type": "hidden_tests", "details": {"fail_to_pass": {"t1": "missing"}, "suite": {}}})
    assert label(missing) == "grader"
    assert attribute(record(), invalid=frozenset({"bf_001_tax_half_even"})).label == "grader"


def test_agent_errors_have_specific_reasons():
    assert attribute(record(), invalid=frozenset()).reason.startswith("behaviour still wrong")
    assert attribute(record(diff=""), invalid=frozenset()).reason == "submitted no changes"
    cheat = record(primary_pass=1, negative_checks=[{"name": "no_skip_or_xfail", "passed": False,
                                                      "evidence": ["tests/a.py:3: skip"]}])
    a = attribute(cheat, invalid=frozenset())
    assert a.label == "agent" and "no_skip_or_xfail" in a.evidence
    flaky = record(primary={"type": "repeated_runs", "details": {"runs": 20, "failed_runs": 3,
                                                                  "failures": [{"failing": ["t"]}]}})
    assert "3/20" in attribute(flaky, invalid=frozenset()).evidence
    review = record(primary={"type": "review_findings", "details": {"missed": ["leak"], "false_positives": []}})
    assert attribute(review, invalid=frozenset()).reason == "review missed seeded defects"


def test_skipped_runs_are_ignored():
    assert attribute(record(status="skipped"), invalid=frozenset()) is None
