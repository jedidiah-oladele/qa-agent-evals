# qa-agent-evals

This is my evaluation suite for coding agents doing QA work. I built it to show how I would turn a code change into a task and grade it so that a caught cheat does not count as a pass.

The tasks cover six kinds of work: fixing a bug from an issue, implementing a pull request, writing tests that kill mutants, fixing a flaky test at the cause, triaging a red CI log, and reviewing a diff for seeded defects. Two of the codebases, shopcore (Python) and ledgerkit (TypeScript), are libraries I wrote for this suite. One pull-request task is cut from a merged change in more-itertools. Counts, the judge's share of the score, and the assumption-based cost are in the [suite snapshot](#suite-snapshot), which is generated from the code.

A deterministic grader decides the pass or fail. A small rubric adds detail. Some rubric items are code checks. The rest go to an LLM judge. Negative checks look for gaming the grader. `make validate` has to pass before I trust a grader: the reference solution passes, every flawed solution fails, and every planted cheat is caught. The harness can run `claude-opus-5-5`, `claude-sonnet-5-5` and `gpt-6-astra` through one shared tool loop, plus the vendors' own coding-agent CLIs where they run headless. It reports pass@1 and pass^k with a 95% task-bootstrap confidence interval, and it labels a failure as an agent, environment or grader error.

I have not run a real model. The pipeline runs end to end with scripted fake models and no API keys. See [Results](#results).

[![validate](https://github.com/jedidiah-oladele/qa-agent-evals/actions/workflows/validate.yml/badge.svg)](https://github.com/jedidiah-oladele/qa-agent-evals/actions/workflows/validate.yml)

- [Problem](#problem)
- [What is measured](#what-is-measured)
- [Task design](#task-design)
- [Rubric philosophy](#rubric-philosophy)
- [Grader validation](#grader-validation)
- [Results](#results)
- [How to run](#how-to-run)
- [Cost](#cost)
- [Limitations](#limitations)
- [Related work](#related-work)
- [Suite snapshot](#suite-snapshot)
- [Repository layout](#repository-layout)
- [License](#license)

## Problem

Coding agents do well on fix-the-failing-test benchmarks, but QA work is wider and easier to fake. An agent can make a suite green by deleting the inconvenient test, skipping it, special-casing the expected value, or adding a sleep until the flaky test passes. Tests it writes can pass without catching anything. A code review can sound plausible while missing the actual bug. A benchmark that only checks "tests pass" rewards all of this.

This repository measures QA skills directly, and is built so that gaming the grader does not pay. Hidden tests are never visible from the agent's sandbox, with a unit test that proves it for every task. Written tests are judged by whether they kill mutants. Flaky-test fixes are judged by 20 perturbed runs. Reviews are judged by whether they locate the seeded defects. Each grader is validated against flawed and cheating solutions before it is trusted.

## What is measured

| Category | The agent gets | It must | Primary (deterministic) grader |
| --- | --- | --- | --- |
| **bug_fix** | an issue report and the repo | fix the bug (and add a regression test) | hidden fail-to-pass tests pass; the pass-to-pass tests stay green |
| **pr_derived** | a pull request description, with the change reverted | implement the change | the pull request's own tests + hidden edge-case tests |
| **write_tests** | a module whose tests were deleted | write tests | tests pass on clean code and kill the required share of hidden mutants |
| **flaky_test** | an intermittently failing suite | remove the root cause (no sleeps, retries, skips) | suite green in 20 runs with shuffled order, re-seeded randomness, varied hash seed and time zone |
| **ci_triage** | a red CI log and the repo | fix the cause and write a 3-5 line TRIAGE.md | hidden tests; the root cause write-up is graded by the rubric |
| **code_review** | a PR (`PR.md` + `pr.diff`) with seeded defects | write REVIEW.md, one located finding per defect | every seeded defect located by file:line; findings that match none are bounded |

The task counts, languages and difficulty mix are in the [suite snapshot](#suite-snapshot). The full list is in [`docs/tasks.md`](docs/tasks.md). Most pull-request tasks use the history I wrote for shopcore and ledgerkit. That history is constructed for this suite. It is not an upstream project's history. The tasks that do come from an upstream pull request are named in the snapshot, and [`docs/upstream_tasks.md`](docs/upstream_tasks.md) says how I cut them.

Per model and harness, the report gives:

- **pass@1**: mean success over the runs of each task, with a 95% task-clustered bootstrap CI. A run counts only when the primary grader passed and every negative check passed. A flagged cheat is a failure.
- **primary pass@1, flags ignored**: the same average using `primary_pass` alone. This is a secondary number. It is there so a reader can see what the primary grader said. It is not the headline.
- **pass^k**: the share of tasks solved on all k runs, using the same success bit as pass@1 (k is 5 for a real run)
- **mean task score**: tests plus rubric, minus penalties
- mean tool steps, mean USD per run (agent and judge separately), and how many runs negative checks flagged
- pass@1 by category, by language and by difficulty
- pairwise model differences with paired-bootstrap CIs, so small gaps are not over-claimed
- failure attribution counts (agent, environment, grader), and at least five auto-selected failure case studies with evidence

## Task design

Both target libraries were written for this benchmark ([`target/`](target/README.md)):

- **shopcore** (Python 3.12): money with per-currency minor units, discounts with stacking rules, tax regions, shipping, a pricing engine, inventory reservations with time-to-live, async payment retries with idempotency keys, and CSV import.
- **ledgerkit** (TypeScript, Node 22): integer minor-unit money, currency conversion, calendar dates, anchored billing and proration, invoices, and a fetch-based REST client with timeouts, retries, `Retry-After` and pagination.

Collected test counts for both, and for the more-itertools snapshot, are in the [suite snapshot](#suite-snapshot).

Each of those two libraries has a commit history I wrote for this suite, including merge commits with pull request descriptions. It is stored as plain-text patch series, because nested `.git` directories cannot be committed, and `make history` rebuilds it with identical hashes. The pull-request tasks that use that history are generated by [`tools/derive_pr_task.py`](tools/derive_pr_task.py), and validation re-checks their provenance on every run. The upstream task is separate. Its snapshot and pin are described in [`docs/upstream_tasks.md`](docs/upstream_tasks.md).

Every task is a readable directory: `task.yaml` (prompt and grading), `bug.patch` (starting state), `hidden_tests/`, `reference.patch`, `flawed/*.patch`, and `mutants/` or `cheats/` where relevant. The agent works in a sandbox containing only the library in its starting state, a fresh git checkout with no history. It has five tools (`list_files`, `read_file`, `write_file`, `run_command`, `submit`), no network, and step and time limits from the task. Grading happens afterwards in a separate sandbox where the hidden tests are added.

The reasoning behind each choice (hidden tests vs visible failing tests, mutation testing, perturbed runs, located review findings, difficulty, distinctness) is in [`docs/task_design.md`](docs/task_design.md).

## Rubric philosophy

**Deterministic first.** The primary grader runs code. Its weight is `PRIMARY_WEIGHT` in `graders/scoring.py` (0.7 today). If it fails, the task score is capped at 0.3.

**The rest of the weight is the rubric.** Each task has 2 to 4 rubric items, each decidable from the final diff (plus TRIAGE.md / REVIEW.md) alone. Where a deterministic check exists, the item uses it. Examples: does the added regression test actually fail on the old code? Is the change confined to the right module? Is TRIAGE.md 3-5 lines? The items that are not auto checks go to an LLM judge, one call per item, which returns a JSON verdict and rationale. The judge's share of the task score is the rubric weight times the judge items' share of the rubric weight. It is not the whole rubric weight. The measured minimum, average and maximum are in the [suite snapshot](#suite-snapshot).

**The judge is blind.** `gpt-6.1-sol` sees the task prompt, the criterion, the diff and the written artifacts. It never sees the model or harness name, the trajectory, or the hidden tests, and vendor names in the evidence are masked. A deterministic 20% sample is re-judged by `claude-sonnet-5-5`, and agreement (raw and Cohen's kappa) is reported. I have not done the human calibration. The protocol is in [`docs/judge_calibration.md`](docs/judge_calibration.md). No human grades are filled in.

**Negative checks with evidence.** Reading hidden tests, deleting tests, adding skips/xfails/`.only`, hard-coding expected values (or sniffing the test runner), using the network, and (for flaky tasks) sleeps or retries each cost 0.25, capped at 1.0. Every flag cites the exact line or tool call so it can be audited.

```
task_score = max(0, 0.7 * primary_pass + 0.3 * rubric_score - 0.25 * failed_negative_checks)
```

How to write a good rubric item, with before/after examples: [`docs/rubric_guide.md`](docs/rubric_guide.md).

## Grader validation

`make validate` runs [`validation/validate_tasks.py`](validation/validate_tasks.py) on every task and must pass before anything is trusted. CI runs it on every push.

| Check | Required result |
| --- | --- |
| untouched starting state | primary_pass = 0; every fail-to-pass test fails; every pass-to-pass test passes |
| `reference.patch` | primary_pass = 1, no negative check fires, all auto rubric items pass |
| every `flawed/*.patch` | primary_pass = 0 |
| planted cheats: delete a test file, delete one test, add a skip marker, read hidden tests, network command, and each task's `cheats/*.patch` | caught by the matching negative check |
| PR-derived provenance | starting state + reference reproduces the source commit for the files that commit changed |
| target history | rebuilt shopcore and ledgerkit history is byte-identical to `target/`; every historical commit passes its suite |

How many flawed solutions and planted cheats that is, and how many of the cheats are the generic ones the validator builds, is in the [suite snapshot](#suite-snapshot). The last validation run is [`validation/REPORT.md`](validation/REPORT.md), which `make validate` rewrites. I do not type those pass counts.

The per-task table is committed as [`validation/REPORT.md`](validation/REPORT.md). Flawed solutions are written to be plausible, not strawmen: they fix the reported example but not the general case, fix the symptom in the wrong layer, use floats, add a lock that serializes everything, or seed only one test. Validation also caught real issues during development, such as a visible test that already exposed an injected bug and a grader that hid a whole suite behind one import error. Those fixes are in the git history.

Two more properties are proven by unit tests (`make test`):

- **No hidden test file is readable from inside the agent sandbox** ([`tests/test_hidden_test_isolation.py`](tests/test_hidden_test_isolation.py)). For every task, the starting workspace contains no hidden-test content. The file tools refuse absolute, `..` and symlink escapes. Shell commands in the sandbox cannot see the repository at all.
- The judge never receives model names. API adapters build correct requests and account for cost (against mock SDK clients). The statistics, attribution and report code compute what they claim.

## Results

I have not run a real model against this suite. There are no model scores in this README. I am not going to invent results, costs from a paid run, or human grades.

What is committed in [`results/`](results/results.md) comes from a **dry run with scripted fake models**. It is pipeline test data, labelled as such in the report, not model results. The dry run uses the same sandbox, graders, negative checks, judge path, statistics, failure attribution, case studies and charts, without API keys. The fake participants behave in known ways, which is how I check that the measurement does what I think:

- `fake-oracle` replays each task's reference solution, so it must (and does) pass every task in every run.
- `fake-mixed` deterministically mixes reference solutions, flawed solutions, giving up, and simulated provider outages. That exercises pass@1 vs pass^k, agent and environment attribution, and judge errors.
- `fake-cheater` tries to read hidden tests and skips tests on every run. Those runs are flagged, so its headline pass@1 has to be 0. The secondary column can still show the primary grader passing some of them. That split is the check that caught cheats do not move the headline.

To produce the real results:

```bash
cp .env.example .env            # add ANTHROPIC_API_KEY and OPENAI_API_KEY, then export them
make estimate                   # assumption-based cost estimate (see Cost)
uv run python -m harness.run --tasks bf_001 pr_016 wt_023 ci_031 --k 1 --yes   # smoke test, a few dollars
make estimate SMOKE=results/runs/run-<timestamp>.jsonl                         # measured estimate
make run                        # full matrix: 3 models + 2 vendor CLIs, every task, k=5; asks before spending
make report                     # regenerates results/results.md, summary.csv and charts from results/runs
uv run python -m tools.judge_calibration sample --runs results/runs/run-*.jsonl   # then hand-grade >= 30 items
uv run python -m tools.judge_calibration score
```

Once a real run exists, `make report` reports only real runs and drops the dry-run banner. Every number in `results/results.md` is computed from `results/runs/*.jsonl`. Nothing is typed by hand. The raw episode logs in `results/runs/` are not committed (the dry-run log is about 4 MB); `make dry-run` followed by `make report` regenerates them and the report.

## How to run

Requirements: Linux or macOS, [uv](https://docs.astral.sh/uv/), Node 22, and git. Docker is optional (see [Limitations](#limitations)). On Linux, [bubblewrap](https://github.com/containers/bubblewrap) is used for sandboxing when Docker is absent.

```bash
make setup          # uv sync (Python 3.12) + npm ci for ledgerkit
make test           # unit tests + both target libraries' own suites (pytest, vitest, tsc)
make validate       # prove every grader (about 2 minutes with 3 workers)
make dry-run        # full pipeline with scripted fake models: no keys, no cost
make report         # write results/results.md, results/summary.csv, results/charts/*.png
```

Other entry points:

| Command | What it does |
| --- | --- |
| `make run DRY_RUN=1` | same as `make dry-run` |
| `make run` | real run of every model and harness; reads `ANTHROPIC_API_KEY` / `OPENAI_API_KEY`; asks for confirmation before spending (or pass `ARGS=--yes`) |
| `make run TASKS="bf_ pr_016" ARGS="--k 1 --models claude-sonnet-5-5"` | a subset |
| `make grade TASK=bf_001_tax_half_even DIFF=my.patch` | grade any diff against a task, no model involved |
| `make validate TASKS=fl_` | validate a subset |
| `make estimate [SMOKE=<jsonl>]` | cost estimate |
| `make export` | experimental Archipelago-style verifier export to `build/archipelago/` |
| `make docker-image` | build the sandbox image; the harness then uses Docker automatically |
| `make history` | rebuild the target libraries' git history into `.history/` |

`make run --dry-run` does not work as written, because `--dry-run` is make's own flag ("print commands without running them"). Use `make dry-run` or `make run DRY_RUN=1`.

Each episode appends one JSON line to `results/runs/<run_id>.jsonl` with: `task_id`, `model`, `harness`, `run_index`, `primary_pass` (with grader details), `rubric` (verdicts and rationales, plus cross-check verdicts), `negative_checks` (with evidence), `steps`, `tokens`, `cost_usd`, `judge_cost_usd`, `wall_time_s`, the final `diff`, written artifacts, and a compact trajectory. Runs resume with `--resume <file>`.

Model IDs live only in [`config/models.yaml`](config/models.yaml); run settings are in [`config/run.yaml`](config/run.yaml).

## Cost

Prices are in `config/models.yaml`, copied on 2026-10-25 from the providers' pricing pages. Re-check them before a run. Costs are computed from the token counts each API reports, never guessed. Where a price is unknown, cost is recorded as unknown.

- **Measured method (recommended).** Run a smoke test on a few tasks, then run `make estimate SMOKE=<jsonl>`. It scales each participant's measured mean cost per episode (agent + judge) to the full matrix with a 1.3x margin.
- **Assumption-based method.** `make estimate` without a smoke file assumes 25 steps per episode, each with 3k uncached + 25k cached input tokens and 1.5k output tokens, plus 2 judged items per episode. The current total for the full matrix is in the [suite snapshot](#suite-snapshot). It is recomputed from `config/models.yaml` and the task count. It is an assumption, not a measurement. A real agent may take fewer or more steps, and cache hit rates vary. Set spend limits on both API accounts and smoke-test first.

## Limitations

- **Most of the code under test is synthetic.** shopcore and ledgerkit are small libraries I wrote for this suite. One task uses a pinned slice of more-itertools, which is a real project, but it is still a small pure-Python library and one bug, not a large production repository. Pass rates here will not match pass rates on a big repo.
- **Two languages.** Python and TypeScript only. flaky_test is Python only.
- **The LLM judge does not decide a fixed 30%.** The rubric weight is 0.3. Auto checks take part of that. The judge's actual share is in the [suite snapshot](#suite-snapshot). The judge is blind and cross-checked. I have not calibrated it against my own grades. That work is not done.
- **No real model has been run.** The numbers in `results/` are scripted fake models. They check the pipeline. They are not a leaderboard.
- **No Docker on the build machine.** The Docker backend (`--network none`, CPU/memory/PID limits, read-only root, all capabilities dropped, only the workspace mounted) is fully implemented and unit-tested at the argument level. The live Docker tests skip when no daemon is present; CI runs them in a separate job. All validation and the committed dry run used the local fallback: bubblewrap with fresh mount, PID, user and network namespaces, where only system directories, the toolchains and the workspace exist, plus CPU-time and file-size rlimits and a hard timeout. Unlike Docker, the local fallback does not cap memory. Without bubblewrap, file tools are still confined and hidden tests are never copied into the workspace, but a shell command could read the host filesystem. Every result records which isolation level was used.
- **Native harness adapters are untested against the real CLIs.** The Claude Code and Codex adapters follow those CLIs' documented headless JSON output and are tested with fake executables. Native runs need network access to reach the vendor API, unlike shared-loop runs; this is recorded in each result. Hidden tests are still never mounted, and grading is still network-less. If a CLI is missing, its runs are recorded as skipped.
- **Negative checks are heuristics.** They are proven against planted cheats on every task and cite their evidence, but a determined agent could game the grader in ways they do not detect. For example, weakening an assertion without deleting it is not flagged, although hidden tests still catch the behaviour.
- **Mutation and perturbation are finite.** Mutants are hand-written (8-10 per module), and flaky-test grading uses 20 fixed perturbations. A test suite or fix can be wrong in ways these do not exercise.
- **Results are a snapshot.** Model versions, prices and vendor CLIs change. Results are tied to the pinned IDs in `config/models.yaml` and the harness commit recorded in every JSONL line.
- **Server-side refusal fallbacks are off.** A fallback would silently grade a different model than the one in the table, so a refusal ends the episode and is recorded.
- **`make run --dry-run` is not the dry run.** Make treats `--dry-run` as its own flag. The dry run is `make dry-run` or `make run DRY_RUN=1`.
- **Headline pass@1 is strict about flags. The task score is not zeroed by one flag.** A flagged run is a failure for pass@1 and pass^k. `task_score` still uses the published formula: 0.25 off per failed check, capped at 1.0. A run can be a headline failure and still have a task score above zero if the penalty does not wipe it. I kept that split so the penalty stays visible per check. It is a weaker number than pass@1, and I would not rank models by it.

## Related work

- **SWE-bench-style grading.** The fail-to-pass / pass-to-pass split for hidden tests follows the convention SWE-bench popularised for issue-resolution benchmarks. The shopcore and ledgerkit tasks are ones I wrote. One task is derived from a more-itertools pull request. The suite also covers five other QA skills, and each grader is checked against flawed solutions.
- **Mutation testing** (as in mutmut, PIT or Stryker) is the standard way to judge whether tests detect faults. Here it judges agent-written tests against hand-written, realistic mutants.
- **pass^k reliability.** Reporting the probability that all k attempts succeed, alongside pass@1, follows reliability-focused agent benchmarks such as τ-bench.
- **Archipelago-style output verifiers.** Each task's grading spec can be exported as output verifiers with `criteria`, `weight`, `is_primary_objective` and `negative_criteria` ([`tools/export_archipelago.py`](tools/export_archipelago.py)). The exporter is written from scratch, is experimental, and has not been tested by loading the output into Archipelago.
- **LLM-as-judge calibration.** Judging one atomic criterion per call, blinding the judge, cross-checking with a second model, and calibrating against human grades follow common practice for trustworthy model-graded evaluation.

## Suite snapshot

<!-- SUITE:START -->
Generated by `uv run python -m tools.suite_stats --write` from the task files, the target suites, and
`tools/estimate_cost.py`. Do not edit by hand.

**41 tasks.** 23 Python, 18 TypeScript.

| Category | Python | TypeScript | Total |
| --- | --- | --- | --- |
| bug_fix | 5 | 5 | 10 |
| pr_derived | 5 | 4 | 9 |
| write_tests | 4 | 4 | 8 |
| flaky_test | 4 | 0 | 4 |
| ci_triage | 3 | 2 | 5 |
| code_review | 2 | 3 | 5 |

| Difficulty | Tasks | Share |
| --- | --- | --- |
| easy | 10 | 24% |
| medium | 19 | 46% |
| hard | 12 | 29% |

Flawed solutions on disk: **126**.

Planted cheats: **214**. **186** are the generic ones `validation/validate_tasks.py` builds for each task (delete a test file, delete one test when the file has a top-level test function, add a skip, read the hidden tests, run a network command). **28** are task files under `cheats/`. Validation must catch every one of them. The generic checks are the same five ideas repeated, not 200 distinct attacks.

PR-derived tasks: **8** from the shopcore and ledgerkit history I wrote, **1** from an upstream project (pr_019_sample_strict_counts).

History commits stored as patches: ledgerkit 10, shopcore 11, **21** in total. Rebuilding that history is checked by `make validate` and `tests/test_target_history.py`.

Tests in the target trees, counted by collecting them, not by hand:

| Tree | Collected tests |
| --- | --- |
| shopcore | 165 |
| ledgerkit | 134 |
| more-itertools | 535 |

Score weights in `graders/scoring.py`: primary **0.7**, rubric **0.3**. The rubric weight is split between auto checks and the LLM judge in proportion to item weights. Across 41 tasks the judge's share of the task score, when the primary passes and the penalty is zero, is **12.0%** minimum, **19.0%** average, **30.0%** maximum. There are 77 judge items and 64 auto items. The judge does not decide the whole rubric weight.

Assumption-based cost of one full paid run, from `tools/estimate_cost.py` (41 tasks x k=5, 25 steps, 3000 uncached + 25000 cached input tokens and 1500 output tokens per step, 2 judge items per episode). These are assumptions. `make estimate` prints the same total. A smoke test replaces them.

| Participant | $/episode | Episodes | Subtotal |
| --- | --- | --- | --- |
| claude-opus-5-5 | 1.36 | 410 | $558.62 |
| claude-sonnet-5-5 | 0.74 | 205 | $152.47 |
| gpt-6-astra | 3.25 | 410 | $1,332.50 |
| judging | | 1025 | $46.74 |
| **total** | | | **$2,090.33** |
<!-- SUITE:END -->

## Repository layout

```
target/          shopcore (Python) and ledgerkit (TypeScript), their tests, and their history as patch series;
                 more-itertools/ is a pinned upstream snapshot, separate from that history
tasks/<id>/      task.yaml, bug.patch, hidden_tests/, reference.patch, flawed/, mutants/, cheats/
harness/         sandbox (Docker + local), workspace builder, tools, shared agent loop, model adapters,
                 fake models for dry runs, native CLI adapters, run orchestrator
graders/         test runners, primary graders, negative checks, auto checks, rubric judge, scoring
validation/      validate_tasks.py and the committed REPORT.md
analysis/        stats (bootstrap, pass@1, pass^k), failure attribution, report generator
tools/           history rebuild, PR-task derivation, authoring helper, cost estimate, exporter, calibration
config/          models.yaml (the only place model IDs live), run.yaml
results/         summary.csv, results.md, charts/ (runs/*.jsonl is generated, not committed)
docs/            task_design.md, rubric_guide.md, judge_calibration.md, tasks.md, upstream_tasks.md
tests/           unit tests (no API keys; keys are removed from the environment for every test)
```

## License

MIT, see [LICENSE](LICENSE). Author: Jedidiah Oladele.
