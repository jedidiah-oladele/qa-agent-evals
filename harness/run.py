"""Run the evaluation matrix: every task x every model/harness x k runs.

    uv run python -m harness.run --dry-run                 # scripted fake models, no keys, no cost
    uv run python -m harness.run --yes                     # real run (reads ANTHROPIC_API_KEY, OPENAI_API_KEY)
    uv run python -m harness.run --models claude-sonnet-5-5 --tasks bf_001 --k 1 --yes   # smoke test

Each finished episode appends one JSON line to ``results/runs/<run_id>.jsonl``
with: task_id, model, harness, run_index, primary_pass, rubric results with
rationales, negative-check results, steps, tokens, cost_usd, wall_time_s,
the final diff, a compact trajectory and failure-attribution inputs. Runs can
be resumed with ``--resume <file>``: episodes already in the file are skipped.
"""

from __future__ import annotations

import argparse
import datetime as dt
import json
import os
import subprocess
import sys
import threading
import time
import traceback
from concurrent.futures import ThreadPoolExecutor, as_completed
from dataclasses import dataclass
from pathlib import Path

from graders.grade import GradeResult, JudgeSetup, grade_submission
from graders.rubric_judge import FakeJudge, LLMJudge

from .agent_loop import run_episode
from .config import AgentModel, ModelsConfig, NativeHarness, RunConfig, models_config, run_config
from .models import ModelError, cost_usd, make_adapter
from .native import ADAPTERS
from .paths import REPO, RUNS, TASKS
from .sandbox import SandboxError, create_sandbox, node_modules_for, resolve_backend
from .task import Task, discover_tasks
from .tools import ToolExecutor
from .workspace import PatchError, build_workspace

SHARED_HARNESS = "shared-loop"
KEY_ENV = {"anthropic": "ANTHROPIC_API_KEY", "openai": "OPENAI_API_KEY"}


@dataclass(frozen=True)
class Participant:
    """One column of the results table: a model inside a harness."""

    key: str
    harness: str
    model: AgentModel
    native: NativeHarness | None = None


def git_commit() -> str:
    result = subprocess.run(["git", "rev-parse", "--short", "HEAD"], cwd=REPO, capture_output=True, text=True)
    return result.stdout.strip() or "unknown"


def participants(config: ModelsConfig, *, dry_run: bool, models: list[str] | None, harnesses: str) -> list[Participant]:
    chosen: list[Participant] = []
    agents = config.fake_agents if dry_run else config.agents
    if harnesses in ("shared", "all"):
        for agent in agents:
            if not models or agent.key in models:
                chosen.append(Participant(agent.key, SHARED_HARNESS, agent))
    if harnesses in ("native", "all") and not dry_run:
        for native in config.native_harnesses:
            model = config.agent(native.model_key)
            if not models or native.key in models or native.model_key in models:
                chosen.append(Participant(native.key, native.adapter, model, native))
    return chosen


def judges_for(config: ModelsConfig, run_cfg: RunConfig, *, dry_run: bool, skip: bool) -> JudgeSetup | None:
    if skip:
        return None
    if dry_run:
        spec = config.fake_judges
        return JudgeSetup(
            FakeJudge(spec.primary.model_id, error_rate=0.03),
            None,
            FakeJudge(spec.cross_check.model_id, disagree_rate=0.12),
            None,
            spec.cross_check.sample_rate or 0.0,
            run_cfg.seed,
        )
    spec = config.judge
    return JudgeSetup(
        LLMJudge(spec.primary),
        spec.primary.pricing,
        LLMJudge(spec.cross_check),
        spec.cross_check.pricing,
        spec.cross_check.sample_rate or 0.0,
        run_cfg.seed,
    )


def _compact_trajectory(trajectory: list[dict]) -> list[dict]:
    compact = []
    for event in trajectory:
        event = dict(event)
        if event.get("type") == "tool_call":
            args = {}
            for key, value in (event.get("arguments") or {}).items():
                text = str(value)
                args[key] = text if len(text) <= 300 else text[:300] + f"... [{len(text)} chars]"
            event["arguments"] = args
            event["output"] = str(event.get("output", ""))[:300]
        elif event.get("type") == "model_turn":
            event["text"] = str(event.get("text", ""))[:600]
        compact.append(event)
    return compact


def base_record(run_id: str, p: Participant, task: Task, run_index: int, dry_run: bool) -> dict:
    return {
        "run_id": run_id,
        "dry_run": dry_run,
        "task_id": task.id,
        "category": task.category,
        "language": task.language,
        "difficulty": task.difficulty,
        "model": p.model.model_id,
        "participant": p.key,
        "harness": p.harness,
        "provider": p.model.provider,
        "run_index": run_index,
        "started_at": dt.datetime.now(dt.UTC).isoformat(timespec="seconds"),
    }


def run_one(
    run_id: str,
    p: Participant,
    task: Task,
    run_index: int,
    *,
    backend: str,
    run_cfg: RunConfig,
    judges: JudgeSetup | None,
    dry_run: bool,
) -> dict:
    record = base_record(run_id, p, task, run_index, dry_run)
    record.update(status="ok", error=None, error_kind=None)
    started = time.monotonic()
    workspace = None
    try:
        if p.native is not None:
            adapter = ADAPTERS[p.native.adapter](p.model.model_id)
            if not adapter.available():
                record.update(status="skipped", error=adapter.skip_reason(), error_kind="skipped")
                return record
        workspace = build_workspace(task, node_modules=node_modules_for(backend))
        record["sandbox"] = {"backend": backend}
        if p.native is not None:
            from pathlib import Path as _P

            binds = [_P(adapter.cli_path).resolve().parent.parent] if adapter.cli_path else []
            with create_sandbox(
                workspace.root, backend, config=run_cfg.sandbox, env=task.env, network=True, extra_ro_binds=binds
            ) as sandbox:
                record["sandbox"]["isolation"] = sandbox.isolation
                record["sandbox"]["network"] = "vendor-api"
                result = adapter.run(task, sandbox, os.environ.get(adapter.key_env, ""))
            steps, usage, trajectory = result.steps, result.usage, result.trajectory
            stop_reason, agent_error = result.stop_reason, result.error
            agent_cost = result.cost_usd if result.cost_usd is not None else cost_usd(usage, p.model.pricing)
            wall = result.wall_time_s
            submit_summary = None
        else:
            with create_sandbox(workspace.root, backend, config=run_cfg.sandbox, env=task.env) as sandbox:
                record["sandbox"]["isolation"] = sandbox.isolation
                record["sandbox"]["network"] = "none"
                adapter = make_adapter(p.model, task=task, run_index=run_index)
                readonly = [Path(node_modules_for(backend))] if backend == "local" else []
                executor = ToolExecutor(workspace.root, sandbox, run_cfg.sandbox, readonly_roots=readonly)
                episode = run_episode(task, adapter, executor)
            steps, usage, trajectory = episode.steps, episode.usage, episode.trajectory
            stop_reason, agent_error = episode.stop_reason, episode.error
            if episode.error_kind:
                record["error_kind"] = (
                    "environment" if episode.error_kind in ("api", "rate_limit", "auth", "missing_key") else "agent"
                )
            agent_cost = cost_usd(usage, p.model.pricing)
            wall = episode.wall_time_s
            submit_summary = episode.submit_summary
        diff = workspace.diff()
        artifacts = {
            name: text for name in ("TRIAGE.md", "REVIEW.md") if (text := workspace.read_text(name)) is not None
        }
        grade: GradeResult = grade_submission(
            task,
            diff,
            trajectory,
            backend=backend,
            judges=judges,
            artifacts=artifacts,
            config=run_cfg,
            key=(task.id, p.key, run_index),
        )
        record.update(grade.to_dict())
        record.update(
            stop_reason=stop_reason,
            error=agent_error,
            steps=steps,
            tokens=usage.to_dict() | {"total": usage.total},
            cost_usd=agent_cost,
            judge_cost_usd=grade.judge_cost_usd,
            wall_time_s=round(time.monotonic() - started, 2),
            agent_wall_time_s=wall,
            submit_summary=submit_summary,
            diff=diff,
            artifacts=artifacts,
            trajectory=_compact_trajectory(trajectory),
        )
        if agent_error and record.get("error_kind") is None:
            record["error_kind"] = "agent"
    except (SandboxError, PatchError, ModelError, OSError) as exc:
        record.update(
            status="error",
            error=f"{type(exc).__name__}: {exc}"[:1000],
            error_kind="environment",
            primary_pass=0,
            task_score=0.0,
            rubric=[],
            negative_checks=[],
            steps=0,
            wall_time_s=round(time.monotonic() - started, 2),
            cost_usd=None,
            diff="",
        )
    except Exception as exc:  # a harness bug: record it, keep the matrix going
        record.update(
            status="error",
            error=f"{type(exc).__name__}: {exc}\n{traceback.format_exc()[-1200:]}",
            error_kind="harness",
            primary_pass=0,
            task_score=0.0,
            rubric=[],
            negative_checks=[],
            steps=0,
            wall_time_s=round(time.monotonic() - started, 2),
            cost_usd=None,
            diff="",
        )
    finally:
        if workspace is not None:
            workspace.cleanup()
    return record


def done_keys(path: Path) -> set[tuple]:
    keys = set()
    if path.exists():
        for line in path.read_text().splitlines():
            if line.strip():
                r = json.loads(line)
                keys.add((r["participant"], r["task_id"], r["run_index"]))
    return keys


def confirm_spend(n_episodes: int, plist: list[Participant], tasks: list[Task], k: int) -> bool:
    print(
        f"\nREAL RUN: {n_episodes} episodes ({len(plist)} model/harness x {len(tasks)} tasks x k={k}), "
        "plus judge calls on every judge rubric item."
    )
    print(
        "This spends money on the Anthropic and OpenAI APIs. Estimate first with:\n"
        "  uv run python -m tools.estimate_cost --smoke <a smoke-run jsonl>\n"
    )
    if not sys.stdin.isatty():
        print("Refusing to start a paid run without --yes in a non-interactive shell.")
        return False
    return input("Type 'spend' to continue: ").strip() == "spend"


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    parser.add_argument("--dry-run", action="store_true", help="scripted fake models and judges; no keys needed")
    parser.add_argument("--models", nargs="*", help="participant keys or model keys (default: all)")
    parser.add_argument("--harnesses", choices=["shared", "native", "all"], default="all")
    parser.add_argument("--tasks", nargs="*", help="task ids or prefixes (default: all)")
    parser.add_argument("--k", type=int, help="runs per task per participant")
    parser.add_argument("--backend", choices=["auto", "docker", "local"])
    parser.add_argument("--workers", type=int)
    parser.add_argument("--out", type=Path, help="output JSONL (default results/runs/<run_id>.jsonl)")
    parser.add_argument("--resume", type=Path, help="append to an existing JSONL, skipping finished episodes")
    parser.add_argument("--skip-judge", action="store_true", help="grade judge rubric items as skipped")
    parser.add_argument("--yes", action="store_true", help="confirm a paid run without prompting")
    args = parser.parse_args(argv)

    config, run_cfg = models_config(), run_config()
    dry = args.dry_run
    k = args.k or (run_cfg.dry_run.k if dry else run_cfg.k)
    workers = args.workers or (run_cfg.dry_run.workers if dry else run_cfg.workers)
    backend = resolve_backend(args.backend or run_cfg.backend)
    tasks = discover_tasks(TASKS, args.tasks)
    plist = participants(config, dry_run=dry, models=args.models, harnesses=args.harnesses)
    if not tasks or not plist:
        print("nothing to run (no tasks or no participants selected)")
        return 1

    if not dry:
        needed = {p.model.provider for p in plist} | (
            {config.judge.primary.provider, config.judge.cross_check.provider} if not args.skip_judge else set()
        )
        missing = [KEY_ENV[p] for p in needed if p in KEY_ENV and not os.environ.get(KEY_ENV[p])]
        if missing:
            print(f"missing API keys: {', '.join(missing)} (see .env.example); use --dry-run to run without keys")
            return 2

    run_id = (
        args.resume.stem
        if args.resume
        else f"{'dryrun' if dry else 'run'}-{dt.datetime.now(dt.UTC).strftime('%Y%m%dT%H%M%SZ')}"
    )
    out = args.resume or args.out or (RUNS / f"{run_id}.jsonl")
    out.parent.mkdir(parents=True, exist_ok=True)
    skip = done_keys(out)
    jobs = [
        (p, t, i)
        for p in plist
        for t in tasks
        for i in range(k)
        if (p.key, t.id, i) not in skip
        and not (p.native and i > 0 and not ADAPTERS[p.native.adapter](p.model.model_id).available())
    ]
    if not dry and not args.yes and not confirm_spend(len(jobs), plist, tasks, k):
        return 3

    judges = judges_for(config, run_cfg, dry_run=dry, skip=args.skip_judge)
    commit = git_commit()
    print(
        f"{'DRY RUN (fake models)' if dry else 'REAL RUN'} {run_id}: {len(jobs)} episodes, backend={backend}, "
        f"workers={workers}, commit={commit} -> {out.relative_to(REPO) if out.is_relative_to(REPO) else out}"
    )
    lock = threading.Lock()
    started = time.monotonic()
    finished = 0
    with ThreadPoolExecutor(max_workers=max(1, workers)) as pool, open(out, "a", encoding="utf-8") as sink:
        futures = {
            pool.submit(run_one, run_id, p, t, i, backend=backend, run_cfg=run_cfg, judges=judges, dry_run=dry): (
                p,
                t,
                i,
            )
            for p, t, i in jobs
        }
        for future in as_completed(futures):
            record = future.result()
            record["harness_commit"] = commit
            with lock:
                sink.write(json.dumps(record, default=str) + "\n")
                sink.flush()
                finished += 1
            p, t, i = futures[future]
            status = record["status"] if record["status"] != "ok" else f"primary={record.get('primary_pass')}"
            print(
                f"[{finished}/{len(jobs)}] {p.key:<24} {t.id:<38} run {i}: {status} "
                f"score={record.get('task_score')} ({record.get('wall_time_s')}s)",
                flush=True,
            )
    print(f"done in {time.monotonic() - started:.0f}s -> {out}")
    return 0


if __name__ == "__main__":
    sys.exit(main())
