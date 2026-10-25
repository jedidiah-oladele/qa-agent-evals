"""Grade a diff against a task from the command line (no model involved).

    uv run python -m graders --task bf_001_tax_half_even --diff my_fix.patch
    uv run python -m graders --task bf_001_tax_half_even --diff tasks/bf_001_tax_half_even/reference.patch --judge fake

Prints the primary result, rubric (auto items; judge items only with --judge),
negative checks and the task score as JSON.
"""

from __future__ import annotations

import argparse
import json
import sys
from pathlib import Path

from harness.config import models_config, run_config
from harness.paths import TASKS
from harness.sandbox import resolve_backend
from harness.task import load_task

from .grade import JudgeSetup, grade_submission
from .rubric_judge import FakeJudge, LLMJudge


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    parser.add_argument("--task", required=True)
    parser.add_argument("--diff", type=Path, required=True, help="unified diff relative to the library root")
    parser.add_argument("--judge", choices=["none", "fake", "real"], default="none")
    parser.add_argument("--backend", default="auto", choices=["auto", "docker", "local"])
    args = parser.parse_args(argv)
    task = load_task(TASKS / args.task)
    judges = None
    if args.judge == "fake":
        judges = JudgeSetup(FakeJudge())
    elif args.judge == "real":
        spec = models_config().judge
        judges = JudgeSetup(LLMJudge(spec.primary), spec.primary.pricing)
    result = grade_submission(task, args.diff.read_text(encoding="utf-8"), [], backend=resolve_backend(args.backend),
                              judges=judges, config=run_config())
    print(json.dumps(result.to_dict(), indent=2))
    return 0 if result.score.primary_pass else 1


if __name__ == "__main__":
    sys.exit(main())
