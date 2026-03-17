"""Statistical utilities for experiment analysis."""
from __future__ import annotations

import math
from typing import Sequence


def mean_std(values: Sequence[float]) -> tuple[float, float]:
    """Return (mean, std_dev) for a sequence of floats."""
    n = len(values)
    if n == 0:
        return 0.0, 0.0
    mu = sum(values) / n
    if n == 1:
        return mu, 0.0
    var = sum((x - mu) ** 2 for x in values) / (n - 1)
    return mu, math.sqrt(var)


def wilcoxon_test(a: Sequence[float], b: Sequence[float]) -> tuple[float, float]:
    """Wilcoxon signed-rank test. Returns (statistic, p_value).

    Falls back to (nan, nan) if scipy is unavailable or input is too small.
    """
    try:
        from scipy.stats import wilcoxon
        if len(a) < 6 or len(a) != len(b):
            return float("nan"), float("nan")
        stat, p = wilcoxon(a, b)
        return float(stat), float(p)
    except (ImportError, ValueError):
        return float("nan"), float("nan")


def spearman_corr(a: Sequence[float], b: Sequence[float]) -> tuple[float, float]:
    """Spearman rank correlation. Returns (rho, p_value).

    Falls back to (nan, nan) if scipy is unavailable.
    """
    try:
        from scipy.stats import spearmanr
        if len(a) < 3 or len(a) != len(b):
            return float("nan"), float("nan")
        rho, p = spearmanr(a, b)
        return float(rho), float(p)
    except (ImportError, ValueError):
        return float("nan"), float("nan")
