# qa-agent-evals

**An evaluation suite that measures whether frontier coding agents can do real QA work.** It has 40 original tasks across two synthetic codebases, one Python and one TypeScript, in six categories: fixing bugs from issue reports, implementing changes from pull-request descriptions, writing tests that catch hidden mutants, fixing flaky tests at the root cause, triaging red CI builds, and reviewing pull requests for seeded defects. Deterministic graders decide pass or fail. A small, explicit rubric judged by an LLM adds detail. Negative checks penalise gaming the grader. Before any model runs, every grader is proven: on every task, a reference solution must pass, every one of 123 plausible flawed solutions must fail, and planted cheats must be caught. The harness runs `claude-opus-5-5`, `claude-sonnet-5-5` and `gpt-6-astra` through one shared tool loop, plus the vendors' own coding-agent CLIs where they run headless. It reports pass@1 and pass^k with 95% bootstrap confidence intervals and labels every failure as an agent, environment or grader error. **Status:** the pipeline is complete and validated, and runs end to end without API keys. Real model results are pending a paid run (see [Results](#results)).

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
- [Repository layout](#repository-layout)
- [License](#license)

## Problem

Coding agents do well on fix-the-failing-test benchmarks, but QA work is wider and easier to fake. An agent can make a suite green by deleting the inconvenient test, skipping it, special-casing the expected value, or adding a sleep until the flaky test passes. Tests it writes can pass without catching anything. A code review can sound plausible while missing the actual bug. A benchmark that only checks "tests pass" rewards all of this.

This repository measures QA skills directly, and is built so that gaming the grader does not pay. Hidden tests are never visible from the agent's sandbox, with a unit test that proves it for every task. Written tests are judged by whether they kill mutants. Flaky-test fixes are judged by 20 perturbed runs. Reviews are judged by whether they locate the seeded defects. Each grader is validated against flawed and cheating solutions before it is trusted.

## What is measured

| Category | Tasks | The agent gets | It must | Primary (deterministic) grader |
| --- | --- | --- | --- | --- |
| **bug_fix** | 10 | an issue report and the repo | fix the bug (and add a regression test) | hidden fail-to-pass tests pass; the whole suite stays green |
| **pr_derived** | 8 | a real PR description from the repo's history, with the commit reverted | implement the PR | the PR's own tests + hidden edge-case tests |
| **write_tests** | 8 | a module whose tests were deleted | write tests | tests pass on clean code and kill >= 75-80% of 8-10 hidden mutants |
| **flaky_test** | 4 | an intermittently failing suite | remove the root cause (no sleeps, retries, skips) | suite green in 20 runs with shuffled order, re-seeded randomness, varied hash seed and time zone |
| **ci_triage** | 5 | a red CI log and the repo | fix the cause and write a 3-5 line TRIAGE.md | hidden tests; the root cause write-up is graded by the rubric |
| **code_review** | 5 | a PR (`PR.md` + `pr.diff`) with 1-3 seeded defects | write REVIEW.md, one located finding per defect | every seeded defect located by file:line; at most 2 findings that match none |

Both languages appear in every category except flaky_test (Python only). The spread is 10 easy, 18 medium and 12 hard tasks (25/45/30%). The full list is in [`docs/tasks.md`](docs/tasks.md).

Per model and harness, the report gives:

- **pass@1**: mean primary pass over k = 5 runs per task, with a 95% task-clustered bootstrap CI
- **pass^5**: the share of tasks solved in all 5 runs (reliability)
- **mean task score**: tests plus rubric, minus penalties
- mean tool steps, mean USD per run (agent and judge separately), and how many runs negative checks flagged
- pass@1 by category, by language and by difficulty
- pairwise model differences with paired-bootstrap CIs, so small gaps are not over-claimed
- failure attribution counts (agent, environment, grader), and at least five auto-selected failure case studies with evidence

## Task design

Both target libraries were written for this benchmark ([`target/`](target/README.md)):

- **shopcore** (Python 3.12): money with per-currency minor units, discounts with stacking rules, tax regions, shipping, a pricing engine, inventory reservations with time-to-live, async payment retries with idempotency keys, and CSV import. 165 tests.
- **ledgerkit** (TypeScript, Node 22): integer minor-unit money, currency conversion, calendar dates, anchored billing and proration, invoices, and a fetch-based REST client with timeouts, retries, `Retry-After` and pagination. 134 tests.

Each library has a real commit history with merged pull requests. It is stored as plain-text patch series, because nested `.git` directories cannot be committed, and `make history` rebuilds it with identical hashes. PR-derived tasks are generated from that history by [`tools/derive_pr_task.py`](tools/derive_pr_task.py), and validation re-checks their provenance on every run.

Every task is a readable directory: `task.yaml` (prompt and grading), `bug.patch` (starting state), `hidden_tests/`, `reference.patch`, `flawed/*.patch`, and `mutants/` or `cheats/` where relevant. The agent works in a sandbox containing only the library in its starting state, a fresh git checkout with no history. It has five tools (`list_files`, `read_file`, `write_file`, `run_command`, `submit`), no network, and step and time limits from the task. Grading happens afterwards in a separate sandbox where the hidden tests are added.

The reasoning behind each choice (hidden tests vs visible failing tests, mutation testing, perturbed runs, located review findings, difficulty, distinctness) is in [`docs/task_design.md`](docs/task_design.md).

## Rubric philosophy

**Deterministic first.** The primary grader runs code and is worth 70% of the score. If it fails, the task score is capped at 0.3.

**Small, atomic rubric for the rest (30%).** Each task has 2 to 4 rubric items, each decidable from the final diff (plus TRIAGE.md / REVIEW.md) alone. Where a deterministic check exists, the item uses it. Examples: does the added regression test actually fail on the old code? Is the change confined to the right module? Is TRIAGE.md 3-5 lines? The rest go to an LLM judge, one call per item, which returns a JSON verdict and rationale.

**The judge is blind.** `gpt-6.1-sol` sees the task prompt, the criterion, the diff and the written artifacts. It never sees the model or harness name, the trajectory, or the hidden tests, and vendor names in the evidence are masked. A deterministic 20% sample is re-judged by `claude-sonnet-5-5`, and agreement (raw and Cohen's kappa) is reported. Human calibration on at least 30 items is set up in [`docs/judge_calibration.md`](docs/judge_calibration.md), pending the owner's hand grades.

**Negative checks with evidence.** Reading hidden tests, deleting tests, adding skips/xfails/`.only`, hard-coding expected values (or sniffing the test runner), using the network, and (for flaky tasks) sleeps or retries each cost 0.25, capped at 1.0. Every flag cites the exact line or tool call so it can be audited.

```
task_score = max(0, 0.7 * primary_pass + 0.3 * rubric_score - 0.25 * failed_negative_checks)
```

How to write a good rubric item, with before/after examples: [`docs/rubric_guide.md`](docs/rubric_guide.md).

## Grader validation

`make validate` runs [`validation/validate_tasks.py`](validation/validate_tasks.py) on every task and must pass before anything is trusted. CI runs it on every push.

| Check | Required result | Result (40 tasks) |
| --- | --- | --- |
| untouched starting state | primary_pass = 0; every fail-to-pass test fails; every pass-to-pass test passes | 40/40 |
| `reference.patch` | primary_pass = 1, no negative check fires, all auto rubric items pass | 40/40 |
| every `flawed/*.patch` (123 total, 3-4 per task) | primary_pass = 0 | 123/123 fail |
| planted cheats: delete a test file, delete one test, add a skip marker, read hidden tests, network command, task-specific cheat patch (hard-coded values, sleeps/retries) | caught by the matching negative check | 209/209 caught |
| PR-derived provenance | starting state + reference reproduces the source commit byte for byte | 8/8 |
| target history | rebuilt history is byte-identical to `target/`; every historical commit passes its suite | 21/21 commits |

The per-task table is committed as [`validation/REPORT.md`](validation/REPORT.md). Flawed solutions are written to be plausible, not strawmen: they fix the reported example but not the general case, fix the symptom in the wrong layer, use floats, add a lock that serializes everything, or seed only one test. Validation also caught real issues during development, such as a visible test that already exposed an injected bug and a grader that hid a whole suite behind one import error. Those fixes are in the git history.

Two more properties are proven by unit tests (`make test`):

- **No hidden test file is readable from inside the agent sandbox** ([`tests/test_hidden_test_isolation.py`](tests/test_hidden_test_isolation.py)). For every task, the starting workspace contains no hidden-test content. The file tools refuse absolute, `..` and symlink escapes. Shell commands in the sandbox cannot see the repository at all.
- The judge never receives model names. API adapters build correct requests and account for cost (against mock SDK clients). The statistics, attribution and report code compute what they claim.

## Results

**Real model results are pending the owner's paid run.** No real model has been run against this suite yet, so this README contains no model numbers. I won't fabricate or estimate results, costs or human grades.

What is committed in [`results/`](results/results.md) comes from a **dry run with scripted fake models**: pipeline test data, clearly labelled as such in every file, not model results. The dry run exercises the real sandbox, graders, negative checks, judge path, statistics, failure attribution, case studies and charts without API keys. Its fake participants behave in known ways, which makes it a sanity check of the measurement:

- `fake-oracle` replays each task's reference solution, so it must (and does) pass every task in every run.
- `fake-mixed` deterministically mixes reference solutions, flawed solutions, giving up, and simulated provider outages. That exercises pass@1 vs pass^k, agent and environment attribution, and judge errors.
- `fake-cheater` tries to read hidden tests and skips tests, so every one of its runs must be flagged by the negative checks.

To produce the real results:

```bash
cp .env.example .env            # add ANTHROPIC_API_KEY and OPENAI_API_KEY, then export them
make estimate                   # assumption-based cost estimate (see Cost)
uv run python -m harness.run --tasks bf_001 pr_016 wt_023 ci_031 --k 1 --yes   # smoke test, a few dollars
make estimate SMOKE=results/runs/run-<timestamp>.jsonl                         # measured estimate
make run                        # full matrix: 3 models + 2 vendor CLIs, 40 tasks, k=5; asks before spending
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
- **Assumption-based method.** `make estimate` without a smoke file assumes 25 steps per episode, each with 3k uncached + 25k cached input tokens and 1.5k output tokens, plus 2 judged items per episode. For the full matrix (40 tasks x k=5 x 3 models + 2 vendor CLIs, plus judging) that comes to **about $2,000**:

  | Participant | Assumed $/episode | Episodes | Subtotal |
  | --- | --- | --- | --- |
  | claude-opus-5-5 | 1.36 | 400 (shared loop + Claude Code) | ~$545 |
  | claude-sonnet-5-5 | 0.74 | 200 | ~$149 |
  | gpt-6-astra | 3.25 | 400 (shared loop + Codex CLI) | ~$1,300 |
  | judging | | 1,000 | ~$46 |

  These are assumptions, not measurements. Real agents may take fewer or more steps, and cache hit rates vary. Set spend limits on both API accounts and smoke-test first.

## Limitations

- **Synthetic codebases.** Both libraries are small and original. Real production repositories are bigger, messier and have more context to find. The tasks test skills that transfer, but absolute pass rates here will not match pass rates on real repos.
- **Two languages.** Python and TypeScript only. flaky_test is Python only.
- **The LLM judge decides 30% of the score.** It is blind and cross-checked, but human calibration is still pending (the owner's hand grades are not in yet).
- **No Docker on the build machine.** The Docker backend (`--network none`, CPU/memory/PID limits, read-only root, all capabilities dropped, only the workspace mounted) is fully implemented and unit-tested at the argument level. The live Docker tests skip when no daemon is present; CI runs them in a separate job. All validation and the committed dry run used the local fallback: bubblewrap with fresh mount, PID, user and network namespaces, where only system directories, the toolchains and the workspace exist, plus CPU-time and file-size rlimits and a hard timeout. Unlike Docker, the local fallback does not cap memory. Without bubblewrap, file tools are still confined and hidden tests are never copied into the workspace, but a shell command could read the host filesystem. Every result records which isolation level was used.
- **Native harness adapters are untested against the real CLIs.** The Claude Code and Codex adapters follow those CLIs' documented headless JSON output and are tested with fake executables. Native runs need network access to reach the vendor API, unlike shared-loop runs; this is recorded in each result. Hidden tests are still never mounted, and grading is still network-less. If a CLI is missing, its runs are recorded as skipped.
- **Negative checks are heuristics.** They are proven against planted cheats on every task and cite their evidence, but a determined agent could game the grader in ways they do not detect. For example, weakening an assertion without deleting it is not flagged, although hidden tests still catch the behaviour.
- **Mutation and perturbation are finite.** Mutants are hand-written (8-10 per module), and flaky-test grading uses 20 fixed perturbations. A test suite or fix can be wrong in ways these do not exercise.
- **Results are a snapshot.** Model versions, prices and vendor CLIs change. Results are tied to the pinned IDs in `config/models.yaml` and the harness commit recorded in every JSONL line.
- **Server-side refusal fallbacks are deliberately off.** A fallback would silently grade a different model than the one in the table, so a refusal ends the episode and is recorded.

Nothing from the brief was dropped. One adjustment: `make run --dry-run` is exposed as `make dry-run` / `make run DRY_RUN=1`, because make reserves `--dry-run` (see [How to run](#how-to-run)).

## Related work

- **SWE-bench-style grading.** The fail-to-pass / pass-to-pass split for hidden tests follows the convention SWE-bench popularised for issue-resolution benchmarks. Tasks here are original, include five other QA skills, and validate each grader against flawed solutions.
- **Mutation testing** (as in mutmut, PIT or Stryker) is the standard way to judge whether tests detect faults. Here it judges agent-written tests against hand-written, realistic mutants.
- **pass^k reliability.** Reporting the probability that all k attempts succeed, alongside pass@1, follows reliability-focused agent benchmarks such as τ-bench.
- **Archipelago-style output verifiers.** Each task's grading spec can be exported as output verifiers with `criteria`, `weight`, `is_primary_objective` and `negative_criteria` ([`tools/export_archipelago.py`](tools/export_archipelago.py)). The exporter is written from scratch, is experimental, and has not been tested by loading the output into Archipelago.
- **LLM-as-judge calibration.** Judging one atomic criterion per call, blinding the judge, cross-checking with a second model, and calibrating against human grades follow common practice for trustworthy model-graded evaluation.

## Repository layout

```
target/          shopcore (Python) and ledgerkit (TypeScript), their tests, and their history as patch series
tasks/<id>/      task.yaml, bug.patch, hidden_tests/, reference.patch, flawed/, mutants/, cheats/
harness/         sandbox (Docker + local), workspace builder, tools, shared agent loop, model adapters,
                 fake models for dry runs, native CLI adapters, run orchestrator
graders/         test runners, primary graders, negative checks, auto checks, rubric judge, scoring
validation/      validate_tasks.py and the committed REPORT.md
analysis/        stats (bootstrap, pass@1, pass^k), failure attribution, report generator
tools/           history rebuild, PR-task derivation, authoring helper, cost estimate, exporter, calibration
config/          models.yaml (the only place model IDs live), run.yaml
results/         summary.csv, results.md, charts/ (runs/*.jsonl is generated, not committed)
docs/            task_design.md, rubric_guide.md, judge_calibration.md, tasks.md
tests/           unit tests (no API keys; keys are removed from the environment for every test)
```

## License

MIT, see [LICENSE](LICENSE). Author: Jedidiah Oladele.
