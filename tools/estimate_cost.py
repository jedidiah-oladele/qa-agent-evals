"""Estimate the cost of the full paid run before spending it.

Two methods, both printed with their inputs so the number can be checked:

1. ``--smoke <jsonl>`` (recommended): measured. Run a small real smoke test
   first, e.g. ``uv run python -m harness.run --tasks bf_001 pr_016 wt_023 --k 1 --yes``,
   then scale each participant's measured mean cost per episode (agent + judge)
   to the full matrix (tasks x k), and add a safety margin.
2. No smoke file: assumption-based. Uses per-episode token assumptions
   (editable flags) and the prices in config/models.yaml. Treat it as an order
   of magnitude, not a quote.

Native harness runs are estimated like their underlying model.
"""

from __future__ import annotations

import argparse
import json
import sys
from collections import defaultdict
from pathlib import Path

from harness.config import models_config, run_config
from harness.models import Usage, cost_usd
from harness.paths import TASKS
from harness.task import discover_tasks


def measured(smoke: Path, n_tasks: int, k: int, margin: float) -> int:
    per: dict[str, list[float]] = defaultdict(list)
    judge: dict[str, list[float]] = defaultdict(list)
    for line in smoke.read_text().splitlines():
        if not line.strip():
            continue
        r = json.loads(line)
        if r.get("dry_run") or r.get("status") == "skipped":
            continue
        if r.get("cost_usd") is not None:
            per[r["participant"]].append(r["cost_usd"])
        if r.get("judge_cost_usd") is not None:
            judge[r["participant"]].append(r["judge_cost_usd"])
    if not per:
        print("no priced real runs in the smoke file")
        return 1
    total = 0.0
    print(f"Measured from {smoke} -> full matrix of {n_tasks} tasks x k={k}, margin x{margin}")
    for participant, costs in sorted(per.items()):
        agent = sum(costs) / len(costs)
        judged = sum(judge[participant]) / len(judge[participant]) if judge[participant] else 0.0
        est = (agent + judged) * n_tasks * k * margin
        total += est
        print(
            f"  {participant:<28} {len(costs)} smoke episodes, ${agent:.3f} agent + ${judged:.3f} judge per "
            f"episode -> ${est:,.2f}"
        )
    print(f"  TOTAL ~ ${total:,.2f}")
    return 0


def assumed(n_tasks: int, k: int, steps: int, fresh_in: int, cached_in: int, out: int, judge_items: float) -> int:
    config = models_config()
    print(
        f"Assumption-based estimate: {n_tasks} tasks x k={k}; per episode {steps} steps, each step "
        f"{fresh_in:,} uncached + {cached_in:,} cached input tokens and {out:,} output tokens; "
        f"{judge_items} judge items per episode (8k in / 300 out each), 20% re-judged by the cross-check."
    )
    total = 0.0
    per_step = Usage(fresh_in, out, cached_in, 0)
    for agent in config.agents:
        episode = cost_usd(
            Usage(
                per_step.input_tokens * steps,
                per_step.output_tokens * steps,
                per_step.cache_read_tokens * steps,
                fresh_in * steps // 2,
            ),
            agent.pricing,
        )
        participants = 1 + sum(1 for h in config.native_harnesses if h.model_key == agent.key)
        cost = (episode or 0) * n_tasks * k * participants
        total += cost
        print(f"  {agent.key:<22} ${episode:.3f}/episode x {participants} harness(es) -> ${cost:,.2f}")
    judge_call = Usage(8000, 300)
    j1 = cost_usd(judge_call, config.judge.primary.pricing) or 0
    j2 = cost_usd(judge_call, config.judge.cross_check.pricing) or 0
    episodes = n_tasks * k * (len(config.agents) + len(config.native_harnesses))
    judging = episodes * judge_items * (j1 + 0.2 * j2)
    total += judging
    print(f"  judging                ${judging:,.2f} ({episodes} episodes)")
    print(f"  TOTAL ~ ${total:,.2f}  (assumptions, not measurements: run a smoke test and use --smoke)")
    return 0


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    parser.add_argument("--smoke", type=Path)
    parser.add_argument("--k", type=int, default=run_config().k)
    parser.add_argument("--margin", type=float, default=1.3)
    parser.add_argument("--steps", type=int, default=25)
    parser.add_argument("--fresh-input", type=int, default=3_000, help="uncached input tokens per step")
    parser.add_argument("--cached-input", type=int, default=25_000, help="cache-read input tokens per step")
    parser.add_argument("--output", type=int, default=1_500, help="output tokens (incl. reasoning) per step")
    parser.add_argument("--judge-items", type=float, default=2.0)
    args = parser.parse_args(argv)
    n_tasks = len(discover_tasks(TASKS))
    if args.smoke:
        return measured(args.smoke, n_tasks, args.k, args.margin)
    return assumed(n_tasks, args.k, args.steps, args.fresh_input, args.cached_input, args.output, args.judge_items)


if __name__ == "__main__":
    sys.exit(main())
