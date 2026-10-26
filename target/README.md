# Target codebases

Two libraries I wrote for this suite. Tasks are built from these, plus the
more-itertools snapshot documented in `UPSTREAM.md` under `more-itertools/`.

| Library | Language | Tests | History |
| --- | --- | --- | --- |
| [`shopcore/`](shopcore) | Python 3.12, no runtime deps | pytest | 11 commits, 4 of them merged PRs (#12, #15, #17, #19) |
| [`ledgerkit/`](ledgerkit) | TypeScript, Node 22, ESM | vitest, `tsc --noEmit` | 10 commits, 4 of them merged PRs (#21, #23, #24, #27) |

`target/<lib>/` is always the tip of that library's history: clean code with
a passing test suite. Tasks never edit it; they copy it into a sandbox and
apply their own `bug.patch`.

## Why the history is stored as patches

The commit history is what the shopcore and ledgerkit pull-request tasks are
cut from: each one reverts one of those commits and hands the agent that
commit's pull request description. I wrote the history. It is not an upstream
project. The one task that does come from an upstream project lives in
`target/more-itertools/` and is documented in `docs/upstream_tasks.md`. A
nested `.git` directory cannot be committed inside this repository, and a git
bundle is an opaque binary that cannot be reviewed on GitHub.

So each history is a `git format-patch` series in `history/<lib>/`. It is
plain text, reviewable in a browser, and small. To get real git repositories:

```bash
make history                       # or: uv run python -m tools.rebuild_history
git -C .history/shopcore log --stat
```

`tools/rebuild_history.py` replays the series with `git am` using fixed
identities and dates, so the rebuilt commit hashes are identical on every
machine, and then verifies the rebuilt tree is byte-for-byte identical to
`target/<lib>/`. `make validate` runs this check, and also checks that every
PR-derived task's `reference.patch` is exactly the source half of its commit
(see `tools/derive_pr_task.py`).

Every commit in both series passes its own test suite (and `tsc` for
ledgerkit), which `tests/test_target_history.py` checks.
