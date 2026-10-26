# Upstream pull requests

Most `pr_derived` tasks come from the commit history I wrote for shopcore and ledgerkit. That history is not an upstream project. This page is the other kind: a task cut from a merged pull request in a project I do not maintain.

The task format is the same one `tasks/*/task.yaml` already uses. `make validate` still has to show that the untouched start fails, the reference passes, every flawed patch fails, and the planted cheats are caught. For an upstream task it also checks the pin: the vendored files match the recorded sha256, and `reference.patch` puts the files the pull request changed back to the pinned commit.

## How I build one

1. Pick a merged pull request that fixes a small bug and adds a test, in a permissive license, with no extra runtime dependencies. Record the merge commit and its first parent. The parent is the broken code. The merge commit is the fixed code.
2. Download that commit (a GitHub tarball is enough). Copy in the files required to run the affected tests. Leave out docs, packaging metadata, and tests that skip on Python 3.12, and say so in the snapshot's `UPSTREAM.md`. Do not edit the copied source to make the bug easier.
3. Add a `pytest.ini` with `pythonpath = .` if the project is not installed. That file is not part of the pin.
4. `bug.patch` is the reverse of the pull request's change to those files, applied to the fixed snapshot. The agent's starting tree is the parent commit for the files the pull request touched.
5. `reference.patch` is that change applied forward, including the test the pull request added. Hidden tests are the new behaviour plus any edge the pull request's own test does not pin. Edges go in `hidden_tests/` and are not part of the upstream commit. Say that in the task.
6. If the pull request body is the patch ("move this line"), do not paste it into the prompt. The prompt should say what the code does wrong and what it should do. Keep the original title.
7. Write flawed patches that are wrong in a way a careful reading could still produce, and a `cheats/hardcode.patch` that special-cases a distinctive literal from a hidden test.
8. Fill `source.upstream` in `task.yaml`. `make validate TASKS=<id>` checks the pin and the graders.

## pr_019, more-itertools #944

- Repository: https://github.com/more-itertools/more-itertools
- License: MIT
- Pull request: https://github.com/more-itertools/more-itertools/pull/944
- Merge commit: `7b9889c0b7de2189e7dd77688f7a811ce43337cc`
- Parent: `18225d856665bfc3bfdfcdbfa585290f92645daf`
- Snapshot: `target/more-itertools/`

The bug is in `_sample_counted`. The `strict` check sat inside `with suppress(StopIteration)`, so when `feed()` ran out of counts it raised `StopIteration`, the suppressor swallowed it, and the `ValueError` never ran. The pull request moves the check to after that block. I did not put that instruction in the prompt. The pull request body is the instruction. The prompt states the behaviour the new test checks, and the extra hidden tests reject a fix that only compares `len(iterable)` to `k`. The pull request's own test uses `'abcde'` with `k=10`, where those two numbers disagree, so that test alone does not catch the wrong fix.

`reference.patch` is the pull request's hunks for `more_itertools/more.py` and `tests/test_more.py`. The hidden file is not in the upstream commit.
