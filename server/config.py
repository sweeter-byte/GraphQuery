"""
Centralized configuration for the Graph Query Planning System.

All runtime settings are resolved here — environment variables, default
config files, and auto-detection.  Other modules import from this single
source rather than scattering ``os.environ.get`` / ``json.load`` calls.
"""
from __future__ import annotations

import json
import os
from dataclasses import dataclass, field
from pathlib import Path
from typing import Optional

from .models import ScheduleConfig

# ---------------------------------------------------------------------------
# Paths — resolved once relative to the project root
# ---------------------------------------------------------------------------
_PROJECT_ROOT = Path(__file__).resolve().parent.parent
_DEFAULT_DATASET_ROOT = str(_PROJECT_ROOT / "dataset")
_DEFAULT_LOG_DIR = str(_PROJECT_ROOT / "logs")
_DEFAULT_SCHEDULE_CFG = Path(__file__).resolve().parent / "default_config" / "schedule_config.json"


@dataclass(frozen=True)
class AppConfig:
    """Immutable application-wide configuration."""

    dataset_root: str = field(default_factory=lambda: os.environ.get("DATASET_ROOT", _DEFAULT_DATASET_ROOT))
    log_dir: str = field(default_factory=lambda: os.environ.get("LOG_DIR", _DEFAULT_LOG_DIR))
    survey_binary: str = field(default_factory=lambda: os.environ.get("SURVEY_BINARY", ""))


# ---------------------------------------------------------------------------
# Singleton
# ---------------------------------------------------------------------------
_config: AppConfig | None = None


def get_config() -> AppConfig:
    """Return the global ``AppConfig`` singleton (created on first call)."""
    global _config
    if _config is None:
        _config = AppConfig()
    return _config


# ---------------------------------------------------------------------------
# Schedule configuration resolution
# ---------------------------------------------------------------------------

def resolve_schedule_config(override: Optional[ScheduleConfig] = None) -> ScheduleConfig:
    """
    Resolve the effective schedule configuration.

    Priority:
      1. Explicit user override (if mode != "auto")
      2. ``server/default_config/schedule_config.json``
      3. Auto-detect based on CPU core count
    """
    if override and override.mode != "auto":
        return override

    # Try loading from the default config file
    if _DEFAULT_SCHEDULE_CFG.exists():
        try:
            data = json.loads(_DEFAULT_SCHEDULE_CFG.read_text())
            cfg = ScheduleConfig(**data)
            if cfg.mode != "auto":
                return cfg
        except Exception:
            pass  # fall through to auto-detect

    # Auto-detect
    cores = os.cpu_count() or 4
    return ScheduleConfig(mode="auto", python_threads=cores, omp_threads=1)
