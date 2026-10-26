# more-itertools snapshot

This directory is a pinned slice of [more-itertools](https://github.com/more-itertools/more-itertools) at merge commit `7b9889c0b7de2189e7dd77688f7a811ce43337cc` (pull request 944, merged 2025-01-11). The parent of that merge is `18225d856665bfc3bfdfcdbfa585290f92645daf`, which is the broken baseline.

more-itertools is MIT licensed. The copyright is Erik Rose's, 2012, plus later contributors. `LICENSE` is the upstream license text, unchanged. I did not write this library.

## What is in the snapshot

Copied byte for byte from that commit:

- `more_itertools/__init__.py`
- `more_itertools/more.py`
- `more_itertools/recipes.py`
- `more_itertools/py.typed`
- `tests/__init__.py`
- `tests/test_more.py`
- `LICENSE`

`pytest.ini` is mine. It only sets `pythonpath = .` so pytest can import the package without an install. It is not part of the pin.

## What I left out

I did not vendor `docs/`, the stub files, `tests/test_recipes.py`, or the project metadata (`pyproject.toml`, `setup.cfg`). `tests/test_recipes.py` is not needed to grade this fix, and on Python 3.12 it skips `TransposeTests.test_incompatible_allow`. This harness counts a skip as a failure, so I left that file out rather than edit it. `recipes.py` is still here because `more_itertools/__init__.py` imports it.

The sha256 of each pinned file is in `tasks/pr_019_sample_strict_counts/task.yaml`. `make validate` checks those hashes, and checks that the task's starting state plus `reference.patch` restores `more.py` and `tests/test_more.py` to the pinned bytes.

How the task was built is in `docs/upstream_tasks.md`.
