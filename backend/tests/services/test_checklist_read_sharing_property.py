"""Property 18: upstream reads are shared within a request.

Requirements 4.8, 12.7.
"""
from __future__ import annotations

from collections import Counter
from decimal import Decimal

from hypothesis import given, settings
from hypothesis import strategies as st

from logstead.models.property import Property
from logstead.models.result import Result
from logstead.models.transaction import Transaction
from logstead.services.carryforward import ReconciliationSummary
from logstead.services.checklist import ChecklistService, receipt_candidates
from logstead.services.checklist_config import CHECKLIST_CONFIG
from logstead.services.dashboard import latest_tax_year
from logstead.services.report import ReportHeader, ReportTotals, ScheduleEReport

_ZERO = Decimal("0.00")
_LATEST = latest_tax_year()


class _Reports:
    def __init__(self) -> None:
        self.calls: Counter[tuple[str, int]] = Counter()

    def report_for(self, property_id: str, year: int) -> Result[ScheduleEReport]:
        self.calls[(property_id, year)] += 1
        return Result.success(
            ScheduleEReport(
                header=ReportHeader(property_id, "P", "addr", None, year, 365, 0),
                lines=(),
                other_items=(),
                totals=ReportTotals(_ZERO, _ZERO, _ZERO),
            )
        )


class _Carryforward:
    def __init__(self) -> None:
        self.calls = 0

    def reconcile(self) -> ReconciliationSummary:
        self.calls += 1
        return ReconciliationSummary(years=(), opening_balance=_ZERO, has_data=False)


class _Transactions:
    def __init__(self, by_property: dict[str, list[Transaction]]) -> None:
        self._by_property = by_property
        self.receipt_calls: Counter[str] = Counter()

    def list_for_property(self, property_id: str, tax_year: int | None = None):
        rows = self._by_property.get(property_id, [])
        if tax_year is not None:
            rows = [t for t in rows if t.date.startswith(f"{tax_year:04d}-")]
        return Result.success(list(rows))

    def has_receipt(self, property_id: str, transaction: Transaction) -> bool:
        self.receipt_calls[transaction.id] += 1
        return False


class _Depreciation:
    def list_assets(self, property_id: str) -> list:
        return []

    def schedule_for(self, property_id: str, asset_id: str) -> list:
        return []


class _Loans:
    def year_facts(self, property_id: str, tax_year: int) -> list:
        return []

    def report_years(self, property_id: str) -> list[int]:
        return []


class _Properties:
    def __init__(self, props: list[Property]) -> None:
        self._props = props

    def get(self, property_id: str) -> Result[Property]:
        for p in self._props:
            if p.id == property_id:
                return Result.success(p)
        return Result.failure("not_found", "missing")

    def list(self) -> list[Property]:
        return list(self._props)


@st.composite
def _worlds(draw):
    count = draw(st.integers(1, 4))
    props = [Property(f"p{i}", "u", f"Prop {i}", "addr") for i in range(count)]
    years = [_LATEST, _LATEST - 1, _LATEST - 2, _LATEST - 3]
    by_property: dict[str, list[Transaction]] = {}
    for prop in props:
        rows: list[Transaction] = []
        for n in range(draw(st.integers(0, 8))):
            rows.append(
                Transaction(
                    id=f"{prop.id}-t{n}",
                    property_id=prop.id,
                    date=f"{draw(st.sampled_from(years))}-03-01",
                    amount=draw(
                        st.sampled_from(
                            [Decimal("10.00"), Decimal("249.99"), Decimal("250.00"), Decimal("900.00")]
                        )
                    ),
                    type=draw(st.sampled_from(["income", "expense"])),
                    category_id="supplies",
                    schedule_e_line=14,
                    imported=draw(st.booleans()),
                )
            )
        by_property[prop.id] = rows
    return props, by_property


def _service(props, by_property):
    reports, carry = _Reports(), _Carryforward()
    txns = _Transactions(by_property)
    service = ChecklistService(
        reports,  # type: ignore[arg-type]
        txns,  # type: ignore[arg-type]
        _Depreciation(),  # type: ignore[arg-type]
        _Loans(),  # type: ignore[arg-type]
        _Properties(props),  # type: ignore[arg-type]
        carry,  # type: ignore[arg-type]
    )
    return service, reports, carry, txns


def _assert_shared(reports, carry, txns, allowed_receipts: set[str]) -> None:
    assert carry.calls == 1
    assert all(n == 1 for n in reports.calls.values())
    assert all(n == 1 for n in txns.receipt_calls.values())
    assert set(txns.receipt_calls) <= allowed_receipts


def _candidates(by_property, property_ids, years) -> set[str]:
    ids: set[str] = set()
    for pid in property_ids:
        for year in years:
            rows = [t for t in by_property[pid] if t.date.startswith(f"{year:04d}-")]
            ids |= {t.id for t in receipt_candidates(rows, CHECKLIST_CONFIG)}
    return ids


# Feature: year-end-checklist, Property 18: Upstream reads are shared within a request
@settings(max_examples=100, deadline=None)
@given(world=_worlds(), year=st.sampled_from([_LATEST, _LATEST - 1, _LATEST - 2]))
def test_single_checklist_shares_reads(world, year: int) -> None:
    """**Validates: Requirements 4.8, 12.7**"""
    props, by_property = world
    service, reports, carry, txns = _service(props, by_property)
    result = service.checklist_for(props[0].id, year)
    assert result.is_ok
    _assert_shared(reports, carry, txns, _candidates(by_property, [props[0].id], [year]))
    # Every evaluated candidate was looked up exactly once.
    assert set(txns.receipt_calls) == _candidates(by_property, [props[0].id], [year])


# Feature: year-end-checklist, Property 18: Upstream reads are shared within a request
@settings(max_examples=100, deadline=None)
@given(world=_worlds())
def test_property_summary_shares_reads(world) -> None:
    """**Validates: Requirements 4.8, 12.7**"""
    props, by_property = world
    service, reports, carry, txns = _service(props, by_property)
    result = service.property_summary(props[0].id)
    assert result.is_ok
    years = [s.tax_year for s in result.value.years]
    # One reconciliation per request, but only when at least one year is built.
    assert carry.calls == (1 if years else 0)
    assert all(n == 1 for n in reports.calls.values())
    assert all(n == 1 for n in txns.receipt_calls.values())
    assert set(txns.receipt_calls) == _candidates(by_property, [props[0].id], years)


# Feature: year-end-checklist, Property 18: Upstream reads are shared within a request
@settings(max_examples=100, deadline=None)
@given(world=_worlds(), year=st.sampled_from([_LATEST, _LATEST - 1, None]))
def test_portfolio_summary_shares_reads(world, year) -> None:
    """**Validates: Requirements 4.8, 12.7**"""
    props, by_property = world
    service, reports, carry, txns = _service(props, by_property)
    result = service.portfolio_summary(year)
    assert result.is_ok
    evaluated_year = _LATEST if year is None else year
    _assert_shared(
        reports,
        carry,
        txns,
        _candidates(by_property, [p.id for p in props], [evaluated_year]),
    )
    assert set(txns.receipt_calls) == _candidates(
        by_property, [p.id for p in props], [evaluated_year]
    )
