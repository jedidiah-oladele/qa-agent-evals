# Judge calibration

The rubric judge (`gpt-6.1-sol`) grades the judge items in the rubric. That is
not a flat 30% of the task score: auto checks take part of the rubric weight.
The measured share is in the README suite snapshot. I only want to trust the
judge after I have compared it to my own grades. This page is where that
comparison will live.

**Status: not done.** I have not run a paid model, so there are no real judge
verdicts to calibrate, and I have not entered any human grades. The table
below is empty on purpose.

## Protocol

1. After the paid run, sample at least 30 judged rubric items, stratified across
   task categories and models (round-robin over (category, model) cells):

   ```bash
   uv run python -m tools.judge_calibration sample --runs results/runs/run-*.jsonl --n 36
   ```

   This writes `docs/judge_calibration.csv`.
2. I grade each item **pass** or **fail** from the same evidence the judge
   saw: the task prompt, the criterion, the final diff, and TRIAGE.md /
   REVIEW.md. To stay blind, I hide the `participant`, `judge_verdict` and
   `judge_rationale` columns while grading.
3. Score agreement (overall, per category, per model, Cohen's kappa):

   ```bash
   uv run python -m tools.judge_calibration score
   ```

   This rewrites the results table below from the CSV.
4. Any criterion where judge and human disagree more than once is rewritten to be
   more observable (see `docs/rubric_guide.md`), and the affected tasks are
   re-validated.

Separately, every run already reports the agreement between the primary judge
and the cross-check judge (`claude-sonnet-5-5` on a deterministic ~20% sample)
in `results/results.md`. Judge-judge agreement is a consistency check, not a
substitute for this human calibration.

## My hand grades

Not filled in. I will grade these after a real run, from the CSV, not from memory.

| Item | Task | Category | Model (hide while grading) | Rubric item | Judge verdict | Human verdict | Note |
| --- | --- | --- | --- | --- | --- | --- | --- |
| C001 | | | | | | | |
| C002 | | | | | | | |
| C003 | | | | | | | |
| C004 | | | | | | | |
| C005 | | | | | | | |
| C006 | | | | | | | |
| C007 | | | | | | | |
| C008 | | | | | | | |
| C009 | | | | | | | |
| C010 | | | | | | | |
| C011 | | | | | | | |
| C012 | | | | | | | |
| C013 | | | | | | | |
| C014 | | | | | | | |
| C015 | | | | | | | |
| C016 | | | | | | | |
| C017 | | | | | | | |
| C018 | | | | | | | |
| C019 | | | | | | | |
| C020 | | | | | | | |
| C021 | | | | | | | |
| C022 | | | | | | | |
| C023 | | | | | | | |
| C024 | | | | | | | |
| C025 | | | | | | | |
| C026 | | | | | | | |
| C027 | | | | | | | |
| C028 | | | | | | | |
| C029 | | | | | | | |
| C030 | | | | | | | |

(The CSV produced by `sample` is the working copy; this table mirrors it for
readers once grading is done.)

## Results

<!-- RESULTS:START -->
_Not measured. I have not run a paid model, and I have not entered hand grades._
<!-- RESULTS:END -->
