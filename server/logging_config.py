"""
Centralized logging configuration for the Graph Query Planning System.

Features:
  - Rich color-coded console output in development (human-readable)
  - Rotating plain-text log files under logs/ for historical debugging
  - Contextual session ID injection via ``contextvars`` — every log line
    emitted within a session's lifecycle is automatically tagged with
    ``[sid=<session_id>]`` without callers needing to pass it manually.
  - Granular subsystem loggers:
      gq.api         — HTTP request/response
      gq.session     — Session lifecycle (create, start, complete, fail)
      gq.estimation  — Cardinality estimation results and timing
      gq.threading   — Thread scheduling and OMP configuration
      gq.execution   — Downstream survey engine execution
"""
from __future__ import annotations

import contextvars
import logging
import os
from logging.handlers import RotatingFileHandler

from rich.console import Console
from rich.logging import RichHandler
from rich.text import Text
from rich.theme import Theme

# ---------------------------------------------------------------------------
# Context variable for session ID tracing
# ---------------------------------------------------------------------------
_session_id_var: contextvars.ContextVar[str | None] = contextvars.ContextVar(
    "session_id", default=None,
)


def set_session_id(sid: str) -> contextvars.Token:
    """Set the current session ID for contextual log tagging."""
    return _session_id_var.set(sid)


def clear_session_id(token: contextvars.Token) -> None:
    """Reset the session ID context variable."""
    _session_id_var.reset(token)


def get_session_id() -> str | None:
    """Return the current session ID (or None if outside a session)."""
    return _session_id_var.get()


# ---------------------------------------------------------------------------
# Configuration
# ---------------------------------------------------------------------------
_LOG_DIR: str | None = None  # set in setup_logging()

FILE_FORMAT = "%(asctime)s [%(levelname)-5s] %(name)s [%(funcName)s:%(lineno)d] %(session_tag)s%(message)s"
DATE_FORMAT = "%Y-%m-%d %H:%M:%S"

MAX_BYTES = 10 * 1024 * 1024  # 10 MB per file
BACKUP_COUNT = 5

# Subsystem loggers and their dedicated log files
_LOGGERS = {
    "api":        {"file": "api.log",        "level": logging.DEBUG},
    "session":    {"file": "session.log",    "level": logging.DEBUG},
    "estimation": {"file": "estimation.log", "level": logging.DEBUG},
    "threading":  {"file": "threading.log",  "level": logging.DEBUG},
    "execution":  {"file": "execution.log",  "level": logging.DEBUG},
}

# Color theme for subsystem badges in the Rich console
_SUBSYSTEM_COLORS = {
    "gq.api":        "bold cyan",
    "gq.session":    "bold green",
    "gq.estimation": "bold magenta",
    "gq.threading":  "bold yellow",
    "gq.execution":  "bold blue",
}


# ---------------------------------------------------------------------------
# Custom filter: injects session_tag into every LogRecord
# ---------------------------------------------------------------------------
class _SessionTagFilter(logging.Filter):
    """Injects ``record.session_tag`` from the contextvar."""

    def filter(self, record: logging.LogRecord) -> bool:
        sid = _session_id_var.get(None)
        record.session_tag = f"[sid={sid}] " if sid else ""  # type: ignore[attr-defined]
        return True


# ---------------------------------------------------------------------------
# Custom Rich handler: adds subsystem badge + session tag
# ---------------------------------------------------------------------------
class _GraphQueryRichHandler(RichHandler):
    """
    Extends ``RichHandler`` to prepend a color-coded subsystem badge
    and the session ID to each console log line.
    """

    def get_level_text(self, record: logging.LogRecord) -> Text:
        # Build a subsystem badge like  [SESSION]  or  [ESTIMATION]
        name: str = record.name
        style = _SUBSYSTEM_COLORS.get(name, "dim")
        short = name.removeprefix("gq.").upper() if name.startswith("gq.") else name.split(".")[-1].upper()
        badge = Text(f" {short:<11s}", style=style)

        # Append session ID if present
        sid = getattr(record, "session_tag", "")
        if sid:
            badge.append(Text(sid.strip(), style="dim cyan"))
            badge.append(" ")

        return badge


# ---------------------------------------------------------------------------
# Public API
# ---------------------------------------------------------------------------

def setup_logging(log_dir: str | None = None) -> None:
    """
    Configure the logging subsystem.

    Call once at startup (before any loggers are used).  Safe to call
    multiple times (e.g. in tests) -- previous handlers are cleared.

    Parameters
    ----------
    log_dir : str or None
        Directory for log files.  Defaults to ``<project_root>/logs``.
    """
    global _LOG_DIR

    if log_dir is None:
        log_dir = os.path.join(os.path.dirname(os.path.dirname(__file__)), "logs")
    _LOG_DIR = log_dir
    os.makedirs(_LOG_DIR, exist_ok=True)

    file_formatter = logging.Formatter(FILE_FORMAT, datefmt=DATE_FORMAT)
    session_filter = _SessionTagFilter()

    # -- Root logger --
    root = logging.getLogger()
    root.setLevel(logging.DEBUG)
    root.handlers.clear()
    root.addFilter(session_filter)

    # Console handler -- Rich
    console = Console(stderr=True, theme=Theme({
        "logging.level.info": "bold",
        "logging.level.warning": "bold yellow",
        "logging.level.error": "bold red",
        "logging.level.debug": "dim",
    }))
    rich_handler = _GraphQueryRichHandler(
        console=console,
        show_time=True,
        show_path=False,
        rich_tracebacks=True,
        tracebacks_show_locals=True,
        markup=True,
        log_time_format="[%H:%M:%S]",
    )
    rich_handler.setLevel(logging.INFO)
    rich_handler.addFilter(session_filter)
    root.addHandler(rich_handler)

    # Global backend.log (INFO+)
    backend_fh = _make_file_handler("backend.log", logging.INFO, file_formatter)
    backend_fh.addFilter(session_filter)
    root.addHandler(backend_fh)

    # Error aggregation (ERROR+)
    error_fh = _make_file_handler("error.log", logging.ERROR, file_formatter)
    error_fh.addFilter(session_filter)
    root.addHandler(error_fh)

    # -- Dedicated subsystem loggers --
    for name, cfg in _LOGGERS.items():
        sub_logger = logging.getLogger(f"gq.{name}")
        sub_logger.setLevel(cfg["level"])
        sub_logger.propagate = True  # also goes to console + backend.log via root

        # Remove stale file handlers from previous setup_logging() calls
        sub_logger.handlers = [
            h for h in sub_logger.handlers
            if not isinstance(h, RotatingFileHandler)
        ]

        fh = _make_file_handler(cfg["file"], cfg["level"], file_formatter)
        fh.addFilter(session_filter)
        sub_logger.addHandler(fh)

    root.info("Logging initialized -- Rich console + rotating files -> %s", _LOG_DIR)


def get_logger(name: str) -> logging.Logger:
    """
    Get a dedicated subsystem logger by short name.

    Usage::

        from server.logging_config import get_logger
        log = get_logger("estimation")   # -> logging.Logger("gq.estimation")
    """
    return logging.getLogger(f"gq.{name}")


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------

def _make_file_handler(
    filename: str,
    level: int,
    formatter: logging.Formatter,
) -> RotatingFileHandler:
    assert _LOG_DIR is not None
    fh = RotatingFileHandler(
        os.path.join(_LOG_DIR, filename),
        maxBytes=MAX_BYTES,
        backupCount=BACKUP_COUNT,
        encoding="utf-8",
    )
    fh.setLevel(level)
    fh.setFormatter(formatter)
    return fh
