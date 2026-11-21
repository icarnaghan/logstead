"""Thresholds applied by the Year-end checklist.

This module is the only place the checklist's threshold values live. Every
money threshold and the swing percentage is a ``Decimal``; floats are rejected.
An invalid configuration raises ``ChecklistConfigError`` when the module is
loaded (``CHECKLIST_CONFIG`` is built at import time).
"""

from __future__ import annotations

from dataclasses import dataclass
from decimal import ROUND_HALF_UP, Decimal
from typing import Any

_CENTS = Decimal("0.01")
_ZERO = Decimal("0")


class ChecklistConfigError(ValueError):
    """Raised when a checklist threshold is missing its type or range."""


@dataclass(frozen=True)
class AppliedThresholds:
    """The thresholds echoed in a checklist response (money at two places)."""

    large_entry_amount: Decimal
    capital_candidate_amount: Decimal
    swing_percent: Decimal
    swing_minimum_amount: Decimal
    anchor_max_age_months: int
    summary_year_count: int


def _require_decimal(name: str, value: Any) -> Decimal:
    if isinstance(value, bool) or not isinstance(value, Decimal):
        raise ChecklistConfigError(f"{name} must be a Decimal.")
    if not value.is_finite():
        raise ChecklistConfigError(f"{name} must be a finite number.")
    return value


def _require_count(name: str, value: Any) -> int:
    if isinstance(value, bool) or not isinstance(value, int):
        raise ChecklistConfigError(f"{name} must be an integer.")
    if value < 1:
        raise ChecklistConfigError(f"{name} must be at least 1.")
    return value


def _money(name: str, value: Any) -> Decimal:
    amount = _require_decimal(name, value)
    if amount < _ZERO:
        raise ChecklistConfigError(f"{name} must not be below 0.00.")
    return amount.quantize(_CENTS, rounding=ROUND_HALF_UP)


@dataclass(frozen=True)
class ChecklistConfig:
    large_entry_amount: Decimal = Decimal("250.00")
    capital_candidate_amount: Decimal = Decimal("2500.00")
    swing_percent: Decimal = Decimal("50")
    swing_minimum_amount: Decimal = Decimal("500.00")
    anchor_max_age_months: int = 12
    summary_year_count: int = 5

    def __post_init__(self) -> None:
        # Frozen dataclass: normalize through object.__setattr__.
        for name in (
            "large_entry_amount",
            "capital_candidate_amount",
            "swing_minimum_amount",
        ):
            object.__setattr__(self, name, _money(name, getattr(self, name)))
        percent = _require_decimal("swing_percent", self.swing_percent)
        if percent <= _ZERO:
            raise ChecklistConfigError("swing_percent must be greater than 0.")
        _require_count("anchor_max_age_months", self.anchor_max_age_months)
        _require_count("summary_year_count", self.summary_year_count)

    def applied(self) -> AppliedThresholds:
        """Return the thresholds in the form echoed in a response."""
        return AppliedThresholds(
            large_entry_amount=self.large_entry_amount,
            capital_candidate_amount=self.capital_candidate_amount,
            swing_percent=self.swing_percent,
            swing_minimum_amount=self.swing_minimum_amount,
            anchor_max_age_months=self.anchor_max_age_months,
            summary_year_count=self.summary_year_count,
        )


CHECKLIST_CONFIG = ChecklistConfig()
