"""Mortgage loan and amortization models.

Money fields are ``decimal.Decimal`` (no floats). Dates are ISO
``YYYY-MM-DD`` strings.
"""

from __future__ import annotations

from dataclasses import dataclass
from decimal import Decimal
from typing import Literal

# Upper bound for any money value (Requirement 1.2).
MAX_MONEY = Decimal("999999999.99")

# Maximum number of projected payments for one loan (Requirement 2.14).
MAX_PAYMENTS = 600

# Earliest allowed anchor date / override tax year (Requirements 1.7, 6.2).
MIN_ANCHOR_YEAR = 1900


@dataclass
class LoanInput:
    """Raw, unvalidated input (router maps the JSON body to this)."""

    property_id: str | None
    description: str | None
    annual_interest_rate: Decimal | None
    monthly_payment: Decimal | None
    anchor_balance: Decimal | None
    anchor_date: str | None
    extra_principal: Decimal | None = None
    payoff_date: str | None = None
    original_principal: Decimal | None = None  # informational
    closing_date: str | None = None  # informational
    include_in_report: bool = True


@dataclass(frozen=True)
class Loan:
    """A persisted mortgage loan."""

    id: str
    property_id: str
    description: str
    annual_interest_rate: Decimal  # canonical, <= 4 dp, never scientific
    monthly_payment: Decimal  # 2 dp
    anchor_balance: Decimal  # 2 dp
    anchor_date: str  # YYYY-MM-DD
    extra_principal: Decimal  # 2 dp, 0.00 when unset
    payoff_date: str | None
    original_principal: Decimal | None  # informational, 2 dp
    closing_date: str | None  # informational
    include_in_report: bool
    interest_overrides: dict[int, Decimal]  # tax_year -> 2 dp
    created_at: str
    updated_at: str


@dataclass(frozen=True)
class PaymentRow:
    """One scheduled payment."""

    number: int
    date: str
    payment: Decimal
    interest: Decimal
    principal: Decimal
    balance: Decimal


@dataclass(frozen=True)
class YearlyRollup:
    """Per-tax-year totals for a loan."""

    loan_id: str
    property_id: str
    tax_year: int
    payments: int
    interest: Decimal  # estimated (sum of row interest)
    principal: Decimal
    total_paid: Decimal
    ending_balance: Decimal | None  # None for an override-only rollup
    interest_override: Decimal | None
    include_in_report: bool

    @property
    def effective_interest(self) -> Decimal:
        """Override if present, else the estimated interest."""
        if self.interest_override is not None:
            return self.interest_override
        return self.interest


@dataclass(frozen=True)
class LoanView:
    """Flat API shape: Loan fields plus derived values."""

    id: str
    property_id: str
    description: str
    annual_interest_rate: Decimal
    monthly_payment: Decimal
    anchor_balance: Decimal
    anchor_date: str
    extra_principal: Decimal
    payoff_date: str | None
    original_principal: Decimal | None
    closing_date: str | None
    include_in_report: bool
    interest_overrides: dict[str, Decimal]  # e.g. {"2024": Decimal("7000.00")}
    created_at: str
    updated_at: str
    remaining_payments: int  # number of projected payment rows
    next_payment_date: str  # one month after the anchor date
    projected_payoff_date: str | None  # date of the final row when balance is 0.00
    payoff_balance: Decimal | None  # only when Payoff_Date leaves a balance
    status: Literal["active", "ended"]


@dataclass(frozen=True)
class YearlyRollupView:
    """Per-tax-year API shape with override variance."""

    tax_year: int
    payments: int
    interest: Decimal  # Effective_Interest (what Line 12 uses)
    estimated_interest: Decimal  # raw rollup interest
    interest_override: Decimal | None
    variance: Decimal | None  # override - estimated; None without override
    principal: Decimal
    total_paid: Decimal
    ending_balance: Decimal | None  # None for an override-only year


@dataclass(frozen=True)
class LoanSchedule:
    """Full amortization schedule for a loan."""

    loan_id: str
    estimate: bool  # always True; the UI labels the schedule as an estimate
    payments: tuple[PaymentRow, ...]
    yearly: tuple[YearlyRollupView, ...]
    payoff_balance: Decimal | None

    def __post_init__(self) -> None:
        if self.estimate is not True:
            raise ValueError("LoanSchedule.estimate must always be True")
