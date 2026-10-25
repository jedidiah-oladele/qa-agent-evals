"""Reliability statistics: pass@1, pass^k, task-clustered bootstrap CIs.

Runs of the same task are not independent samples, so every confidence
interval resamples *tasks* (with replacement) and keeps each task's runs
together (a cluster bootstrap). With k runs per task:

* pass@1  - mean over tasks of the per-task success rate c/n.
* pass^k  - mean over tasks of C(c, k) / C(n, k): the probability that k runs
            drawn from the n observed all succeed (the unbiased estimator
            used for reliability metrics; equals "all k passed" when n == k).
* pass@k  - mean over tasks of 1 - C(n - c, k) / C(n, k).
"""

from __future__ import annotations

import random
from collections import defaultdict
from collections.abc import Callable, Iterable, Sequence
from dataclasses import dataclass
from math import comb


@dataclass(frozen=True)
class Estimate:
    value: float
    low: float
    high: float
    n_tasks: int

    def fmt(self, pct: bool = True) -> str:
        if pct:
            return f"{self.value * 100:.1f}% [{self.low * 100:.1f}, {self.high * 100:.1f}]"
        return f"{self.value:.3f} [{self.low:.3f}, {self.high:.3f}]"


def per_task(records: Iterable[dict], field: str = "primary_pass") -> dict[str, list[float]]:
    grouped: dict[str, list[float]] = defaultdict(list)
    for r in records:
        grouped[r["task_id"]].append(float(r.get(field) or 0.0))
    return dict(grouped)


def pass_hat_k(c: int, n: int, k: int) -> float:
    if n < k:
        raise ValueError(f"need at least k={k} runs, have {n}")
    return comb(c, k) / comb(n, k)


def pass_at_k(c: int, n: int, k: int) -> float:
    if n < k:
        raise ValueError(f"need at least k={k} runs, have {n}")
    return 1.0 - comb(n - c, k) / comb(n, k)


def _mean(values: Sequence[float]) -> float:
    return sum(values) / len(values) if values else 0.0


def bootstrap(clusters: dict[str, list[float]], statistic: Callable[[list[list[float]]], float], *,
              samples: int = 10_000, seed: int = 0, alpha: float = 0.05) -> Estimate:
    """Percentile CI of ``statistic`` over task clusters resampled with replacement."""
    groups = list(clusters.values())
    if not groups:
        return Estimate(0.0, 0.0, 0.0, 0)
    point = statistic(groups)
    rng = random.Random(seed)
    stats = sorted(statistic([groups[rng.randrange(len(groups))] for _ in groups]) for _ in range(samples))
    low = stats[int((alpha / 2) * samples)]
    high = stats[min(samples - 1, int((1 - alpha / 2) * samples))]
    return Estimate(point, low, high, len(groups))


def pass_at_1(clusters: dict[str, list[float]], **kw) -> Estimate:
    return bootstrap(clusters, lambda gs: _mean([_mean(g) for g in gs]), **kw)


def pass_hat(clusters: dict[str, list[float]], k: int, **kw) -> Estimate:
    def stat(groups: list[list[float]]) -> float:
        return _mean([pass_hat_k(int(sum(g)), len(g), k) for g in groups if len(g) >= k])

    return bootstrap({t: g for t, g in clusters.items() if len(g) >= k}, stat, **kw)


def mean_score(clusters: dict[str, list[float]], **kw) -> Estimate:
    return pass_at_1(clusters, **kw)


def paired_difference(a: dict[str, list[float]], b: dict[str, list[float]], *, samples: int = 10_000,
                      seed: int = 0) -> Estimate:
    """CI for pass@1(a) - pass@1(b) over tasks both participants ran (paired by task)."""
    shared = sorted(set(a) & set(b))
    diffs = {t: [_mean(a[t]) - _mean(b[t])] for t in shared}
    return bootstrap(diffs, lambda gs: _mean([g[0] for g in gs]), samples=samples, seed=seed)


def cohen_kappa(pairs: Sequence[tuple[str, str]]) -> float | None:
    """Cohen's kappa for two raters' binary pass/fail labels."""
    pairs = [(x, y) for x, y in pairs if x in ("pass", "fail") and y in ("pass", "fail")]
    if not pairs:
        return None
    n = len(pairs)
    observed = sum(x == y for x, y in pairs) / n
    p1 = sum(x == "pass" for x, _ in pairs) / n
    p2 = sum(y == "pass" for _, y in pairs) / n
    expected = p1 * p2 + (1 - p1) * (1 - p2)
    if expected == 1:
        return 1.0 if observed == 1 else 0.0
    return (observed - expected) / (1 - expected)
