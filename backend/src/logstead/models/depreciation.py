"""Depreciable-asset and depreciation-schedule models (Requirements 8, 9).

Money fields are typed as ``decimal.Decimal``. The recovery period is a
``Decimal`` to represent the 27.5-year residential-rental default exactly.
"""

from __future__ import annotations

from dataclasses import dataclass
from decimal import Decimal

# Default recovery period for residential rental building assets
# (Requirement 8.4).
DEFAULT_RECOVERY_PERIOD_YEARS = Decimal("27.5")


@dataclass
class AssetInput:
    """Input to create or edit a depreciable asset (Requirements 8.1-8.3, 8.5).

    The service validates: cost basis greater than zero; property,
    description, cost basis, placed-in-service date, and recovery period
    present. ``recovery_period_years`` defaults to 27.5 when unspecified.
    """

    property_id: str | None
    description: str | None
    cost_basis: Decimal | None
    placed_in_service_date: str | None
    recovery_period_years: Decimal | None = None


@dataclass
class DepreciableAsset:
    """A persisted depreciable asset (Requirement 8).

    Attributes:
        id: The asset identifier.
        property_id: The owning property.
        description: Human-readable asset description.
        cost_basis: Cost basis as a ``Decimal`` (always greater than zero).
        placed_in_service_date: ISO-8601 ``YYYY-MM-DD`` date placed in service.
        recovery_period_years: Recovery period in years (default 27.5).
        created_at: ISO-8601 creation timestamp.
        updated_at: ISO-8601 last-update timestamp.
    """

    id: str
    property_id: str
    description: str
    cost_basis: Decimal
    placed_in_service_date: str
    recovery_period_years: Decimal = DEFAULT_RECOVERY_PERIOD_YEARS
    created_at: str | None = None
    updated_at: str | None = None


@dataclass
class DepreciationScheduleRow:
    """One tax-year row of a computed depreciation schedule (Requirement 9).

    Attributes:
        asset_id: The asset this row belongs to.
        property_id: The owning property.
        tax_year: The tax year for this row.
        amount: The depreciation amount for the year (``Decimal``).
        remaining_basis: Remaining basis after this year (``Decimal``).
        method: Depreciation method (straight-line).
        convention: Convention applied (mid-month).
    """

    asset_id: str
    property_id: str
    tax_year: int
    amount: Decimal
    remaining_basis: Decimal
    method: str = "straight_line"
    convention: str = "mid_month"
