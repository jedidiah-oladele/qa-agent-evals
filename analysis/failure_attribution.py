"""Label every failed run as an agent, environment or grader error, with evidence.

A run *failed* when ``primary_pass == 0`` or any negative check fired. The
label answers "whose fault is this?", which is what decides whether a task,
the infrastructure or the model needs attention:

* ``environment`` - the infrastructure failed: sandbox/Docker errors, provider
  API failures (rate limits, auth, outages) after retries, test runner crashes
  unrelated to the submission, CLI harness problems.
* ``grader``      - the grading machinery failed or is suspect: a grader raised,
  the judge reply was unparseable, the task failed its last validation, or a
  required test id did not exist while the suite ran cleanly.
* ``agent``       - everything else: the submission was wrong, incomplete or
  gamed the grader (with the specific reason: failing tests, step limit, no
  changes, missed review findings, low mutant kill rate, cheating flags...).

Rules are checked in that order, so an agent is never blamed for an
infrastructure or grader fault.
"""

from __future__ import annotations

import json
from dataclasses import dataclass
from functools import lru_cache
from pathlib import Path

from harness.paths import REPO

VALIDATION_JSON = REPO / "validation" / "report.json"


@dataclass(frozen=True)
class Attribution:
    label: str  # agent | environment | grader
    reason: str
    evidence: str


@lru_cache
def invalid_tasks(path: Path = VALIDATION_JSON) -> frozenset[str]:
    if not path.exists():
        return frozenset()
    return frozenset(r["task_id"] for r in json.loads(path.read_text()) if not r.get("ok", True))


def failed(record: dict) -> bool:
    if record.get("status") == "skipped":
        return False
    cheats = [c for c in record.get("negative_checks", []) if not c.get("passed", True)]
    return not record.get("primary_pass") or bool(cheats)


def _first(items, n: int = 3) -> str:
    items = list(items)
    more = f" (+{len(items) - n} more)" if len(items) > n else ""
    return ", ".join(map(str, items[:n])) + more


def attribute(record: dict, invalid: frozenset[str] | None = None) -> Attribution | None:
    if not failed(record):
        return None
    invalid = invalid_tasks() if invalid is None else invalid
    primary = record.get("primary") or {}
    details = primary.get("details") or {}
    suite = details.get("suite") or {}

    # -- environment --------------------------------------------------------
    if record.get("status") == "error" and record.get("error_kind") in ("environment", "harness"):
        return Attribution("environment", f"run crashed ({record.get('error_kind')})", str(record.get("error"))[:300])
    if record.get("stop_reason") == "model_error" and record.get("error_kind") == "environment":
        return Attribution("environment", "provider API failed after retries", str(record.get("error"))[:300])
    if primary.get("environment_error"):
        return Attribution("environment", "sandbox failed during grading", str(primary["environment_error"])[:300])
    tail = str(details.get("output_tail", ""))
    for marker in (
        "No module named pytest",
        "vitest: not found",
        "Cannot find module 'vitest",
        "ENOSPC",
        "Killed",
        "bwrap:",
    ):
        if marker in tail and not record.get("diff"):
            return Attribution("environment", "test runner could not start", marker)

    # -- grader ---------------------------------------------------------------
    if primary.get("grader_error"):
        return Attribution("grader", "grader raised an error", str(primary["grader_error"])[:300])
    if record["task_id"] in invalid:
        return Attribution("grader", "task failed its latest validation run", "validation/report.json")
    f2p = details.get("fail_to_pass") or {}
    missing = [t for t, o in f2p.items() if o == "missing"]
    if missing and not suite.get("collection_errors") and not suite.get("runner_error"):
        return Attribution("grader", "required test ids were not collected", _first(missing))
    judge_errors = [r["id"] for r in record.get("rubric", []) if r.get("verdict") == "error"]
    if (
        judge_errors
        and record.get("primary_pass")
        and not any(not c.get("passed", True) for c in record.get("negative_checks", []))
    ):
        return Attribution("grader", "judge or auto check errored", _first(judge_errors))

    # -- agent ----------------------------------------------------------------
    flags = [c for c in record.get("negative_checks", []) if not c.get("passed", True)]
    if flags:
        evidence = "; ".join(f"{c['name']}: {(c.get('evidence') or [''])[0]}" for c in flags)
        return Attribution("agent", "gamed or bypassed the grader (negative check fired)", evidence[:400])
    stop = record.get("stop_reason")
    if stop in ("max_steps", "timeout", "no_tool_calls", "refusal") and not record.get("diff"):
        return Attribution("agent", f"stopped without a solution ({stop})", f"steps={record.get('steps')}")
    if record.get("stop_reason") == "model_error":
        return Attribution("agent", "model produced an invalid request", str(record.get("error"))[:300])
    if not record.get("diff", "").strip():
        return Attribution("agent", "submitted no changes", f"stop_reason={stop}, steps={record.get('steps')}")
    kind = primary.get("type")
    if kind == "hidden_tests":
        failing = [t for t, o in f2p.items() if o != "passed"]
        p2p = (details.get("pass_to_pass") or {}).get("failures") or {}
        if suite.get("collection_errors"):
            return Attribution("agent", "submission breaks test collection", _first(suite["collection_errors"]))
        if failing:
            return Attribution("agent", "behaviour still wrong (fail_to_pass tests fail)", _first(failing))
        if p2p:
            return Attribution("agent", "fix broke existing behaviour (pass_to_pass tests fail)", _first(p2p))
    if kind == "mutation":
        if details.get("reason"):
            return Attribution("agent", "tests unusable", details["reason"])
        return Attribution(
            "agent", "tests too weak", f"kill rate {details.get('kill_rate')} < {details.get('required')}"
        )
    if kind == "repeated_runs":
        return Attribution(
            "agent",
            "suite still flaky",
            f"{details.get('failed_runs')}/{details.get('runs')} runs "
            f"failed: {_first((details.get('failures') or [{}])[0].get('failing', []))}",
        )
    if kind == "review_findings":
        if details.get("reason"):
            return Attribution("agent", "no review written", details["reason"])
        if details.get("missed"):
            return Attribution("agent", "review missed seeded defects", _first(details["missed"]))
        return Attribution(
            "agent", "review invented too many defects", f"{len(details.get('false_positives', []))} unmatched findings"
        )
    return Attribution("agent", f"primary grader failed ({kind})", f"stop_reason={stop}")
