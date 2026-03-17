"""Centralized logging for experiment scripts.

Configures Python logging to output to both console (INFO+) and a log file
(DEBUG+) under the results directory. Also provides an ErrorCounter for
tracking per-query failures.

Usage:
    from experiments.common.logger import setup_logger, ErrorCounter

    log = setup_logger("E7")
    errors = ErrorCounter()

    try:
        ...
    except Exception:
        log.exception("query %s failed", q["name"])
        errors.record(dataset=ds, query=q["name"], error=str(e))

    errors.summary(log)
"""
from __future__ import annotations

import logging
import sys
import time
from dataclasses import dataclass, field
from pathlib import Path

from .config import RESULTS_DIR


def setup_logger(
    name: str,
    log_dir: str | Path | None = None,
    console_level: int = logging.INFO,
    file_level: int = logging.DEBUG,
) -> logging.Logger:
    """Create and configure a logger that writes to console + file.

    Parameters
    ----------
    name : experiment identifier (e.g. "E7", "E8")
    log_dir : directory for log file (default: experiments/results/)
    console_level : minimum level for console output
    file_level : minimum level for file output
    """
    log_dir = Path(log_dir) if log_dir else RESULTS_DIR
    log_dir.mkdir(parents=True, exist_ok=True)

    logger = logging.getLogger(f"exp.{name}")
    logger.setLevel(logging.DEBUG)

    # Avoid duplicate handlers on repeated calls
    if logger.handlers:
        return logger

    fmt = logging.Formatter(
        "[%(asctime)s] %(levelname)-7s %(name)s — %(message)s",
        datefmt="%Y-%m-%d %H:%M:%S",
    )

    # Console handler
    ch = logging.StreamHandler(sys.stdout)
    ch.setLevel(console_level)
    ch.setFormatter(fmt)
    logger.addHandler(ch)

    # File handler — shared log file for all experiments in this run
    log_file = log_dir / "experiment.log"
    fh = logging.FileHandler(log_file, mode="a", encoding="utf-8")
    fh.setLevel(file_level)
    fh.setFormatter(fmt)
    logger.addHandler(fh)

    return logger


@dataclass
class ErrorCounter:
    """Track per-query errors during an experiment run."""

    _errors: list[dict] = field(default_factory=list)

    def record(self, *, dataset: str, query: str, phase: str = "", error: str = ""):
        """Record a single error occurrence."""
        self._errors.append({
            "time": time.strftime("%H:%M:%S"),
            "dataset": dataset,
            "query": query,
            "phase": phase,
            "error": error,
        })

    @property
    def count(self) -> int:
        return len(self._errors)

    def summary(self, logger: logging.Logger) -> None:
        """Log a summary of all recorded errors."""
        if not self._errors:
            logger.info("All queries completed successfully (0 errors)")
            return
        logger.warning("Completed with %d error(s):", len(self._errors))
        for e in self._errors:
            logger.warning(
                "  [%s] %s / %s / %s: %s",
                e["time"], e["dataset"], e["query"], e["phase"], e["error"],
            )
