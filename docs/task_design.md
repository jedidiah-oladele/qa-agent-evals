# Task design

This page explains how the tasks were built and why. The full list, with one
line per task, is in [`docs/tasks.md`](tasks.md) (generated from the task files).

## What a task is

A task is a directory under `tasks/<id>/`:

```
task.yaml          what the agent sees (prompt) and how it is graded (schema: harness/task.py)
bug.patch          applied to a clean copy of a target library to create the starting state
hidden_tests/      grader-only tests, mirroring the library layout; never in the agent's sandbox
reference.patch    a correct solution; must pass the primary grader and trip no negative check
flawed/*.patch     2+ plausible wrong solutions; each must fail the primary grader
mutants/*.patch    write_tests only: faulty versions of the library the agent's tests must catch
cheats/*.patch     planted reward hacks the negative checks must catch
```

The agent starts in a sandbox containing the target library in the task's
starting state: a git checkout with exactly one commit and no history, no
hidden tests and no access to this repository. It gets five tools
(`list_files`, `read_file`, `write_file`, `run_command`, `submit`), no network,
and a step and time budget. Its final diff is graded in a *separate* sandbox
where the hidden tests are added.

## Target codebases

shopcore and ledgerkit were written for this benchmark. I did not copy them
from an employer or a client. more-itertools is third-party code: one task
vendors a pinned slice of it under the MIT license, with the attribution in
`target/more-itertools/UPSTREAM.md`. Nothing else in the suite is upstream code.

- **shopcore** (Python 3.12): money with per-currency minor units and
  cent-exact allocation, discounts with priority/stacking rules, tax regions
  with reduced/exempt categories and inclusive pricing, weight-based shipping,
  a pricing engine, inventory reservations with time-to-live, async payment
  capture with backoff and idempotency keys, and a CSV product importer.
- **ledgerkit** (TypeScript, Node 22): integer minor-unit money, robust
  rounding, currency conversion with cross rates, zone-free calendar dates,
  anchored billing periods and proration, invoices with a lifecycle, and a
  fetch-based REST client with timeouts, retries, `Retry-After` and pagination.

They are small enough to read in an hour but have the cross-module behaviour
bugs actually have: discounts feed allocation feeds tax; the REST client mixes
timers, abort signals and retries; billing depends on calendar arithmetic. The
collected test counts are in the README suite snapshot.

### History and PR-derived tasks

Each library has a history I wrote, with merged pull requests and written
descriptions. The commit counts are in the README suite snapshot. Because nested `.git`
directories cannot be committed, the history is stored as `git format-patch`
series in `target/history/` and rebuilt deterministically (identical commit
hashes everywhere) by `tools/rebuild_history.py`; `make validate` checks the
rebuilt tree is byte-identical to `target/<lib>`, and the unit tests check that
every historical commit passes its own suite.

A **PR-derived** task on shopcore or ledgerkit is built from one of those
commits by `tools/derive_pr_task.py`: the commit's source changes are reverted
on top of the current library (later commits stay), its tests are removed from
the starting state and become hidden tests, and the PR description becomes the
prompt. The reference solution *is* the commit. On top, each task adds hidden
edge-case tests for behaviour the description promises but the PR's own tests
do not pin. `make validate` checks the provenance on every run: starting state
+ reference must reproduce the commit byte for byte.

An upstream task uses the same graders. The difference is the source of the
code. `docs/upstream_tasks.md` is the procedure. The pin is a commit sha and
the sha256 of each vendored file, and validation checks that the reference
restores the files the pull request changed.

## The six categories

| Category | What it measures | How it is built | Primary grader |
| --- | --- | --- | --- |
| **bug_fix** | Find and fix a defect from an issue report | inject one realistic bug with `bug.patch`; write hidden tests that pin it from several angles plus guard tests | hidden `fail_to_pass` tests must pass and every collected test (`pass_to_pass: tests/`) must stay green |
| **pr_derived** | Implement a change from a pull request description | revert one commit, either from the history I wrote or from a pinned upstream pull request | the PR's own tests + hidden edge cases |
| **write_tests** | Write tests that actually catch bugs | remove a module's tests; write 6-10 realistic mutants of the module | the agent's tests must pass on the clean library and fail on at least the required share of hidden mutants (source edits are discarded before grading) |
| **flaky_test** | Fix the root cause of an intermittent failure | introduce a test that fails depending on order, randomness, time zone or an async race | the whole suite must pass 20 runs in a row with shuffled order (seeds 1000-1019), re-seeded `random`, varying `PYTHONHASHSEED` and a rotating `TZ` |
| **ci_triage** | Diagnose a red CI build from its log, fix it, explain it | inject a cause that shows up as a CI failure; add a realistic CI log under `ci/` | hidden tests; plus a 3-5 line TRIAGE.md graded by rubric |
| **code_review** | Review a pull request and find its defects | apply a feature PR with 1-3 seeded defects (that no test catches) and add `PR.md` + `pr.diff` | REVIEW.md must locate every seeded defect (file + line within a tolerance) with a bounded number of findings that match none |

Why these choices:

- **Hidden tests, not visible failing tests.** Bug-fix agents get an issue, not a
  failing test, like real triage. Where an existing visible test would give the
  bug away, the starting state weakens that one test, modelling the coverage gap
  that let the bug in.
- **`pass_to_pass` is the whole suite.** A fix that breaks a neighbour fails.
  Skipped tests count as not passing, so skipping your way to green fails the
  primary grader as well as the negative check.
- **Mutation testing for test writing.** "Tests pass" is meaningless on its own
  (an empty test passes). Killing hidden mutants measures whether the tests
  would catch real regressions. Only the agent's test file runs against the
  mutants, so other modules' tests cannot do the work for it.
- **Repeated, perturbed runs for flaky tests.** The grader runs with conditions
  the agent cannot see but the code should not care about: order, seeds, hash
  seed, time zone. The perturbations are deterministic (fixed seeds and zone
  rotation), so grading a given diff always gives the same answer, while a
  masking fix (sleep, retry, narrower tolerance) still fails on some run.
- **Located findings for code review.** "Did the review mention the bug?" is
  judged by an LLM, but *whether the right place was flagged* is checked
  deterministically, and invented findings are bounded. Each seeded defect
  also gets a judge rubric item about the explanation.
- **A written root cause for CI triage.** Real triage ends with an explanation
  someone else can act on, so TRIAGE.md is part of the deliverable and its
  length is bounded to force precision.

## Difficulty

- **easy**: one function, the issue points at the behaviour.
- **medium**: needs reproduction and understanding of one module's behaviour.
- **hard**: needs multi-file reasoning or cross-module side effects (for
  example, a cent of drift that only appears where discounts, allocation and
  per-order tax meet, or a retry loop where a timer from one attempt aborts the
  next).

Target spread: about 25% easy, 45% medium, 30% hard; the actual spread is in
`docs/tasks.md`. Both languages appear in every category except flaky_test,
which is Python-only.

## The quality gate

A task ships only if `make validate` proves, on every run:

1. the untouched starting state **fails** the primary grader, every
   `fail_to_pass` test fails at the start, and every `pass_to_pass` test passes
   at the start;
2. the reference **passes** (primary_pass = 1), triggers no negative check and
   passes every auto rubric item;
3. **every** flawed solution fails (primary_pass = 0);
4. planted cheats are caught: deleting a visible test file, deleting a single
   test, adding a skip marker, reading hidden tests, a network command, and the
   task's own `cheats/*.patch` (hard-coded expected values for bug/PR/CI
   tasks, sleeps or retries for flaky tasks);
5. for PR-derived tasks, the provenance check above.

The latest result is committed in [`validation/REPORT.md`](../validation/REPORT.md).

Flawed solutions are written to be plausible, the kind of partial fix a capable
model actually produces: fixing the reported example but not the general case,
fixing the symptom in the wrong layer, floats instead of decimals, an
off-by-one in the fix, a fix that breaks a neighbouring behaviour. A grader that
only rejects strawmen proves little.

## Prompts

Prompts read like real issues, PR descriptions, CI pings or review requests:
specific symptoms, inputs and expected behaviour, no mention of hidden tests,
and no line-by-line fix. Validation rejects prompts that name a hidden test or
hidden test file. Every task is readable on its own: open `task.yaml` for the
prompt and grading, `bug.patch` for the starting state, and `reference.patch`
for the answer.

## Distinctness

Every task tests something different: a different module, a different failure
mode, or a different skill. Two tasks may touch the same module (for example,
inventory expiry appears in a PR-derived task, a bug-fix task and a write-tests
task), but they ask for different work: implementing the feature, repairing a
specific regression in it, and writing tests that would catch regressions.
