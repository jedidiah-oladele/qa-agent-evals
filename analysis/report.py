"""Generate results/results.md, results/summary.csv and results/charts/*.png.

Every number comes from the JSONL files in results/runs/. Nothing is typed by
hand. If any real (non-dry-run) runs exist, the report covers only real runs;
otherwise it reports the dry-run data under a prominent banner saying the
numbers come from scripted fake models.

    uv run python -m analysis.report
    uv run python -m analysis.report --runs results/runs/run-2026....jsonl
"""

from __future__ import annotations

import argparse
import csv
import json
import sys
from collections import Counter, defaultdict
from pathlib import Path

from harness.config import run_config
from harness.paths import REPO, RESULTS, RUNS

from .failure_attribution import attribute
from .stats import Estimate, cohen_kappa, mean_score, pass_at_1, pass_hat, paired_difference, per_task

CHARTS = RESULTS / "charts"
CATEGORIES = ["bug_fix", "pr_derived", "write_tests", "flaky_test", "ci_triage", "code_review"]
LANGUAGES = ["python", "typescript"]
DIFFICULTIES = ["easy", "medium", "hard"]

# Reference categorical palette (validated light-mode steps), fixed order by participant.
PALETTE = ["#2a78d6", "#eb6834", "#1baf7a", "#eda100", "#e87ba4", "#008300", "#6250d6", "#e34948"]
SURFACE, INK, INK2, GRID = "#fcfcfb", "#0b0b0b", "#52514e", "#e4e3df"
SEQUENTIAL = ["#cde2fb", "#9ec5f4", "#6da7ec", "#3987e5", "#256abf", "#184f95", "#0d366b"]


def load_runs(paths: list[Path]) -> list[dict]:
    records = []
    for path in paths:
        for line in path.read_text(encoding="utf-8").splitlines():
            if line.strip():
                records.append(json.loads(line))
    return records


def select(records: list[dict], include_dry: bool) -> tuple[list[dict], bool]:
    real = [r for r in records if not r.get("dry_run")]
    if real and not include_dry:
        return real, False
    return records, any(r.get("dry_run") for r in records)


def by(records: list[dict], key: str) -> dict[str, list[dict]]:
    groups: dict[str, list[dict]] = defaultdict(list)
    for r in records:
        groups[r[key]].append(r)
    return dict(groups)


def fmt_money(value: float | None) -> str:
    return "n/a" if value is None else f"${value:.4f}"


def _mean(xs):
    xs = list(xs)
    return sum(xs) / len(xs) if xs else 0.0


def participant_order(records: list[dict]) -> list[str]:
    seen = []
    for r in records:
        if r["participant"] not in seen:
            seen.append(r["participant"])
    return sorted(seen, key=lambda p: (p.startswith("fake-") is False, p))


class Analysis:
    def __init__(self, records: list[dict], samples: int, seed: int) -> None:
        self.all = records
        self.skipped = [r for r in records if r.get("status") == "skipped"]
        self.records = [r for r in records if r.get("status") != "skipped"]
        self.samples, self.seed = samples, seed
        self.participants = participant_order(self.records)
        self.groups = by(self.records, "participant") if self.records else {}
        runs_per_task = [len(v) for p in self.groups.values() for v in per_task(p).values()]
        self.k = min(runs_per_task) if runs_per_task else 0

    def est(self, records: list[dict], field: str = "primary_pass") -> Estimate:
        return pass_at_1(per_task(records, field), samples=self.samples, seed=self.seed)

    def overall(self, participant: str) -> dict:
        rs = self.groups[participant]
        costs = [r.get("cost_usd") for r in rs]
        judge = [r.get("judge_cost_usd") for r in rs]
        flags = [r for r in rs if any(not c.get("passed", True) for c in r.get("negative_checks", []))]
        return {
            "participant": participant,
            "harness": rs[0]["harness"],
            "model": rs[0]["model"],
            "runs": len(rs),
            "tasks": len({r["task_id"] for r in rs}),
            "pass_at_1": self.est(rs),
            "pass_hat_k": pass_hat(per_task(rs), self.k, samples=self.samples, seed=self.seed) if self.k else None,
            "task_score": mean_score(per_task(rs, "task_score"), samples=self.samples, seed=self.seed),
            "steps": _mean(r.get("steps") or 0 for r in rs),
            "cost": None if any(c is None for c in costs) else _mean(costs),
            "judge_cost": None if any(c is None for c in judge) else _mean(judge),
            "flagged_runs": len(flags),
            "errors": sum(r.get("status") == "error" for r in rs),
        }

    def slice_table(self, key: str, values: list[str]) -> list[list[str]]:
        rows = []
        for p in self.participants:
            row = [f"`{p}`"]
            for v in values:
                rs = [r for r in self.groups[p] if r[key] == v]
                row.append(self.est(rs).fmt() if rs else "-")
            rows.append(row)
        return rows

    def attributions(self) -> list[tuple[dict, object]]:
        out = []
        for r in self.records:
            a = attribute(r)
            if a is not None:
                out.append((r, a))
        return out

    def judge_agreement(self) -> dict:
        pairs = []
        for r in self.records:
            for item in r.get("rubric", []):
                cross = item.get("cross_check")
                if cross:
                    pairs.append((item.get("verdict"), cross.get("verdict")))
        judged = sum(1 for r in self.records for i in r.get("rubric", []) if i.get("grader") == "judge")
        valid = [(a, b) for a, b in pairs if a in ("pass", "fail") and b in ("pass", "fail")]
        agree = sum(a == b for a, b in valid)
        return {"judged": judged, "cross_checked": len(pairs), "comparable": len(valid),
                "agreement": (agree / len(valid)) if valid else None, "kappa": cohen_kappa(valid)}


# ---------------------------------------------------------------- charts ----

def _style(ax, fig):
    fig.patch.set_facecolor(SURFACE)
    ax.set_facecolor(SURFACE)
    for side in ("top", "right"):
        ax.spines[side].set_visible(False)
    for side in ("left", "bottom"):
        ax.spines[side].set_color(GRID)
    ax.tick_params(colors=INK2, labelsize=9)
    ax.yaxis.label.set_color(INK2)
    ax.xaxis.label.set_color(INK2)
    ax.title.set_color(INK)


def charts(analysis: Analysis, dry: bool, out_dir: Path = CHARTS) -> list[str]:
    import matplotlib

    matplotlib.use("Agg")
    import matplotlib.pyplot as plt

    out_dir.mkdir(parents=True, exist_ok=True)
    note = " (DRY RUN: fake models, not model results)" if dry else ""
    colors = {p: PALETTE[i % len(PALETTE)] for i, p in enumerate(analysis.participants)}
    written = []

    # 1. pass@1 with 95% CI
    fig, ax = plt.subplots(figsize=(7, 0.6 * len(analysis.participants) + 1.4), dpi=110)
    _style(ax, fig)
    ests = [analysis.overall(p)["pass_at_1"] for p in analysis.participants]
    ys = list(range(len(ests)))[::-1]
    for y, p, e in zip(ys, analysis.participants, ests):
        ax.barh(y, e.value * 100, height=0.5, color=colors[p], zorder=2)
        ax.errorbar(e.value * 100, y, xerr=[[max(0, (e.value - e.low) * 100)], [max(0, (e.high - e.value) * 100)]],
                    fmt="none", ecolor=INK, elinewidth=1.5, capsize=4, zorder=3)
        ax.text(min(e.high * 100 + 2, 101), y, f"{e.value * 100:.0f}%", va="center", fontsize=9, color=INK)
    ax.set_yticks(ys, analysis.participants)
    ax.set_xlim(0, 110)
    ax.set_xlabel("pass@1 (%), 95% task-bootstrap CI")
    ax.xaxis.grid(True, color=GRID, linewidth=0.8, zorder=0)
    ax.set_title("pass@1 by model and harness" + note, fontsize=10, loc="left")
    fig.tight_layout()
    path = out_dir / "pass_at_1.png"
    fig.savefig(path, facecolor=SURFACE)
    plt.close(fig)
    written.append(path)

    # 2. category heatmap (sequential blue, values annotated)
    fig, ax = plt.subplots(figsize=(8, 0.55 * len(analysis.participants) + 1.6), dpi=110)
    _style(ax, fig)
    grid = []
    for p in analysis.participants:
        row = []
        for c in CATEGORIES:
            rs = [r for r in analysis.groups[p] if r["category"] == c]
            row.append(_mean(float(r.get("primary_pass") or 0) for r in rs) if rs else float("nan"))
        grid.append(row)
    from matplotlib.colors import LinearSegmentedColormap

    cmap = LinearSegmentedColormap.from_list("seq", SEQUENTIAL)
    ax.imshow(grid, cmap=cmap, vmin=0, vmax=1, aspect="auto")
    for i, row in enumerate(grid):
        for j, v in enumerate(row):
            if v == v:
                ax.text(j, i, f"{v * 100:.0f}%", ha="center", va="center", fontsize=9,
                        color="#ffffff" if v > 0.55 else INK)
    ax.set_xticks(range(len(CATEGORIES)), [c.replace("_", " ") for c in CATEGORIES])
    ax.set_yticks(range(len(analysis.participants)), analysis.participants)
    for spine in ax.spines.values():
        spine.set_visible(False)
    ax.set_title("pass@1 by task category" + note, fontsize=10, loc="left")
    fig.tight_layout()
    path = out_dir / "category_pass_rates.png"
    fig.savefig(path, facecolor=SURFACE)
    plt.close(fig)
    written.append(path)

    # 3. failure attribution stacked bars (three slots: validated all-pairs)
    labels = ["agent", "environment", "grader"]
    label_colors = {"agent": PALETTE[0], "environment": PALETTE[1], "grader": PALETTE[2]}
    counts = {p: Counter() for p in analysis.participants}
    for r, a in analysis.attributions():
        counts[r["participant"]][a.label] += 1
    fig, ax = plt.subplots(figsize=(7, 0.6 * len(analysis.participants) + 1.6), dpi=110)
    _style(ax, fig)
    ys = list(range(len(analysis.participants)))[::-1]
    for y, p in zip(ys, analysis.participants):
        left = 0
        for label in labels:
            n = counts[p][label]
            if n:
                ax.barh(y, n, left=left, height=0.5, color=label_colors[label], edgecolor=SURFACE, linewidth=2,
                        zorder=2)
                ax.text(left + n / 2, y, str(n), ha="center", va="center", fontsize=8, color="#ffffff")
                left += n
    ax.set_yticks(ys, analysis.participants)
    ax.set_xlabel("failed runs")
    from matplotlib.ticker import MaxNLocator

    ax.xaxis.set_major_locator(MaxNLocator(integer=True))
    ax.xaxis.grid(True, color=GRID, linewidth=0.8, zorder=0)
    handles = [plt.Rectangle((0, 0), 1, 1, color=label_colors[lbl]) for lbl in labels]
    ax.legend(handles, [f"{lbl} error" for lbl in labels], frameon=False, fontsize=8, labelcolor=INK2,
              loc="lower right")
    ax.set_title("Failure attribution" + note, fontsize=10, loc="left")
    fig.tight_layout()
    path = out_dir / "failure_attribution.png"
    fig.savefig(path, facecolor=SURFACE)
    plt.close(fig)
    written.append(path)
    return [f"{out_dir.name}/{p.name}" for p in written]


# ---------------------------------------------------------------- report ----

def table(header: list[str], rows: list[list[str]]) -> str:
    lines = ["| " + " | ".join(header) + " |", "| " + " | ".join("---" for _ in header) + " |"]
    lines += ["| " + " | ".join(row) + " |" for row in rows]
    return "\n".join(lines)


def diff_excerpt(diff: str, max_lines: int = 18) -> str:
    lines = [line for line in diff.splitlines() if not line.startswith(("index ", "new file mode"))]
    body = lines[:max_lines]
    if len(lines) > max_lines:
        body.append(f"... ({len(lines) - max_lines} more diff lines)")
    return "\n".join(body)


def case_studies(analysis: Analysis, minimum: int = 5, maximum: int = 8) -> list[str]:
    failures = analysis.attributions()
    chosen: list[tuple[dict, object]] = []
    seen_reasons: set[tuple] = set()
    seen_tasks: set[str] = set()
    # Prefer variety: one per (label, reason), spread across categories and participants.
    for r, a in sorted(failures, key=lambda x: (x[1].label != "agent", x[0]["category"], x[0]["participant"],
                                                x[0]["task_id"], x[0]["run_index"])):
        key = (a.label, a.reason)
        if key in seen_reasons or r["task_id"] in seen_tasks:
            continue
        chosen.append((r, a))
        seen_reasons.add(key)
        seen_tasks.add(r["task_id"])
        if len(chosen) >= maximum:
            break
    for r, a in failures:
        if len(chosen) >= minimum:
            break
        if (r, a) not in chosen and r["task_id"] not in seen_tasks:
            chosen.append((r, a))
            seen_tasks.add(r["task_id"])
    out = []
    for n, (r, a) in enumerate(chosen, 1):
        files = sorted({line[6:] for line in (r.get("diff") or "").splitlines() if line.startswith("+++ b/")})
        failed_items = [i for i in r.get("rubric", []) if i.get("verdict") == "fail"]
        part = [
            f"### Case {n}: `{r['participant']}` on `{r['task_id']}` ({r['category']}, {r['difficulty']}, "
            f"{r['language']}, run {r['run_index']})",
            "",
            f"- **Attribution:** {a.label} error: {a.reason}",
            f"- **Evidence:** {a.evidence}",
            f"- **Trajectory:** stopped with `{r.get('stop_reason')}` after {r.get('steps')} steps; "
            f"files changed: {', '.join(f'`{f}`' for f in files) or 'none'}",
            f"- **Score:** primary {r.get('primary_pass')}, rubric {r.get('rubric_score')}, penalty "
            f"{r.get('penalty')}, task score {r.get('task_score')}",
        ]
        if r.get("submit_summary"):
            part.append(f"- **Agent's summary:** {r['submit_summary'][:300]}")
        if failed_items:
            item = failed_items[0]
            part.append(f"- **Rubric item `{item['id']}` failed ({item.get('judge_model')}):** "
                        f"{str(item.get('rationale'))[:300]}")
        if r.get("diff"):
            part += ["", "```diff", diff_excerpt(r["diff"]), "```"]
        out.append("\n".join(part))
    return out


def _rel(path: Path) -> str:
    path = path.resolve()
    return str(path.relative_to(REPO)) if path.is_relative_to(REPO) else str(path)


def render(analysis: Analysis, dry: bool, chart_files: list[str], sources: list[Path]) -> str:
    cfg = run_config()
    overall = [analysis.overall(p) for p in analysis.participants]
    run_ids = sorted({r["run_id"] for r in analysis.records})
    commits = sorted({r.get("harness_commit", "?") for r in analysis.records})
    lines = ["# Results", ""]
    if dry:
        lines += [
            "> [!WARNING]",
            "> **DRY RUN: these numbers come from scripted fake models, not from any real model.** "
            "`fake-oracle` replays each task's reference solution, `fake-mixed` deterministically "
            "alternates between the reference, a flawed solution, giving up and a simulated provider outage, "
            "and `fake-cheater` tries to read hidden tests and skips tests. The rubric judge is a "
            "keyword heuristic (`fake-judge`). They exist to exercise the full pipeline (sandbox, graders, "
            "negative checks, statistics, attribution, this report) without API keys. Real model results are "
            "pending a paid run; see the README for the command and cost estimate.",
            "",
        ]
    lines += [
        "Generated by `make report` (`analysis/report.py`) from "
        + ", ".join(f"`{_rel(s)}`" for s in sources)
        + ". Do not edit by hand: every number below is computed from those JSONL files.",
        "",
        f"- Runs: {len(analysis.records)} graded episodes ({len(analysis.skipped)} skipped) across "
        f"{len({r['task_id'] for r in analysis.records})} tasks; k = {analysis.k} runs per task per model/harness",
        f"- Run ids: {', '.join(f'`{x}`' for x in run_ids)}; harness commit(s): {', '.join(commits)}",
        f"- Confidence intervals: 95% percentile bootstrap over tasks ({analysis.samples} resamples, seed "
        f"{analysis.seed}); runs of one task are resampled together.",
        "",
    ]
    if analysis.skipped:
        reasons = Counter((r["participant"], r.get("error")) for r in analysis.skipped)
        lines.append("Skipped participants: " + "; ".join(f"`{p}` ({why}, {n} tasks)" for (p, why), n in
                                                            reasons.items()))
        lines.append("")

    lines += ["## Overall", ""]
    rows = []
    for o in overall:
        rows.append([f"`{o['participant']}`", o["harness"], str(o["runs"]), o["pass_at_1"].fmt(),
                     o["pass_hat_k"].fmt() if o["pass_hat_k"] else "-", o["task_score"].fmt(pct=False),
                     f"{o['steps']:.1f}", fmt_money(o["cost"]), fmt_money(o["judge_cost"]),
                     str(o["flagged_runs"]), str(o["errors"])])
    lines.append(table(["Model", "Harness", "Runs", "pass@1 [95% CI]", f"pass^{analysis.k} [95% CI]",
                        "Task score [95% CI]", "Mean steps", "Mean agent cost/run", "Mean judge cost/run",
                        "Runs flagged by negative checks", "Run errors"], rows))
    lines += ["", f"![pass@1 by model]({chart_files[0]})" if chart_files else "", ""]

    if len(analysis.participants) > 1:
        lines += ["## Pairwise differences in pass@1", "",
                  "Paired by task; an interval that excludes 0 is a difference the data supports.", ""]
        rows = []
        ps = analysis.participants
        for i, a in enumerate(ps):
            for b in ps[i + 1:]:
                d = paired_difference(per_task(analysis.groups[a]), per_task(analysis.groups[b]),
                                      samples=analysis.samples, seed=analysis.seed)
                rows.append([f"`{a}` - `{b}`", f"{d.value * 100:+.1f} pts [{d.low * 100:+.1f}, {d.high * 100:+.1f}]",
                             str(d.n_tasks)])
        lines += [table(["Comparison", "Difference [95% CI]", "Shared tasks"], rows), ""]

    lines += ["## By category (pass@1 [95% CI])", "",
              table(["Model"] + CATEGORIES, analysis.slice_table("category", CATEGORIES)), ""]
    if len(chart_files) > 1:
        lines += [f"![pass@1 by category]({chart_files[1]})", ""]
    lines += ["## By language (pass@1 [95% CI])", "",
              table(["Model"] + LANGUAGES, analysis.slice_table("language", LANGUAGES)), ""]
    lines += ["## By difficulty (pass@1 [95% CI])", "",
              table(["Model"] + DIFFICULTIES, analysis.slice_table("difficulty", DIFFICULTIES)), ""]

    attributions = analysis.attributions()
    lines += ["## Failure attribution", "",
              "Every failed run (primary fail or a negative check fired) is labelled by "
              "`analysis/failure_attribution.py` as an agent, environment or grader error.", ""]
    counts = defaultdict(Counter)
    reasons = Counter()
    for r, a in attributions:
        counts[r["participant"]][a.label] += 1
        reasons[(a.label, a.reason)] += 1
    rows = [[f"`{p}`", str(sum(1 for r in analysis.groups[p] if attribute(r) is not None)),
             str(counts[p]["agent"]), str(counts[p]["environment"]), str(counts[p]["grader"])]
            for p in analysis.participants]
    lines += [table(["Model", "Failed runs", "Agent", "Environment", "Grader"], rows), ""]
    lines += [table(["Label", "Reason", "Runs"], [[lbl, why, str(n)] for (lbl, why), n in reasons.most_common()]), ""]
    if len(chart_files) > 2:
        lines += [f"![failure attribution]({chart_files[2]})", ""]

    check_counts = defaultdict(Counter)
    for r in analysis.records:
        for c in r.get("negative_checks", []):
            if not c.get("passed", True):
                check_counts[r["participant"]][c["name"]] += 1
    names = sorted({n for c in check_counts.values() for n in c})
    if names:
        lines += ["## Negative-check flags", "",
                  table(["Model"] + names, [[f"`{p}`"] + [str(check_counts[p][n]) for n in names]
                                            for p in analysis.participants]), ""]

    ja = analysis.judge_agreement()
    lines += ["## Judge cross-check", ""]
    if ja["cross_checked"]:
        agreement = f"{ja['agreement'] * 100:.1f}%" if ja["agreement"] is not None else "n/a"
        kappa = f"{ja['kappa']:.2f}" if ja["kappa"] is not None else "n/a"
        lines += [f"{ja['cross_checked']} of {ja['judged']} judged rubric items (a deterministic ~20% sample, seed {cfg.seed}) were "
                  f"re-judged by the cross-check judge: raw agreement **{agreement}**, Cohen's kappa **{kappa}** "
                  f"over {ja['comparable']} comparable verdicts. Human calibration is tracked separately in "
                  "`docs/judge_calibration.md`.", ""]
    else:
        lines += ["No cross-checked items in these runs.", ""]

    lines += ["## Failure case studies", "",
              "Selected automatically for variety (distinct failure reasons, tasks and categories).", ""]
    studies = case_studies(analysis)
    lines += ["\n\n".join(studies) if studies else "No failed runs.", ""]
    return "\n".join(lines)


def write_csv(analysis: Analysis, path: Path) -> None:
    with open(path, "w", newline="", encoding="utf-8") as handle:
        writer = csv.writer(handle)
        writer.writerow(["participant", "harness", "model", "slice", "value", "runs", "tasks", "pass_at_1",
                         "pass_at_1_low", "pass_at_1_high", f"pass_hat_{analysis.k}", "mean_task_score",
                         "mean_steps", "mean_cost_usd", "dry_run"])
        for p in analysis.participants:
            o = analysis.overall(p)
            rs = analysis.groups[p]
            dry = any(r.get("dry_run") for r in rs)
            ph = o["pass_hat_k"].value if o["pass_hat_k"] else ""
            writer.writerow([p, o["harness"], o["model"], "overall", "all", o["runs"], o["tasks"],
                             f"{o['pass_at_1'].value:.4f}", f"{o['pass_at_1'].low:.4f}", f"{o['pass_at_1'].high:.4f}",
                             f"{ph:.4f}" if ph != "" else "", f"{o['task_score'].value:.4f}", f"{o['steps']:.2f}",
                             "" if o["cost"] is None else f"{o['cost']:.6f}", dry])
            for key, values in (("category", CATEGORIES), ("language", LANGUAGES), ("difficulty", DIFFICULTIES)):
                for v in values:
                    sub = [r for r in rs if r[key] == v]
                    if not sub:
                        continue
                    e = analysis.est(sub)
                    writer.writerow([p, o["harness"], o["model"], key, v, len(sub), len({r["task_id"] for r in sub}),
                                     f"{e.value:.4f}", f"{e.low:.4f}", f"{e.high:.4f}", "",
                                     f"{_mean(float(r.get('task_score') or 0) for r in sub):.4f}",
                                     f"{_mean(r.get('steps') or 0 for r in sub):.2f}", "", dry])


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    parser.add_argument("--runs", nargs="*", type=Path, help="JSONL files (default: results/runs/*.jsonl)")
    parser.add_argument("--include-dry", action="store_true", help="include dry-run data next to real runs")
    parser.add_argument("--out", type=Path, default=RESULTS / "results.md")
    parser.add_argument("--no-charts", action="store_true")
    parser.add_argument("--csv", type=Path, help="summary CSV path (default: next to --out)")
    args = parser.parse_args(argv)
    sources = args.runs or sorted(RUNS.glob("*.jsonl"))
    if not sources:
        print("no run files in results/runs; run `make run` or `make dry-run` first")
        return 1
    records, dry = select(load_runs(sources), args.include_dry)
    if not dry:
        sources = [s for s in sources if any(not json.loads(line).get("dry_run")
                                             for line in s.read_text().splitlines()[:1] if line.strip())]
    cfg = run_config()
    analysis = Analysis(records, cfg.bootstrap_samples, cfg.seed)
    if not analysis.records:
        print("no graded runs to report")
        return 1
    out_dir = args.out.parent
    chart_files = [] if args.no_charts else charts(analysis, dry, out_dir / "charts")
    args.out.write_text(render(analysis, dry, chart_files, sources), encoding="utf-8")
    csv_path = args.csv or out_dir / "summary.csv"
    write_csv(analysis, csv_path)
    print(f"wrote {_rel(args.out)}, {_rel(csv_path)} and {len(chart_files)} chart(s)")
    return 0


if __name__ == "__main__":
    sys.exit(main())
