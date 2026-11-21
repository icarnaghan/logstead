"""Property 1: checklist shape, counts, and determinism.

Requirements 1.1 to 1.6.
"""
from __future__ import annotations

from datetime import date, timedelta
from decimal import Decimal

from hypothesis import given, settings
from hypothesis import strategies as st

from logstead.models.transaction import Transaction
from logstead.services.carryforward import ReconciledYear
from logstead.services.checklist import (
    ITEM_IDS,
    LoanFact,
    YearSnapshot,
    build_checklist,
)
from logstead.services.checklist_config import ChecklistConfig
from logstead.services.itemized import resolve_category_rows
from logstead.services.report import (
    Line12Detail,
    ReportHeader,
    ReportLine,
    ReportTotals,
    ScheduleEReport,
    SupersededManualInterest,
)

_ZERO = Decimal("0.00")
_YEAR = 2024
_STATUSES = {"done", "needs_attention", "not_applicable"}

_money = st.decimals(min_value=Decimal("0.00"), max_value=Decimal("20000.00"), places=2)
_configs = st.builds(
    ChecklistConfig,
    large_entry_amount=_money,
    capital_candidate_amount=_money,
    swing_percent=st.decimals(min_value=Decimal("0.1"), max_value=Decimal("500.0"), places=1),
    swing_minimum_amount=_money,
    anchor_max_age_months=st.integers(1, 36),
    summary_year_count=st.integers(1, 20),
)

_INCOME_LINES = (3,)
_EXPENSE_LINES = tuple(range(5, 20))


@st.composite
def _reports(draw, year: int = _YEAR) -> ScheduleEReport:
    lines = [ReportLine(3, "Rents received", "income", draw(_money))]
    for number in _EXPENSE_LINES:
        lines.append(ReportLine(number, f"Line {number}", "expense", draw(_money)))
    superseded = SupersededManualInterest(
        amount=draw(_money), count=draw(st.integers(0, 5))
    )
    line12 = Line12Detail(
        source=draw(st.sampled_from(["loan-generated", "transaction-entered"])),
        superseded_manual_interest=superseded,
    )
    income = lines[0].total
    expenses = sum((ln.total for ln in lines[1:]), _ZERO)
    return ScheduleEReport(
        header=ReportHeader("p1", "P", "addr", None, year, 365, 0),
        lines=tuple(lines),
        other_items=(),
        totals=ReportTotals(income, expenses, income - expenses),
        line12=line12,
    )


_timestamps = st.one_of(
    st.none(),
    st.just("not-a-date"),
    st.integers(0, 3000).map(
        lambda n: f"2024-01-01T00:00:00+00:00"
        if n == 0
        else (date(2024, 1, 1) + timedelta(days=n % 300)).isoformat() + "T00:00:00+00:00"
    ),
)


@st.composite
def _transactions(draw, index: int) -> Transaction:
    return Transaction(
        id=f"t{index}",
        property_id="p1",
        date=f"{_YEAR}-03-01",
        amount=draw(st.decimals(min_value=Decimal("0.01"), max_value=Decimal("20000.00"), places=2)),
        type=draw(st.sampled_from(["income", "expense"])),
        category_id=draw(st.sampled_from(["repairs", "supplies", "rent"])),
        schedule_e_line=draw(st.sampled_from([3, 14, 9])),
        itemized=draw(st.booleans()),
        imported=draw(st.booleans()),
        created_at=draw(_timestamps),
        updated_at=draw(_timestamps),
    )


_dates = st.dates(min_value=date(2000, 1, 1), max_value=date(2030, 12, 31)).map(
    lambda d: d.isoformat()
)


@st.composite
def _loans(draw, index: int) -> LoanFact:
    return LoanFact(
        loan_id=f"l{index}",
        description=f"Loan {index}",
        anchor_date=draw(_dates),
        include_in_report=draw(st.booleans()),
        interest=draw(_money),
        has_override=draw(st.booleans()),
    )


@st.composite
def _carryforwards(draw) -> ReconciledYear | None:
    if draw(st.booleans()):
        return None
    status = draw(st.sampled_from(["ok", "mismatch", "carried", "unreported"]))
    reported = None if status == "unreported" else draw(_money)
    expected = draw(_money)
    return ReconciledYear(
        tax_year=_YEAR,
        schedule_e_net=draw(_money),
        expected_carryforward=draw(_money),
        reported_carryforward=reported,
        status=status,
        drift=None if reported is None else reported - expected,
        carried_from_year=_YEAR - 1 if status == "carried" else None,
        expected_carry_in=expected,
    )


@st.composite
def _snapshots(draw) -> YearSnapshot:
    count = draw(st.integers(0, 8))
    transactions = [draw(_transactions(i)) for i in range(count)]
    loans = [draw(_loans(i)) for i in range(draw(st.integers(0, 3)))]
    receipts = {
        t.id: draw(st.booleans()) for t in transactions if draw(st.booleans())
    }
    return YearSnapshot(
        property_id="p1",
        tax_year=_YEAR,
        report=draw(_reports(_YEAR)),
        prior_report=draw(_reports(_YEAR - 1)),
        transactions=tuple(transactions),
        repairs=resolve_category_rows(transactions, "repairs"),
        assets_with_rows=draw(st.integers(0, 3)),
        loans=tuple(loans),
        carryforward=draw(_carryforwards()),
        status_tolerance=Decimal("2.00"),
        receipt_present=receipts,
    )


def _empty_snapshot() -> YearSnapshot:
    def report(year: int) -> ScheduleEReport:
        return ScheduleEReport(
            header=ReportHeader("p1", "P", "addr", None, year, 365, 0),
            lines=(),
            other_items=(),
            totals=ReportTotals(_ZERO, _ZERO, _ZERO),
        )

    return YearSnapshot(
        property_id="p1",
        tax_year=_YEAR,
        report=report(_YEAR),
        prior_report=report(_YEAR - 1),
        transactions=(),
        repairs=resolve_category_rows([], "repairs"),
        assets_with_rows=0,
        loans=(),
        carryforward=None,
        status_tolerance=Decimal("2.00"),
        receipt_present={},
    )


def _assert_shape(snapshot: YearSnapshot, config: ChecklistConfig) -> None:
    result = build_checklist(snapshot, config)
    assert [item.id for item in result.items] == list(ITEM_IDS)
    assert len(result.items) == 11
    for item in result.items:
        assert item.title.strip()
        assert item.reason.strip()
        assert item.link.strip()
        assert item.status in _STATUSES
    counts = result.counts
    for status in _STATUSES:
        assert getattr(counts, status) == sum(1 for i in result.items if i.status == status)
    assert counts.done + counts.needs_attention + counts.not_applicable == counts.total
    assert counts.total == len(result.items)
    assert result.property_id == snapshot.property_id
    assert result.tax_year == snapshot.tax_year
    # Determinism: building again yields an equal result.
    assert build_checklist(snapshot, config) == result


# Feature: year-end-checklist, Property 1: Checklist shape, counts, and determinism
@settings(max_examples=200, deadline=None)
@given(snapshot=_snapshots(), config=_configs)
def test_shape_counts_and_determinism(snapshot: YearSnapshot, config: ChecklistConfig) -> None:
    """**Validates: Requirements 1.1, 1.2, 1.3, 1.4, 1.5, 1.6**"""
    _assert_shape(snapshot, config)


# Feature: year-end-checklist, Property 1: Checklist shape, counts, and determinism
@settings(max_examples=100, deadline=None)
@given(config=_configs)
def test_empty_snapshot_shape(config: ChecklistConfig) -> None:
    """**Validates: Requirements 1.1, 1.2, 1.3, 1.4, 1.5, 1.6**"""
    _assert_shape(_empty_snapshot(), config)
