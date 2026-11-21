"""Property test for PDF determinism.
# Feature: accountant-package, Property 4: PDF determinism
**Validates: Requirements 1.9, 5.6**
"""
from __future__ import annotations

import time
from datetime import date
from decimal import Decimal

from hypothesis import HealthCheck, given, settings
from hypothesis import strategies as st

from logstead.services.report import (
    Line12Detail,
    OtherItem,
    ReportHeader,
    ReportLine,
    ReportTotals,
    ScheduleEReport,
    SupersededManualInterest,
)
from logstead.services.report_pdf import RepairsDetail, RepairsEntry, render_property_pdf

_money = st.decimals(
    min_value=Decimal("-9999999.99"), max_value=Decimal("9999999.99"),
    places=2, allow_nan=False, allow_infinity=False,
)
# Arbitrary text, including markup, controls, and non-Windows-1252 characters.
_text = st.text(max_size=60)


@st.composite
def _reports(draw):
    header = ReportHeader(
        property_id="p1",
        property_name=draw(_text),
        address=draw(_text),
        property_type=draw(_text),
        tax_year=draw(st.integers(2000, 2100)),
        fair_rental_days=draw(st.integers(0, 365)),
        personal_use_days=draw(st.integers(0, 365)),
    )
    lines = tuple(
        ReportLine(n, f"Line {n}", "income" if n <= 4 else "expense", draw(_money), draw(st.booleans()))
        for n in range(3, 20)
    )
    others = tuple(OtherItem(draw(_text), draw(_money)) for _ in range(draw(st.integers(0, 40))))
    count = draw(st.integers(0, 5))
    detail = Line12Detail(
        source=draw(st.sampled_from(["loan-generated", "transaction-entered"])),
        superseded_manual_interest=SupersededManualInterest(
            amount=draw(_money) if count else Decimal("0.00"), count=count
        ),
    )
    totals = ReportTotals(draw(_money), draw(_money), draw(_money))
    return ScheduleEReport(header, lines, others, totals, detail)


@st.composite
def _repairs(draw):
    if draw(st.booleans()):
        return None
    entries = tuple(
        RepairsEntry(f"e{i}", draw(_text), draw(_text), draw(_money))
        for i in range(draw(st.integers(0, 30)))
    )
    return RepairsDetail(
        entries=entries,
        entered_total=draw(st.one_of(st.none(), _money)),
        itemized_sum=draw(_money),
        line_total=draw(_money),
        line_source=draw(st.sampled_from(["itemized", "entered", "none"])),
    )


@settings(max_examples=40, deadline=None, suppress_health_check=[HealthCheck.too_slow])
@given(_reports(), _repairs(), st.dates(min_value=date(2000, 1, 1), max_value=date(2100, 12, 31)))
def test_two_renders_are_byte_identical(report, repairs, generated_on) -> None:
    first = render_property_pdf(report, repairs, generated_on)
    second = render_property_pdf(report, repairs, generated_on)
    assert first == second


def test_render_does_not_depend_on_the_clock() -> None:
    lines = tuple(
        ReportLine(n, f"Line {n}", "income" if n <= 4 else "expense", Decimal("1.00"))
        for n in range(3, 20)
    )
    report = ScheduleEReport(
        ReportHeader("p1", "Name", "1 Main St", "Duplex", 2024, 365, 0),
        lines, (), ReportTotals(Decimal("2.00"), Decimal("15.00"), Decimal("-13.00")),
        Line12Detail("loan-generated", SupersededManualInterest(Decimal("0.00"), 0)),
    )
    first = render_property_pdf(report, None, date(2025, 1, 2))
    time.sleep(1.1)
    assert render_property_pdf(report, None, date(2025, 1, 2)) == first
