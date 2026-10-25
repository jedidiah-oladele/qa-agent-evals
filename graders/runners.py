"""Run a target test suite inside a sandbox and parse per-test outcomes.

Test ids:
  python      ``tests/test_tax.py::test_rounding[0.125]``  (pytest node ids)
  typescript  ``tests/billing.test.ts > prorate > rounds half-up``
"""

from __future__ import annotations

import json
import shlex
import shutil
from dataclasses import dataclass, field
from pathlib import Path

from harness.sandbox import Sandbox

ASSETS = Path(__file__).resolve().parent / "runner_assets"
GRADER_DIR = ".qa_grader"
PASSING = {"passed"}


@dataclass
class TestReport:
    outcomes: dict[str, str] = field(default_factory=dict)
    collection_errors: dict[str, str] = field(default_factory=dict)
    exit_code: int = 0
    timed_out: bool = False
    output_tail: str = ""
    duration_s: float = 0.0
    runner_error: str | None = None

    def passed(self, test_id: str) -> bool:
        return self.outcomes.get(test_id) in PASSING

    @property
    def failing(self) -> list[str]:
        return sorted(t for t, o in self.outcomes.items() if o not in PASSING and o != "skipped")

    @property
    def all_green(self) -> bool:
        return (
            not self.timed_out
            and self.runner_error is None
            and not self.collection_errors
            and bool(self.outcomes)
            and all(o in PASSING for o in self.outcomes.values())
        )

    def summary(self) -> dict:
        counts: dict[str, int] = {}
        for outcome in self.outcomes.values():
            counts[outcome] = counts.get(outcome, 0) + 1
        return {
            "counts": counts,
            "collection_errors": sorted(self.collection_errors),
            "timed_out": self.timed_out,
            "runner_error": self.runner_error,
            "exit_code": self.exit_code,
        }


def _prepare(workspace_root: Path) -> Path:
    grader_dir = workspace_root / GRADER_DIR
    grader_dir.mkdir(exist_ok=True)
    shutil.copy(ASSETS / "qa_report.py", grader_dir / "qa_report.py")
    report = grader_dir / "report.json"
    if report.exists():
        report.unlink()
    return report


def run_pytest(
    sandbox: Sandbox,
    *,
    paths: list[str] | None = None,
    shuffle_seed: int | None = None,
    env: dict[str, str] | None = None,
    timeout_s: int = 600,
) -> TestReport:
    report_path = _prepare(sandbox.workspace_root)
    targets = " ".join(shlex.quote(p) for p in (paths or []))
    command = (f"python -m pytest -p qa_report -p no:cacheprovider -q -o addopts='' --tb=short -rN {targets}").strip()
    run_env = {"PYTHONPATH": f"{GRADER_DIR}", "QA_REPORT_PATH": f"{GRADER_DIR}/report.json", **(env or {})}
    if shuffle_seed is not None:
        run_env["QA_SHUFFLE_SEED"] = str(shuffle_seed)
    result = sandbox.exec(command, timeout_s=timeout_s, env=run_env)
    report = TestReport(
        exit_code=result.exit_code,
        timed_out=result.timed_out,
        output_tail=result.output[-4000:],
        duration_s=result.duration_s,
    )
    if report_path.exists():
        data = json.loads(report_path.read_text())
        report.outcomes = data.get("outcomes", {})
        report.collection_errors = data.get("collection_errors", {})
    elif not result.timed_out:
        report.runner_error = "pytest produced no report (crashed before session finish)"
    return report


def _vitest_id(file_name: str, ancestors: list[str], title: str, workdir: str) -> str:
    relative = file_name
    for prefix in (workdir.rstrip("/") + "/", "/work/"):
        if relative.startswith(prefix):
            relative = relative[len(prefix) :]
            break
    return " > ".join([relative, *ancestors, title])


def parse_vitest_json(data: dict, workdir: str) -> tuple[dict[str, str], dict[str, str]]:
    outcomes: dict[str, str] = {}
    errors: dict[str, str] = {}
    status_map = {
        "passed": "passed",
        "failed": "failed",
        "skipped": "skipped",
        "pending": "skipped",
        "todo": "skipped",
        "disabled": "skipped",
    }
    for suite in data.get("testResults", []):
        name = suite.get("name", "")
        assertions = suite.get("assertionResults", [])
        if suite.get("status") == "failed" and not assertions:
            relative = _vitest_id(name, [], "", workdir).rstrip(" >")
            errors[relative] = (suite.get("message") or "suite failed to load")[-2000:]
        for test in assertions:
            test_id = _vitest_id(name, list(test.get("ancestorTitles", [])), test.get("title", ""), workdir)
            outcomes[test_id] = status_map.get(test.get("status", "failed"), "failed")
    return outcomes, errors


def run_vitest(
    sandbox: Sandbox,
    *,
    paths: list[str] | None = None,
    shuffle_seed: int | None = None,
    env: dict[str, str] | None = None,
    timeout_s: int = 600,
) -> TestReport:
    report_path = _prepare(sandbox.workspace_root)
    targets = " ".join(shlex.quote(p) for p in (paths or []))
    shuffle = f"--sequence.shuffle --sequence.seed={shuffle_seed}" if shuffle_seed is not None else ""
    command = (
        f"node_modules/.bin/vitest run --reporter=json --outputFile={GRADER_DIR}/report.json "
        f"--no-color --passWithNoTests=false {shuffle} {targets}"
    ).strip()
    result = sandbox.exec(command, timeout_s=timeout_s, env=env or {})
    report = TestReport(
        exit_code=result.exit_code,
        timed_out=result.timed_out,
        output_tail=result.output[-4000:],
        duration_s=result.duration_s,
    )
    if report_path.exists():
        try:
            data = json.loads(report_path.read_text())
        except json.JSONDecodeError as exc:
            report.runner_error = f"unreadable vitest report: {exc}"
            return report
        report.outcomes, report.collection_errors = parse_vitest_json(data, sandbox.workdir)
        if data.get("numFailedTestSuites") and not report.collection_errors and not report.failing:
            report.collection_errors["<suite>"] = "a test suite failed outside any test (e.g. unhandled error)"
        if result.exit_code != 0 and not report.failing and not report.collection_errors:
            report.collection_errors["<run>"] = (
                "vitest exited non-zero with no failing test (unhandled errors or rejections during the run)"
            )
    elif not result.timed_out:
        report.runner_error = "vitest produced no report"
    return report


def run_tests(sandbox: Sandbox, language: str, **kwargs) -> TestReport:
    runner = run_pytest if language == "python" else run_vitest
    return runner(sandbox, **kwargs)
