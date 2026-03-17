"""Timing utilities for experiment scripts."""
from __future__ import annotations

import time
from contextlib import contextmanager
from dataclasses import dataclass, field
from typing import Any, Callable, Generator


@dataclass
class TimerResult:
    """Mutable container filled by the timer context manager."""
    elapsed_s: float = 0.0


@contextmanager
def timer() -> Generator[TimerResult, None, None]:
    """Context manager that measures wall-clock time in seconds."""
    result = TimerResult()
    t0 = time.perf_counter()
    try:
        yield result
    finally:
        result.elapsed_s = time.perf_counter() - t0


def timed_median(fn: Callable[[], Any], repeats: int = 3) -> tuple[float, Any]:
    """Run *fn* multiple times and return (median_seconds, last_return_value)."""
    times: list[float] = []
    ret = None
    for _ in range(repeats):
        t0 = time.perf_counter()
        ret = fn()
        times.append(time.perf_counter() - t0)
    times.sort()
    median = times[len(times) // 2]
    return median, ret
