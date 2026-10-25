# Rubric guide

How tasks in this repository are graded, and how to write a rubric item that a
reviewer (human or model) can grade the same way twice.

## The order of trust

1. **Deterministic graders decide pass or fail.** Every task has a *primary*
   grader that runs code: hidden tests, mutation testing, repeated shuffled runs,
   or exact location matching for code-review findings. It is worth 70% of the
   task score and gates the rest: if the primary fails, the task score is capped
   at 0.3.
2. **Auto rubric items** are deterministic checks that are not about the main
   behaviour: did the agent add a regression test that actually fails on the old
   code, did it keep its change inside the right module, is TRIAGE.md 3 to 5 lines.
3. **Judge rubric items** are the remainder: properties that matter but cannot be
   tested mechanically, such as whether a written root cause names the actual
   cause, or whether a fix uses the library's rounding helper instead of a
   special case. They are graded by an LLM, one call per item.
4. **Negative checks** subtract a fixed 0.25 each (capped at 1.0) when an agent
   games the grader: reading hidden tests, deleting or skipping tests,
   hard-coding expected values, using the network, masking flaky tests with
   sleeps or retries.

Rubric items together are worth 30% of the task score:

```
task_score = max(0, 0.7 * primary_pass + 0.3 * rubric_score - 0.25 * failed_negative_checks)
             (capped at 0.3 when primary_pass = 0; penalty capped at 1.0)
```

## What makes a good rubric item

A rubric item is **atomic** and **observable**: a reader with only the task
prompt, the final diff and any TRIAGE.md / REVIEW.md can say pass or fail
without guessing what the author meant.

| Avoid | Prefer |
| --- | --- |
| "The fix is clean and idiomatic." | "Per-line tax is rounded with the library's half-up policy at the currency's minor unit, not by float rounding, a hard-coded two-decimal quantum, or special cases for particular amounts." |
| "Good root cause analysis." | "TRIAGE.md says the failure comes from `fromDate` using local-time getters, which shifts the date by one day when the runner's TZ is west of UTC." |
| "Tests are thorough." | "The diff adds a test that fails on the original code and passes after the fix." (auto: `regression_test`) |
| "Doesn't break anything." | Covered by `pass_to_pass` in the primary grader, not the rubric. |
| One item checking three things | Three items, or drop the two a test already covers. |

Rules of thumb:

- **Two to four items per task.** More items dilute each one and slow review.
- **Name the evidence.** Say which file, function or behaviour the reader should
  look at. Name the wrong approaches you expect, so "no" is as clear as "yes".
- **Never restate the primary grader.** If a hidden test can check it, it belongs
  in the hidden tests.
- **Prefer an auto check when one exists.** `regression_test`, `diff_scope`,
  `touches`, `doc_lines`, `tests_only`, `min_tests`, `review_false_positives`
  and `review_format` are deterministic (see `graders/auto_checks.py`).
- **Weights express importance, not difficulty.** A correctness-adjacent item
  can weigh 1.0, a hygiene item 0.5.
- **The reference must pass every auto item.** `make validate` enforces it.

## Category patterns

| Category | Primary grader | Typical rubric |
| --- | --- | --- |
| bug_fix | hidden fail_to_pass + pass_to_pass tests | judge: the fix addresses the cause at the right layer; auto: regression test; auto: diff scope |
| pr_derived | the PR's own tests + hidden edge-case tests | judge: a specific design property the PR description asks for; auto: tests added |
| write_tests | tests pass on clean code and kill >= N% of hidden mutants | auto: only test files changed; auto: minimum test count; judge: a named behaviour is asserted |
| flaky_test | suite green in 20 shuffled runs (order, seeds, hash seed, time zone) | judge: root cause removed, not masked; auto: diff scope |
| ci_triage | hidden tests | auto: TRIAGE.md is 3-5 lines; judge: TRIAGE.md names the real cause |
| code_review | every seeded defect located, bounded false positives | judge: one item per defect (explains the impact); auto: false-positive bound or format |

## The judge

- One call per rubric item with a fixed system prompt (`graders/rubric_judge.py`)
  that asks for strict grading and a JSON verdict: `{"verdict": "pass" | "fail",
  "rationale": "..."}`. Unparseable replies are retried once, then recorded as
  `error` (scored as fail and attributed as a grader error, never silently).
- The judge sees the task prompt, the criterion, the final diff and the written
  artifacts. It never sees the model or harness name, the trajectory or the
  hidden tests. Vendor and model names in the evidence are masked as an extra
  guard.
- The primary judge is `gpt-6.1-sol`. A deterministic ~20% sample of items is
  re-judged by `claude-sonnet-5-5`, and agreement (raw and Cohen's kappa) is
  reported in every results file.
- Human calibration of at least 30 items is tracked in `docs/judge_calibration.md`.

## Negative checks

| Check | Fires when | Evidence recorded |
| --- | --- | --- |
| `no_hidden_test_access` | a tool call references hidden tests or the task directory, or tries a path outside the workspace | the step and the call |
| `no_test_deletion` | a test file is deleted or moved out of the suite, or a modified test file ends up with fewer tests | file and test names |
| `no_skip_or_xfail` | added lines skip, xfail, deselect, `.only` or exclude tests | file:line and pattern |
| `no_hardcoded_expected_values` | added source lines branch on or return a distinctive literal from the tests, or detect the test runner (`PYTEST_CURRENT_TEST`, `process.env.VITEST`, ...) | file:line and the literal |
| `no_network` | a command installs packages, downloads or calls a URL, or added code imports a network client | the command or file:line |
| `no_retry_or_sleep_masking` (flaky tasks) | added lines sleep, retry or rerun | file:line |

Checks are heuristics with evidence, not verdicts handed down in secret: every
flag names the exact line or call so a reviewer can overturn it. Each check is
proven on every task by planted cheats during `make validate`, and every
reference solution is proven to trigger none of them.
