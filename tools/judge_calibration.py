"""Judge calibration against my hand grades.

    uv run python -m tools.judge_calibration sample --runs results/runs/run-*.jsonl --n 36
        Picks >= 30 judged rubric items, stratified across categories and models
        (round-robin), and writes docs/judge_calibration.csv with an empty
        `human_verdict` column. Model names are kept in a separate column the
        grader should hide while grading (sort by item_id, grade, then reveal).
    uv run python -m tools.judge_calibration score
        Reads the filled CSV and writes agreement statistics (overall, by
        category, by model, Cohen's kappa) into docs/judge_calibration.md
        between the RESULTS markers.

I fill `human_verdict` with pass/fail by reading the task prompt,
criterion, diff and TRIAGE.md/REVIEW.md (the same evidence the judge saw).
Nothing in this tool invents a human grade: unfilled rows are excluded.
"""

from __future__ import annotations

import argparse
import csv
import hashlib
import json
import sys
from collections import defaultdict
from pathlib import Path

from analysis.stats import cohen_kappa
from harness.paths import REPO

CSV_PATH = REPO / "docs" / "judge_calibration.csv"
DOC_PATH = REPO / "docs" / "judge_calibration.md"
START, END = "<!-- RESULTS:START -->", "<!-- RESULTS:END -->"
FIELDS = [
    "item_id",
    "task_id",
    "category",
    "participant",
    "run_index",
    "rubric_item",
    "criterion",
    "judge_model",
    "judge_verdict",
    "judge_rationale",
    "human_verdict",
    "human_note",
]


def sample(paths: list[Path], n: int, seed: int) -> int:
    from harness.paths import TASKS
    from harness.task import load_task

    pool: dict[tuple[str, str], list[dict]] = defaultdict(list)
    for path in paths:
        for line in path.read_text().splitlines():
            if not line.strip():
                continue
            r = json.loads(line)
            if r.get("dry_run"):
                continue
            for item in r.get("rubric", []):
                if item.get("grader") == "judge" and item.get("verdict") in ("pass", "fail"):
                    pool[(r["category"], r["participant"])].append({"record": r, "item": item})
    if not pool:
        print("no judged rubric items from real runs; calibration needs a real run first")
        return 1
    for key in pool:
        pool[key].sort(
            key=lambda x: hashlib.sha256(
                f"{seed}:{x['record']['task_id']}:{x['record']['run_index']}:{x['item']['id']}".encode()
            ).hexdigest()
        )
    rows, keys = [], sorted(pool)
    while len(rows) < n and any(pool.values()):
        for key in keys:
            if pool[key] and len(rows) < n:
                entry = pool[key].pop()
                r, item = entry["record"], entry["item"]
                criterion = next(
                    (i.criterion for i in load_task(TASKS / r["task_id"]).rubric if i.id == item["id"]), ""
                )
                rows.append(
                    {
                        "item_id": f"C{len(rows) + 1:03d}",
                        "task_id": r["task_id"],
                        "category": r["category"],
                        "participant": r["participant"],
                        "run_index": r["run_index"],
                        "rubric_item": item["id"],
                        "criterion": " ".join(criterion.split()),
                        "judge_model": item.get("judge_model"),
                        "judge_verdict": item["verdict"],
                        "judge_rationale": item.get("rationale", ""),
                        "human_verdict": "",
                        "human_note": "",
                    }
                )
    with open(CSV_PATH, "w", newline="", encoding="utf-8") as handle:
        writer = csv.DictWriter(handle, FIELDS)
        writer.writeheader()
        writer.writerows(rows)
    print(f"wrote {len(rows)} items to {CSV_PATH.relative_to(REPO)}; fill in human_verdict (pass/fail)")
    return 0


def score() -> int:
    if not CSV_PATH.exists():
        print(f"{CSV_PATH.relative_to(REPO)} not found; run `sample` after a real run")
        return 1
    rows = [
        r
        for r in csv.DictReader(open(CSV_PATH, encoding="utf-8"))
        if r["human_verdict"].strip().lower() in ("pass", "fail")
    ]
    if not rows:
        print("no human grades filled in yet")
        return 1

    def summarise(subset: list[dict]) -> str:
        pairs = [(r["judge_verdict"], r["human_verdict"].strip().lower()) for r in subset]
        agree = sum(a == b for a, b in pairs) / len(pairs)
        kappa = cohen_kappa(pairs)
        return f"{len(pairs)} | {agree * 100:.1f}% | {'n/a' if kappa is None else f'{kappa:.2f}'}"

    lines = [
        "| Slice | Items | Agreement | Cohen's kappa |",
        "| --- | --- | --- | --- |",
        f"| all | {summarise(rows)} |",
    ]
    for field in ("category", "participant"):
        for value in sorted({r[field] for r in rows}):
            lines.append(f"| {field}: {value} | {summarise([r for r in rows if r[field] == value])} |")
    text = DOC_PATH.read_text(encoding="utf-8")
    head, _, rest = text.partition(START)
    _, _, tail = rest.partition(END)
    DOC_PATH.write_text(f"{head}{START}\n{chr(10).join(lines)}\n{END}{tail}", encoding="utf-8")
    print("\n".join(lines))
    return 0


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    sub = parser.add_subparsers(dest="cmd", required=True)
    s = sub.add_parser("sample")
    s.add_argument("--runs", nargs="+", type=Path, required=True)
    s.add_argument("--n", type=int, default=36)
    s.add_argument("--seed", type=int, default=20261025)
    sub.add_parser("score")
    args = parser.parse_args(argv)
    return sample(args.runs, args.n, args.seed) if args.cmd == "sample" else score()


if __name__ == "__main__":
    sys.exit(main())
