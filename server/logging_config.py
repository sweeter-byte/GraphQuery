"""
Centralized logging configuration for the Graph Query Planning System.

Creates 6 single-purpose rotating log files under logs/:
  - http.log        — HTTP request/response (method, path, status, latency)
  - session.log     — Session lifecycle (create, start, config, complete, fail)
  - estimation.log  — Cardinality estimation results (V, E, c_hat, timing breakdown)
  - threading.log   — Thread scheduling and execution (thread name/id, OMP config)
  - execution.log   — Survey downstream execution (command, matches, timing, output)
  - error.log       — All ERROR-level logs aggregated across all loggers
  - backend.log     — Global catch-all log file for all INFO+ messages
"""
from __future__ import annotations

import logging
import os
from logging.handlers import RotatingFileHandler

LOG_DIR = os.path.join(os.path.dirname(os.path.dirname(__file__)), "logs")
LOG_FORMAT = "%(asctime)s [%(levelname)s] %(name)s [%(funcName)s:%(lineno)d] %(message)s"
DATE_FORMAT = "%Y-%m-%d %H:%M:%S"

MAX_BYTES = 10 * 1024 * 1024  # 10 MB per file
BACKUP_COUNT = 5

# Named loggers — import these in other modules
# Usage: from server.logging_config import get_logger
#        http_log = get_logger("http")

_LOGGERS = {
    "http":       {"file": "http.log",       "level": logging.DEBUG},
    "session":    {"file": "session.log",    "level": logging.DEBUG},
    "estimation": {"file": "estimation.log", "level": logging.DEBUG},
    "threading":  {"file": "threading.log",  "level": logging.DEBUG},
    "execution":  {"file": "execution.log",  "level": logging.DEBUG},
    "error":      {"file": "error.log",      "level": logging.ERROR},  # errors only
}


def setup_logging() -> None:
    """Configure root logger + 6 dedicated loggers with rotating file handlers."""
    os.makedirs(LOG_DIR, exist_ok=True)

    formatter = logging.Formatter(LOG_FORMAT, datefmt=DATE_FORMAT)

    # ── Root logger → console only (INFO) ──
    root = logging.getLogger()
    root.setLevel(logging.DEBUG)

    # Remove any pre-existing handlers to avoid duplicates on reload
    root.handlers.clear()

    console = logging.StreamHandler()
    console.setLevel(logging.INFO)
    console.setFormatter(formatter)
    root.addHandler(console)

    # ── Root backend handler (catches all INFO+) ──
    backend_fh = RotatingFileHandler(
        os.path.join(LOG_DIR, "backend.log"),
        maxBytes=MAX_BYTES,
        backupCount=BACKUP_COUNT,
        encoding="utf-8",
    )
    backend_fh.setLevel(logging.INFO)
    backend_fh.setFormatter(formatter)
    root.addHandler(backend_fh)

    # ── Error aggregation handler on root (catches all ERROR+) ──
    error_fh = RotatingFileHandler(
        os.path.join(LOG_DIR, "error.log"),
        maxBytes=MAX_BYTES,
        backupCount=BACKUP_COUNT,
        encoding="utf-8",
    )
    error_fh.setLevel(logging.ERROR)
    error_fh.setFormatter(formatter)
    root.addHandler(error_fh)

    # ── Create dedicated loggers ──
    for name, cfg in _LOGGERS.items():
        if name == "error":
            continue  # handled via root

        logger = logging.getLogger(f"gq.{name}")
        logger.setLevel(cfg["level"])
        logger.propagate = True  # also goes to console + error.log via root

        # Remove existing file handlers on reload
        logger.handlers = [h for h in logger.handlers if not isinstance(h, RotatingFileHandler)]

        fh = RotatingFileHandler(
            os.path.join(LOG_DIR, str(cfg["file"])),
            maxBytes=MAX_BYTES,
            backupCount=BACKUP_COUNT,
            encoding="utf-8",
        )
        fh.setLevel(cfg["level"])
        fh.setFormatter(formatter)
        logger.addHandler(fh)

    logging.getLogger().info(
        "Logging initialized — backend.log (global) + dedicated log files → %s", LOG_DIR
    )


def get_logger(name: str) -> logging.Logger:
    """
    Get a dedicated logger by short name.

    Usage:
        from server.logging_config import get_logger
        log = get_logger("estimation")  # → writes to logs/estimation.log
    """
    return logging.getLogger(f"gq.{name}")
