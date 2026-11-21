"""Limits for the activity history. The retention window is defined only here."""
from __future__ import annotations

from dataclasses import dataclass


@dataclass(frozen=True)
class ActivityConfig:
    retention_days: int = 730  # 24 months; the single definition of the retention window
    summary_max_chars: int = 200
    value_max_chars: int = 200
    json_max_bytes: int = 2048
    default_page: int = 50
    max_page: int = 100


ACTIVITY_CONFIG = ActivityConfig()
