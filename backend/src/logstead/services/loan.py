"""Mortgage amortization: pure ``Decimal`` engine and ``LoanService``.

This module currently holds the pure engine (no I/O, no floats):

* :func:`monthly_interest`, :func:`payment_date`
* :func:`compute_payment_rows` -- the monthly schedule projected forward
  from a :class:`Loan`'s balance anchor
* :func:`build_yearly_rollups` -- per-calendar-year totals (cash basis),
  plus override-only rows
* :func:`override_year_allowed` -- which tax years accept an override

All arithmetic runs inside ``decimal.localcontext()`` with ``prec = 60`` and
is rounded half-up to cents through :func:`logstead.util.money.to_money`.
"""

from __future__ import annotations

import calendar
import re
import uuid
from collections.abc import Callable
from dataclasses import dataclass, replace
from datetime import date, datetime, timezone
from decimal import Decimal, InvalidOperation, localcontext
from typing import Any

from botocore.exceptions import BotoCoreError, ClientError

from logstead.models.loan import (
    MAX_MONEY,
    MAX_PAYMENTS,
    MIN_ANCHOR_YEAR,
    Loan,
    LoanInput,
    LoanSchedule,
    LoanView,
    PaymentRow,
    YearlyRollup,
    YearlyRollupView,
)
from logstead.models.result import Result
from logstead.repository import keys
from logstead.repository.dynamo_repo import DynamoRepository
from logstead.util.money import Money, money_to_str, to_money

__all__ = [
    "LoanService",
    "LoanYearFact",
    "ValidatedLoan",
    "validate_loan_fields",
    "monthly_interest",
    "ScheduleError",
    "payment_date",
    "compute_payment_rows",
    "build_yearly_rollups",
    "override_year_allowed",
    "loan_to_item",
    "rollup_to_item",
    "StoredLoanError",
]

_ZERO = Decimal("0.00")
_PRECISION = 60


def monthly_interest(balance: Money, rate_pct: Decimal) -> Money:
    """One month's interest: ``balance * rate% / 12`` rounded half-up."""
    with localcontext() as ctx:
        ctx.prec = _PRECISION
        return to_money(balance * rate_pct / Decimal(1200))


class ScheduleError(Exception):
    """The projection cannot be produced for a loan's inputs.

    ``field`` names the input to blame: ``"monthly_payment"`` (more than
    600 payments) or ``"anchor_date"`` (a payment past year 9999).
    """

    def __init__(self, field: str, message: str) -> None:
        super().__init__(message)
        self.field = field
        self.message = message


def payment_date(anchor: date, index: int) -> date:
    """Date of payment ``index`` (>= 1) months after ``anchor``.

    The day is clamped from the *original* anchor day, so a Jan 31 anchor
    pays Feb 28/29 and then Mar 31 (no drift). Raises
    :class:`ScheduleError` on ``anchor_date`` past year 9999.
    """
    m0 = anchor.month - 1 + index
    year, month = anchor.year + m0 // 12, m0 % 12 + 1
    if year > _MAX_YEAR:
        raise ScheduleError(
            "anchor_date",
            "A payment would fall after the year 9999. Use a later-ending "
            "schedule or an earlier anchor date.",
        )
    day = min(anchor.day, calendar.monthrange(year, month)[1])
    return date(year, month, day)


def compute_payment_rows(
    loan: Loan,
) -> tuple[list[PaymentRow], Money | None]:
    """Return ``(rows, payoff_balance)`` projected forward from the anchor.

    ``payoff_balance`` is set only when a Payoff_Date stops the schedule
    while a positive balance remains. Raises :class:`ScheduleError` when
    the schedule needs more than ``MAX_PAYMENTS`` rows or runs past 9999.
    """
    with localcontext() as ctx:
        ctx.prec = _PRECISION
        rate = loan.annual_interest_rate
        anchor = date.fromisoformat(loan.anchor_date)
        payoff = (
            date.fromisoformat(loan.payoff_date) if loan.payoff_date else None
        )
        due = loan.monthly_payment + loan.extra_principal
        balance = loan.anchor_balance
        rows: list[PaymentRow] = []

        k = 0
        while True:
            k += 1
            d = payment_date(anchor, k)
            if payoff is not None and d > payoff:
                break
            if k > MAX_PAYMENTS:
                raise ScheduleError(
                    "monthly_payment",
                    "This loan would take more than 600 payments to pay off.",
                )
            interest = monthly_interest(balance, rate)
            if balance + interest <= due:
                # Final_Payment: sweep the remaining balance.
                rows.append(
                    PaymentRow(
                        number=k,
                        date=d.isoformat(),
                        payment=to_money(interest + balance),
                        interest=interest,
                        principal=balance,
                        balance=_ZERO,
                    )
                )
                balance = _ZERO
                break
            principal = to_money(due - interest)
            balance = to_money(balance - principal)
            rows.append(
                PaymentRow(
                    number=k,
                    date=d.isoformat(),
                    payment=to_money(interest + principal),
                    interest=interest,
                    principal=principal,
                    balance=balance,
                )
            )

        payoff_balance = (
            balance if (payoff is not None and balance > 0) else None
        )
        return rows, payoff_balance


def override_year_allowed(
    tax_year: int, anchor_year: int, generated_years: set[int]
) -> bool:
    """True when an Interest_Override may be stored for ``tax_year``."""
    return MIN_ANCHOR_YEAR <= tax_year <= _MAX_YEAR and (
        tax_year <= anchor_year or tax_year in generated_years
    )


def build_yearly_rollups(
    loan: Loan, rows: list[PaymentRow]
) -> list[YearlyRollup]:
    """Group ``rows`` by calendar year (cash basis, no proration).

    Override years without rows get an Override_Only_Rollup (no payments,
    zero amounts, no ending balance). Result is sorted by tax year.
    """
    by_year: dict[int, list[PaymentRow]] = {}
    for row in rows:
        by_year.setdefault(int(row.date[0:4]), []).append(row)

    rollups: list[YearlyRollup] = []
    for year in sorted(by_year):
        year_rows = by_year[year]
        rollups.append(
            YearlyRollup(
                loan_id=loan.id,
                property_id=loan.property_id,
                tax_year=year,
                payments=len(year_rows),
                interest=to_money(sum((r.interest for r in year_rows), _ZERO)),
                principal=to_money(
                    sum((r.principal for r in year_rows), _ZERO)
                ),
                total_paid=to_money(
                    sum((r.payment for r in year_rows), _ZERO)
                ),
                ending_balance=year_rows[-1].balance,
                interest_override=loan.interest_overrides.get(year),
                include_in_report=loan.include_in_report,
            )
        )
    for year, amount in loan.interest_overrides.items():
        if year in by_year:
            continue
        rollups.append(
            YearlyRollup(
                loan_id=loan.id,
                property_id=loan.property_id,
                tax_year=year,
                payments=0,
                interest=_ZERO,
                principal=_ZERO,
                total_paid=_ZERO,
                ending_balance=None,
                interest_override=amount,
                include_in_report=loan.include_in_report,
            )
        )
    rollups.sort(key=lambda r: r.tax_year)
    return rollups


# ---------------------------------------------------------------------------
# Validation (shared with backup restore; no store access)
# ---------------------------------------------------------------------------

_DATE_RE = re.compile(r"^\d{4}-\d{2}-\d{2}$")
_MIN_DATE = date(1900, 1, 1)
_MAX_YEAR = 9999


@dataclass(frozen=True)
class ValidatedLoan:
    """Canonical, validated loan fields (no id or timestamps)."""

    property_id: str | None
    description: str
    annual_interest_rate: Decimal  # canonical plain decimal
    monthly_payment: Decimal
    anchor_balance: Decimal
    anchor_date: str
    extra_principal: Decimal  # 0.00 when unset
    payoff_date: str | None
    original_principal: Decimal | None
    closing_date: str | None
    include_in_report: bool


def _is_finite_decimal(v: object) -> bool:
    return isinstance(v, Decimal) and v.is_finite()


def _max_dp(v: Decimal, places: int) -> bool:
    """True when ``v`` (finite) has at most ``places`` decimal places."""
    exp = v.normalize().as_tuple().exponent
    return isinstance(exp, int) and exp >= -places


def _parse_date(value: object) -> date | None:
    if not isinstance(value, str) or not _DATE_RE.match(value):
        return None
    try:
        return date.fromisoformat(value)
    except ValueError:
        return None


def validate_loan_fields(loan_input: LoanInput) -> Result[ValidatedLoan]:
    """Validate raw loan input, collecting every offending field.

    On failure returns a ``validation`` error whose ``field``/``message``
    are the first error and whose ``errors`` holds every ``(field,
    message)`` pair. On success returns the canonical :class:`ValidatedLoan`
    (rate rendered as a plain decimal, never scientific notation).

    When every field check passes, the schedule is projected on a draft
    loan so a :class:`ScheduleError` (more than 600 payments, or a payment
    past year 9999) surfaces as a validation error on its field.
    """
    errors: list[tuple[str, str]] = []

    def bad(field: str, message: str) -> None:
        errors.append((field, message))

    def money_ok(
        value: object, field: str, label: str, *, positive: bool
    ) -> bool:
        if not _is_finite_decimal(value):
            bad(field, f"{label} is required.")
        elif not _max_dp(value, 2):  # type: ignore[arg-type]
            bad(field, f"{label} must have at most 2 decimal places.")
        elif positive and not 0 < value <= MAX_MONEY:  # type: ignore[operator]
            bad(
                field,
                f"{label} must be greater than 0 and at most 999,999,999.99.",
            )
        elif not positive and not 0 <= value <= MAX_MONEY:  # type: ignore[operator]
            bad(field, f"{label} must be between 0 and 999,999,999.99.")
        else:
            return True
        return False

    # description
    description = loan_input.description
    desc = description.strip() if isinstance(description, str) else ""
    if not 1 <= len(desc) <= 200:
        bad("description", "Description must be 1 to 200 characters.")

    # annual_interest_rate
    rate = loan_input.annual_interest_rate
    rate_ok = False
    if not _is_finite_decimal(rate):
        bad("annual_interest_rate", "Annual interest rate is required.")
    elif not 0 <= rate <= 100:
        bad("annual_interest_rate", "Annual interest rate must be between 0 and 100.")
    elif not _max_dp(rate, 4):
        bad(
            "annual_interest_rate",
            "Annual interest rate must have at most 4 decimal places.",
        )
    else:
        rate_ok = True

    # monthly_payment, anchor_balance
    payment = loan_input.monthly_payment
    payment_ok = money_ok(
        payment, "monthly_payment", "Monthly payment", positive=True
    )
    balance = loan_input.anchor_balance
    balance_ok = money_ok(
        balance, "anchor_balance", "Anchor balance", positive=True
    )

    # anchor_date
    anchor = _parse_date(loan_input.anchor_date)
    anchor_ok = False
    if anchor is None:
        bad("anchor_date", "Anchor date must be a valid YYYY-MM-DD date.")
    elif anchor < _MIN_DATE:
        bad("anchor_date", "Anchor date must not be before 1900-01-01.")
    else:
        anchor_ok = True

    # payment must exceed the first month's interest
    if payment_ok and balance_ok and rate_ok:
        if payment <= monthly_interest(balance, rate):
            bad(
                "monthly_payment",
                "Monthly payment must exceed the first month's interest.",
            )
            payment_ok = False

    # extra_principal
    extra = loan_input.extra_principal
    extra_ok = True
    if extra is not None:
        extra_ok = money_ok(
            extra, "extra_principal", "Extra principal", positive=False
        )

    # payoff_date (must not precede the next payment date)
    payoff_ok = True
    if loan_input.payoff_date is not None:
        payoff = _parse_date(loan_input.payoff_date)
        if payoff is None:
            bad("payoff_date", "Payoff date must be a valid YYYY-MM-DD date.")
            payoff_ok = False
        elif anchor_ok:
            try:
                next_date = payment_date(anchor, 1)
            except ScheduleError as exc:
                bad(exc.field, exc.message)
                anchor_ok = False
            else:
                if payoff < next_date:
                    bad(
                        "payoff_date",
                        "Payoff date must not be before the next payment date.",
                    )
                    payoff_ok = False

    # original_principal (informational)
    original = loan_input.original_principal
    if original is not None:
        money_ok(
            original, "original_principal", "Original principal", positive=True
        )

    # closing_date (informational; format only)
    if (
        loan_input.closing_date is not None
        and _parse_date(loan_input.closing_date) is None
    ):
        bad("closing_date", "Closing date must be a valid YYYY-MM-DD date.")

    # Project the schedule only when every other check passed.
    if not errors:
        assert rate is not None and payment is not None
        assert balance is not None and isinstance(loan_input.anchor_date, str)
        draft = Loan(
            id="",
            property_id=loan_input.property_id or "",
            description=desc,
            annual_interest_rate=Decimal(format(rate.normalize(), "f")),
            monthly_payment=payment,
            anchor_balance=balance,
            anchor_date=loan_input.anchor_date,
            extra_principal=extra if extra is not None else _ZERO,
            payoff_date=loan_input.payoff_date,
            original_principal=original,
            closing_date=loan_input.closing_date,
            include_in_report=loan_input.include_in_report,
            interest_overrides={},
            created_at="",
            updated_at="",
        )
        try:
            compute_payment_rows(draft)
        except ScheduleError as exc:
            bad(exc.field, exc.message)

    if errors:
        first_field, first_message = errors[0]
        return Result.failure(
            "validation",
            first_message,
            field=first_field,
            errors=tuple(errors),
        )

    assert rate is not None and payment is not None and balance is not None
    assert isinstance(loan_input.anchor_date, str)
    return Result.success(
        ValidatedLoan(
            property_id=loan_input.property_id,
            description=desc,
            annual_interest_rate=Decimal(format(rate.normalize(), "f")),
            monthly_payment=payment,
            anchor_balance=balance,
            anchor_date=loan_input.anchor_date,
            extra_principal=extra if extra is not None else _ZERO,
            payoff_date=loan_input.payoff_date,
            original_principal=original,
            closing_date=loan_input.closing_date,
            include_in_report=loan_input.include_in_report,
        )
    )


# ---------------------------------------------------------------------------
# Item builders and strict readers
# ---------------------------------------------------------------------------

# Money attributes (stored as two-decimal strings by the repository). The
# repository takes one set per call, so a transaction uses the union.
# ``annualInterestRate`` is deliberately NOT money: it is never quantized.
_LOAN_MONEY: frozenset[str] = frozenset(
    {"monthlyPayment", "anchorBalance", "extraPrincipal", "originalPrincipal"}
)
_ROLLUP_MONEY: frozenset[str] = frozenset(
    {
        "interest",
        "principal",
        "totalPaid",
        "endingBalance",
        "interestOverride",
        "effectiveInterest",
    }
)
_WRITE_MONEY: frozenset[str] = _LOAN_MONEY | _ROLLUP_MONEY


def loan_to_item(loan: Loan) -> dict[str, Any]:
    """Render a loan as its DynamoDB item (``None`` values are omitted on write)."""
    return {
        "PK": keys.property_scoped_pk(loan.property_id),
        "SK": keys.loan_sk(loan.id),
        "id": loan.id,
        "propertyId": loan.property_id,
        "description": loan.description,
        "annualInterestRate": format(loan.annual_interest_rate, "f"),
        "monthlyPayment": loan.monthly_payment,
        "anchorBalance": loan.anchor_balance,
        "anchorDate": loan.anchor_date,
        "originalPrincipal": loan.original_principal,
        "extraPrincipal": loan.extra_principal,
        "closingDate": loan.closing_date,
        "payoffDate": loan.payoff_date,
        "includeInReport": loan.include_in_report,
        "interestOverrides": (
            {
                str(y): money_to_str(v)
                for y, v in loan.interest_overrides.items()
            }
            or None
        ),
        "createdAt": loan.created_at,
        "updatedAt": loan.updated_at,
    }


def rollup_to_item(r: YearlyRollup) -> dict[str, Any]:
    """Render a yearly rollup as its DynamoDB item (GSI2-indexed by year)."""
    item: dict[str, Any] = {
        "PK": keys.property_scoped_pk(r.property_id),
        "SK": keys.loan_year_sk(r.loan_id, r.tax_year),
        "GSI2PK": keys.gsi2_year_pk(r.property_id, r.tax_year),
        "GSI2SK": keys.gsi2_loan_year_sk(r.loan_id),
        "loanId": r.loan_id,
        "propertyId": r.property_id,
        "taxYear": r.tax_year,
        "payments": r.payments,
        "interest": r.interest,
        "principal": r.principal,
        "totalPaid": r.total_paid,
        "interestOverride": r.interest_override,
        "effectiveInterest": r.effective_interest,
        "includeInReport": r.include_in_report,
    }
    if r.ending_balance is not None:
        item["endingBalance"] = r.ending_balance
    return item


class StoredLoanError(Exception):
    """A stored loan/rollup attribute is missing or malformed (Req 12.6)."""

    def __init__(self, field: str) -> None:
        super().__init__(field)
        self.field = field


_STORED_MONEY_RE = re.compile(r"^-?\d+\.\d{2}$")


def _stored_money(item: dict[str, Any], field: str) -> Decimal:
    value = item.get(field)
    if not isinstance(value, str) or not _STORED_MONEY_RE.match(value):
        raise StoredLoanError(field)
    return Decimal(value)


def _stored_opt_money(item: dict[str, Any], field: str) -> Decimal | None:
    if item.get(field) is None:
        return None
    return _stored_money(item, field)


def _stored_rate(item: dict[str, Any], field: str) -> Decimal:
    value = item.get(field)
    if not isinstance(value, str):
        raise StoredLoanError(field)
    try:
        rate = Decimal(value)
    except InvalidOperation:
        raise StoredLoanError(field) from None
    if not rate.is_finite():
        raise StoredLoanError(field)
    return rate


def _stored_int(item: dict[str, Any], field: str) -> int:
    value = item.get(field)
    if isinstance(value, bool) or not isinstance(value, (int, Decimal)):
        raise StoredLoanError(field)
    if value != int(value):
        raise StoredLoanError(field)
    return int(value)


def _stored_str(item: dict[str, Any], field: str) -> str:
    value = item.get(field)
    if not isinstance(value, str):
        raise StoredLoanError(field)
    return value


def _stored_opt_str(item: dict[str, Any], field: str) -> str | None:
    if item.get(field) is None:
        return None
    return _stored_str(item, field)


def _stored_bool(item: dict[str, Any], field: str) -> bool:
    value = item.get(field)
    if not isinstance(value, bool):
        raise StoredLoanError(field)
    return value


def _loan_from_item(item: dict[str, Any]) -> Loan:
    """Strictly parse a raw Loan item (read with ``money_attrs=set()``)."""
    raw_overrides = item.get("interestOverrides")
    overrides: dict[int, Decimal] = {}
    if raw_overrides is not None:
        if not isinstance(raw_overrides, dict):
            raise StoredLoanError("interestOverrides")
        for year, amount in raw_overrides.items():
            if (
                not isinstance(year, str)
                or not year.isascii()
                or not year.isdigit()
                or not isinstance(amount, str)
                or not _STORED_MONEY_RE.match(amount)
            ):
                raise StoredLoanError("interestOverrides")
            overrides[int(year)] = Decimal(amount)

    anchor_date = _stored_str(item, "anchorDate")
    if _parse_date(anchor_date) is None:
        raise StoredLoanError("anchorDate")
    extra = _stored_opt_money(item, "extraPrincipal")
    return Loan(
        id=_stored_str(item, "id"),
        property_id=_stored_str(item, "propertyId"),
        description=_stored_str(item, "description"),
        annual_interest_rate=_stored_rate(item, "annualInterestRate"),
        monthly_payment=_stored_money(item, "monthlyPayment"),
        anchor_balance=_stored_money(item, "anchorBalance"),
        anchor_date=anchor_date,
        original_principal=_stored_opt_money(item, "originalPrincipal"),
        extra_principal=extra if extra is not None else _ZERO,
        closing_date=_stored_opt_str(item, "closingDate"),
        payoff_date=_stored_opt_str(item, "payoffDate"),
        include_in_report=_stored_bool(item, "includeInReport"),
        interest_overrides=overrides,
        created_at=_stored_str(item, "createdAt"),
        updated_at=_stored_str(item, "updatedAt"),
    )


def _rollup_from_item(item: dict[str, Any]) -> YearlyRollup:
    """Strictly parse a raw rollup item (read with ``money_attrs=set()``)."""
    return YearlyRollup(
        loan_id=_stored_str(item, "loanId"),
        property_id=_stored_str(item, "propertyId"),
        tax_year=_stored_int(item, "taxYear"),
        payments=_stored_int(item, "payments"),
        interest=_stored_money(item, "interest"),
        principal=_stored_money(item, "principal"),
        total_paid=_stored_money(item, "totalPaid"),
        ending_balance=_stored_opt_money(item, "endingBalance"),
        interest_override=_stored_opt_money(item, "interestOverride"),
        include_in_report=_stored_bool(item, "includeInReport"),
    )


# ---------------------------------------------------------------------------
# LoanService
# ---------------------------------------------------------------------------

# DynamoDB's TransactWriteItems limit.
_MAX_TRANSACT_ACTIONS = 100


@dataclass(frozen=True)
class LoanYearFact:
    """One loan's facts for a tax year (see :meth:`LoanService.year_facts`)."""

    loan_id: str
    description: str
    anchor_date: str
    include_in_report: bool
    interest: Money  # Effective_Interest for the year; 0.00 without a rollup
    has_override: bool  # the year's rollup carries an interest override


def _utc_today() -> date:
    return datetime.now(timezone.utc).date()


def _now_iso() -> str:
    return datetime.now(timezone.utc).replace(microsecond=0).isoformat()


def _new_id() -> str:
    return uuid.uuid4().hex


def _year_from_sk(sk: str) -> int | None:
    tail = sk.rsplit(keys.LOAN_YEAR_MARKER, 1)[-1]
    return int(tail) if tail.isascii() and tail.isdigit() else None


def _rollup_years(loan: Loan) -> set[int]:
    rows, _ = compute_payment_rows(loan)
    return {int(r.date[0:4]) for r in rows}


class LoanService:
    """Loan CRUD scoped under a property, with atomic rollup maintenance.

    The router is responsible for confirming the property is owned by the
    caller before invoking any method here.
    """

    def __init__(
        self,
        repo: DynamoRepository,
        today: Callable[[], date] = _utc_today,
    ) -> None:
        self._repo = repo
        self._today = today

    # --- Public API ---------------------------------------------------------

    def create_loan(self, data: LoanInput) -> Result[LoanView]:
        if not data.property_id:
            return Result.failure(
                "validation", "Property is required.", field="property_id"
            )
        validated = validate_loan_fields(data)
        if validated.error is not None:
            return Result.failure(
                validated.error.kind,
                validated.error.message,
                field=validated.error.field,
                errors=validated.error.errors,
            )
        now = _now_iso()
        loan = self._build_loan(
            validated.value, data.property_id, _new_id(), {}, now, now
        )
        written = self._write_loan(loan, set())
        if written is not None:
            return written
        return Result.success(self._view(loan))

    def list_loans(self, property_id: str) -> Result[list[LoanView]]:
        items = self._repo.query(
            keys.property_scoped_pk(property_id),
            sk_begins_with=keys.loan_list_prefix(),
            money_attrs=set(),
        )
        views: list[LoanView] = []
        try:
            for item in items:
                if keys.is_loan_year_sk(item["SK"]):
                    continue
                views.append(self._view(_loan_from_item(item)))
        except StoredLoanError as exc:
            return self._corrupt(exc)
        except ScheduleError as exc:
            return self._schedule_conflict(exc)
        return Result.success(views)

    def get_loan(self, property_id: str, loan_id: str) -> Result[LoanView]:
        loaded = self._load(property_id, loan_id)
        if loaded.error is not None:
            return Result.failure(
                loaded.error.kind, loaded.error.message, field=loaded.error.field
            )
        try:
            return Result.success(self._view(loaded.value))
        except ScheduleError as exc:
            return self._schedule_conflict(exc)

    def update_loan(
        self, property_id: str, loan_id: str, data: LoanInput
    ) -> Result[LoanView]:
        loaded = self._load(property_id, loan_id)
        if loaded.error is not None:
            return Result.failure(
                loaded.error.kind, loaded.error.message, field=loaded.error.field
            )
        existing = loaded.value
        validated = validate_loan_fields(data)
        if validated.error is not None:
            return Result.failure(
                validated.error.kind,
                validated.error.message,
                field=validated.error.field,
                errors=validated.error.errors,
            )
        # Overrides are kept only for years still allowed by the new schedule.
        draft = self._build_loan(
            validated.value,
            property_id,
            existing.id,
            {},
            existing.created_at,
            _now_iso(),
        )
        new_years = _rollup_years(draft)
        anchor_year = int(draft.anchor_date[0:4])
        kept = {
            y: v
            for y, v in existing.interest_overrides.items()
            if override_year_allowed(y, anchor_year, new_years)
        }
        loan = replace(draft, interest_overrides=kept)
        previous_years = self._stored_years(property_id, loan_id)
        written = self._write_loan(loan, previous_years)
        if written is not None:
            return written
        return Result.success(self._view(loan))

    def delete_loan(self, property_id: str, loan_id: str) -> Result[None]:
        pk = keys.property_scoped_pk(property_id)
        if self._repo.get_item(pk, keys.loan_sk(loan_id), money_attrs=set()) is None:
            return self._not_found()
        rollups = self._repo.query(
            pk,
            sk_begins_with=keys.loan_year_list_prefix(loan_id),
            money_attrs=set(),
        )
        actions: list[dict[str, Any]] = [
            {"delete": {"pk": pk, "sk": keys.loan_sk(loan_id)}}
        ]
        actions += [{"delete": {"pk": pk, "sk": r["SK"]}} for r in rollups]
        try:
            self._repo.transact_write(actions, money_attrs=_WRITE_MONEY)
        except (ClientError, BotoCoreError):
            return Result.failure(
                "unavailable",
                "Could not delete the loan and its yearly interest totals. "
                "No changes were made.",
            )
        return Result.success(None)

    # --- Internals ----------------------------------------------------------

    @staticmethod
    def _not_found() -> Result[Any]:
        return Result.failure("not_found", "Loan not found.", field="loan_id")

    @staticmethod
    def _corrupt(exc: StoredLoanError) -> Result[Any]:
        return Result.failure(
            "conflict",
            f"Stored loan has an invalid {exc.field} value.",
            field=exc.field,
        )

    @staticmethod
    def _schedule_conflict(exc: ScheduleError) -> Result[Any]:
        return Result.failure(
            "conflict",
            f"Stored loan cannot be projected: {exc.message}",
            field=exc.field,
        )

    @staticmethod
    def _build_loan(
        v: ValidatedLoan,
        property_id: str,
        loan_id: str,
        overrides: dict[int, Decimal],
        created_at: str,
        updated_at: str,
    ) -> Loan:
        return Loan(
            id=loan_id,
            property_id=property_id,
            description=v.description,
            annual_interest_rate=v.annual_interest_rate,
            monthly_payment=v.monthly_payment,
            anchor_balance=v.anchor_balance,
            anchor_date=v.anchor_date,
            extra_principal=v.extra_principal,
            payoff_date=v.payoff_date,
            original_principal=v.original_principal,
            closing_date=v.closing_date,
            include_in_report=v.include_in_report,
            interest_overrides=dict(overrides),
            created_at=created_at,
            updated_at=updated_at,
        )

    def _load(self, property_id: str, loan_id: str) -> Result[Loan]:
        item = self._repo.get_item(
            keys.property_scoped_pk(property_id),
            keys.loan_sk(loan_id),
            money_attrs=set(),
        )
        if item is None:
            return self._not_found()
        try:
            return Result.success(_loan_from_item(item))
        except StoredLoanError as exc:
            return self._corrupt(exc)

    def _stored_years(self, property_id: str, loan_id: str) -> set[int]:
        rows = self._repo.query(
            keys.property_scoped_pk(property_id),
            sk_begins_with=keys.loan_year_list_prefix(loan_id),
            money_attrs=set(),
        )
        years = (_year_from_sk(r["SK"]) for r in rows)
        return {y for y in years if y is not None}

    def _write_loan(
        self, loan: Loan, previous_years: set[int]
    ) -> Result[Any] | None:
        """Write the loan, its rollups and stale-rollup deletes atomically.

        Returns a failure result, or ``None`` on success.
        """
        rows, _ = compute_payment_rows(loan)
        rollups = build_yearly_rollups(loan, rows)
        new_years = {r.tax_year for r in rollups}
        pk = keys.property_scoped_pk(loan.property_id)
        actions: list[dict[str, Any]] = [{"put": loan_to_item(loan)}]
        actions += [{"put": rollup_to_item(r)} for r in rollups]
        actions += [
            {"delete": {"pk": pk, "sk": keys.loan_year_sk(loan.id, y)}}
            for y in sorted(previous_years - new_years)
        ]
        if len(actions) > _MAX_TRANSACT_ACTIONS:
            return Result.failure(
                "validation",
                "This loan has too many yearly interest totals to save at "
                "once. Remove some interest overrides first.",
                field="interest_overrides",
            )
        try:
            self._repo.transact_write(actions, money_attrs=_WRITE_MONEY)
        except (ClientError, BotoCoreError):
            return Result.failure(
                "unavailable",
                "Could not save the loan and its yearly interest totals. "
                "No changes were made.",
            )
        return None

    def _view(self, loan: Loan) -> LoanView:
        rows, payoff_balance = compute_payment_rows(loan)
        next_date = payment_date(date.fromisoformat(loan.anchor_date), 1)
        today = self._today().isoformat()
        ended = (loan.payoff_date is not None and loan.payoff_date <= today) or (
            bool(rows) and rows[-1].date < today and rows[-1].balance == 0
        )
        return LoanView(
            id=loan.id,
            property_id=loan.property_id,
            description=loan.description,
            annual_interest_rate=loan.annual_interest_rate,
            monthly_payment=loan.monthly_payment,
            anchor_balance=loan.anchor_balance,
            anchor_date=loan.anchor_date,
            extra_principal=loan.extra_principal,
            payoff_date=loan.payoff_date,
            original_principal=loan.original_principal,
            closing_date=loan.closing_date,
            include_in_report=loan.include_in_report,
            interest_overrides={
                str(y): v for y, v in sorted(loan.interest_overrides.items())
            },
            created_at=loan.created_at,
            updated_at=loan.updated_at,
            remaining_payments=len(rows),
            next_payment_date=next_date.isoformat(),
            projected_payoff_date=(
                rows[-1].date if rows and rows[-1].balance == 0 else None
            ),
            payoff_balance=payoff_balance,
            status="ended" if ended else "active",
        )

    # --- Schedule and interest overrides ------------------------------------

    @staticmethod
    def _rollup_view(stored: YearlyRollup) -> YearlyRollupView:
        est = stored.interest
        override = stored.interest_override
        return YearlyRollupView(
            tax_year=stored.tax_year,
            payments=stored.payments,
            interest=stored.effective_interest,
            estimated_interest=est,
            interest_override=override,
            variance=(
                to_money(override - est) if override is not None else None
            ),
            principal=stored.principal,
            total_paid=stored.total_paid,
            ending_balance=stored.ending_balance,
        )

    def _year_view(
        self, loan: Loan, tax_year: int
    ) -> YearlyRollupView | None:
        """Engine-derived view of one year, or ``None`` when it has no row."""
        rows, _ = compute_payment_rows(loan)
        for rollup in build_yearly_rollups(loan, rows):
            if rollup.tax_year == tax_year:
                return self._rollup_view(rollup)
        return None

    def schedule_for(
        self, property_id: str, loan_id: str
    ) -> Result[LoanSchedule]:
        loaded = self._load(property_id, loan_id)
        if loaded.error is not None:
            return Result.failure(
                loaded.error.kind, loaded.error.message, field=loaded.error.field
            )
        loan = loaded.value
        try:
            rows, payoff_balance = compute_payment_rows(loan)
        except ScheduleError as exc:
            return self._schedule_conflict(exc)
        yearly = [
            self._rollup_view(r) for r in build_yearly_rollups(loan, rows)
        ]
        return Result.success(
            LoanSchedule(
                loan_id=loan.id,
                estimate=True,
                payments=tuple(rows),
                yearly=tuple(yearly),
                payoff_balance=payoff_balance,
            )
        )

    @staticmethod
    def _override_error(tax_year: int) -> Result[Any]:
        return Result.failure(
            "validation",
            "Interest must be an amount from 0 to 999,999,999.99 with at "
            "most 2 decimal places, for a year from 1900 through the anchor "
            "year or a year with loan payments.",
            field=f"interest_overrides.{tax_year}",
        )

    def set_interest_override(
        self,
        property_id: str,
        loan_id: str,
        tax_year: int,
        amount: Decimal | str,
    ) -> Result[YearlyRollupView]:
        loaded = self._load(property_id, loan_id)
        if loaded.error is not None:
            return Result.failure(
                loaded.error.kind, loaded.error.message, field=loaded.error.field
            )
        loan = loaded.value
        try:
            generated = _rollup_years(loan)
        except ScheduleError as exc:
            return self._schedule_conflict(exc)
        anchor_year = int(loan.anchor_date[0:4])
        if (
            isinstance(tax_year, bool)
            or not isinstance(tax_year, int)
            or not override_year_allowed(tax_year, anchor_year, generated)
        ):
            return self._override_error(tax_year)

        value: Decimal | None = None
        if isinstance(amount, Decimal):
            value = amount
        elif isinstance(amount, str):
            try:
                value = Decimal(amount.strip())
            except InvalidOperation:
                value = None
        if (
            value is None
            or not value.is_finite()
            or not _max_dp(value, 2)
            or not 0 <= value <= MAX_MONEY
        ):
            return self._override_error(tax_year)
        value = to_money(value)

        overrides = dict(loan.interest_overrides)
        overrides[tax_year] = value
        updated = replace(loan, interest_overrides=overrides, updated_at=_now_iso())
        failed = self._write_loan(
            updated, self._stored_years(property_id, loan_id)
        )
        if failed is not None:
            return failed
        view = self._year_view(updated, tax_year)
        assert view is not None
        return Result.success(view)

    def clear_interest_override(
        self, property_id: str, loan_id: str, tax_year: int
    ) -> Result[YearlyRollupView | None]:
        loaded = self._load(property_id, loan_id)
        if loaded.error is not None:
            return Result.failure(
                loaded.error.kind, loaded.error.message, field=loaded.error.field
            )
        loan = loaded.value
        try:
            if tax_year not in loan.interest_overrides:
                return Result.success(self._year_view(loan, tax_year))
            overrides = {
                y: v for y, v in loan.interest_overrides.items() if y != tax_year
            }
            updated = replace(
                loan, interest_overrides=overrides, updated_at=_now_iso()
            )
            failed = self._write_loan(
                updated, self._stored_years(property_id, loan_id)
            )
            if failed is not None:
                return failed
            return Result.success(self._year_view(updated, tax_year))
        except ScheduleError as exc:
            return self._schedule_conflict(exc)

    # --- Read seams (reports, dashboard, carryforward) ----------------------
    #
    # These return plain values. A malformed stored attribute raises
    # :class:`StoredLoanError` (strict readers, Req 12.6) for the caller to map.

    def _included_rollups(
        self, property_id: str, tax_year: int | None = None
    ) -> list[YearlyRollup]:
        """Rollups of included loans: GSI2 for one tax year, else all years."""
        if tax_year is not None:
            items = self._repo.query(
                keys.gsi2_year_pk(property_id, tax_year),
                sk_begins_with=keys.gsi2_loan_year_prefix(),
                index_name="GSI2",
                money_attrs=set(),
            )
        else:
            items = [
                i
                for i in self._repo.query(
                    keys.property_scoped_pk(property_id),
                    sk_begins_with=keys.loan_list_prefix(),
                    money_attrs=set(),
                )
                if keys.is_loan_year_sk(i["SK"])
            ]
        rollups = [_rollup_from_item(i) for i in items]
        return [r for r in rollups if r.include_in_report]

    def property_effective_interest_for_year(
        self, property_id: str, tax_year: int
    ) -> Money:
        """Sum of Effective_Interest over the property's included loans."""
        total = Decimal("0.00")
        for r in self._included_rollups(property_id, tax_year):
            total += r.effective_interest
        return to_money(total)

    def year_facts(
        self, property_id: str, tax_year: int
    ) -> list[LoanYearFact]:
        """Per-loan facts for one tax year, for every loan of the property.

        Reads the loan items and the year's rollups (all rollups, included
        or not), joins on loan id, projects no schedule and writes nothing.
        A loan without a rollup for the year has ``interest`` of ``0.00``
        and no override. Raises :class:`StoredLoanError` on a malformed
        stored attribute.
        """
        loans = [
            _loan_from_item(i)
            for i in self._repo.query(
                keys.property_scoped_pk(property_id),
                sk_begins_with=keys.loan_list_prefix(),
                money_attrs=set(),
            )
            if not keys.is_loan_year_sk(i["SK"])
        ]
        rollups = {
            r.loan_id: r
            for r in (
                _rollup_from_item(i)
                for i in self._repo.query(
                    keys.gsi2_year_pk(property_id, tax_year),
                    sk_begins_with=keys.gsi2_loan_year_prefix(),
                    index_name="GSI2",
                    money_attrs=set(),
                )
            )
        }
        facts: list[LoanYearFact] = []
        for loan in loans:
            rollup = rollups.get(loan.id)
            facts.append(
                LoanYearFact(
                    loan_id=loan.id,
                    description=loan.description,
                    anchor_date=loan.anchor_date,
                    include_in_report=loan.include_in_report,
                    interest=(
                        rollup.effective_interest if rollup else _ZERO
                    ),
                    has_override=(
                        rollup is not None
                        and rollup.interest_override is not None
                    ),
                )
            )
        return facts

    def report_years(self, property_id: str) -> set[int]:
        """Tax years with a rollup from an included loan."""
        return {r.tax_year for r in self._included_rollups(property_id)}

    def earliest_year(self, property_id: str) -> int | None:
        """Earliest anchor or override year across the loans, or ``None``."""
        items = self._repo.query(
            keys.property_scoped_pk(property_id),
            sk_begins_with=keys.loan_list_prefix(),
            money_attrs=set(),
        )
        years: list[int] = []
        for i in items:
            if keys.is_loan_year_sk(i["SK"]):
                continue
            loan = _loan_from_item(i)
            years.append(
                min([int(loan.anchor_date[0:4]), *loan.interest_overrides])
            )
        return min(years) if years else None
