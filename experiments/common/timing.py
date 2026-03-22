"""Timing utilities for experiment scripts."""
from __future__ import annotations

import signal
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


class QueryTimeout(Exception):
    """Raised when a per-query timeout is exceeded."""


@contextmanager
def query_timeout(seconds: int):
    """Context manager that raises QueryTimeout after *seconds*.

    Uses SIGALRM — Linux only, main thread only.
    Nests safely: restores the previous alarm on exit.
    """
    if seconds <= 0:
        yield
        return

    def _handler(signum, frame):
        raise QueryTimeout(f"query exceeded {seconds}s timeout")

    old_handler = signal.signal(signal.SIGALRM, _handler)
    old_alarm = signal.alarm(seconds)
    try:
        yield
    finally:
        signal.alarm(0)  # cancel our alarm
        signal.signal(signal.SIGALRM, old_handler)
        if old_alarm > 0:  # restore outer alarm (approximate)
            signal.alarm(old_alarm)


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
