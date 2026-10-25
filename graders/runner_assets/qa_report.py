"""pytest plugin used only by the graders (copied into grading workspaces).

* Records the outcome of every test node id to $QA_REPORT_PATH as JSON.
* With $QA_SHUFFLE_SEED set, shuffles test order deterministically and
  re-seeds :mod:`random` before every test, so "flaky" behaviour that depends
  on ordering or unseeded randomness reproduces exactly for a given seed.

Skips and xfails are recorded as such; graders never count them as passes.
"""

import json
import os
import random

_outcomes = {}
_collection_errors = {}


def pytest_collection_modifyitems(session, config, items):
    seed = os.environ.get("QA_SHUFFLE_SEED")
    if seed is not None:
        random.Random(int(seed)).shuffle(items)


def pytest_runtest_setup(item):
    seed = os.environ.get("QA_SHUFFLE_SEED")
    if seed is not None:
        random.seed(int(seed))


def pytest_collectreport(report):
    if report.failed:
        _collection_errors[report.nodeid or "<session>"] = str(report.longrepr)[-2000:]


def pytest_runtest_logreport(report):
    nodeid = report.nodeid
    current = _outcomes.get(nodeid)
    if hasattr(report, "wasxfail"):
        outcome = "xpassed" if report.passed else "xfailed"
    elif report.when == "call":
        outcome = report.outcome  # passed | failed | skipped
    elif report.failed:
        outcome = "error"
    elif report.skipped:
        outcome = "skipped"
    else:
        return
    if current in ("error", "failed") and outcome == "passed":
        return
    if report.when == "teardown" and report.failed:
        outcome = "error"
    _outcomes[nodeid] = outcome


def pytest_sessionfinish(session, exitstatus):
    path = os.environ.get("QA_REPORT_PATH")
    if not path:
        return
    with open(path, "w", encoding="utf-8") as handle:
        json.dump(
            {"outcomes": _outcomes, "collection_errors": _collection_errors, "exitstatus": int(exitstatus)}, handle
        )
