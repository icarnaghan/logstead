"""Property test: Line 12 exports match the report (mortgage-amortization).

Feature: mortgage-amortization, Property 24: Exports match the report

For any report, the Line 12 total, source, and superseded-manual-interest
amount and count found by parsing the backend CSV and JSON exports equal the
report values at two decimals. Pure: report dataclasses are built directly.

**Validates: Requirements 6.10**
"""

from __future__ import annotations

import csv
import io
import json
from decimal import Decimal

from hypothesis import given, settings
from hypothesis import strategies as st

from logstead.services.report import (
    CombinedScheduleEReport,
    Line12Detail,
    Line12Portfolio,
    ReportHeader,
    ReportLine,
    ReportTotals,
    ScheduleEReport,
    SupersededManualInterest,
    _combined_to_csv,
    _combined_to_json,
    _report_to_csv,
    _report_to_json,
)

_money = st.decimals(
    min_value=Decimal("0.00"),
    max_value=Decimal("999999999.99"),
    places=2,
    allow_nan=False,
    allow_infinity=False,
)
_signed_money = st.decimals(
    min_value=Decimal("-999999999.99"),
    max_value=Decimal("999999999.99"),
    places=2,
    allow_nan=False,
    allow_infinity=False,
)
_superseded = st.builds(
    SupersededManualInterest, amount=_money, count=st.integers(0, 1000)
)
_detail = st.builds(
    Line12Detail,
    source=st.sampled_from(["loan-generated", "transaction-entered"]),
    superseded_manual_interest=_superseded,
)
_portfolio = st.builds(
    Line12Portfolio, total=_money, superseded_manual_interest=_superseded
)
_totals = st.builds(
    ReportTotals,
    total_income=_money,
    total_expenses=_money,
    net=_signed_money,
)
_text = st.text(alphabet="abcdefghij ,\"", max_size=12)


@st.composite
def _reports(draw) -> ScheduleEReport:
    line12_total = draw(_money)
    header = ReportHeader(
        property_id="p1",
        property_name=draw(_text),
        address=draw(_text),
        property_type=draw(st.none() | st.just("single-family")),
        tax_year=draw(st.integers(2000, 2100)),
        fair_rental_days=draw(st.integers(0, 365)),
        personal_use_days=draw(st.integers(0, 365)),
    )
    lines = (
        ReportLine(3, "Rents received", "income", draw(_money)),
        ReportLine(12, "Mortgage interest paid to banks", "expense", line12_total),
        ReportLine(13, "Other interest", "expense", draw(_money)),
    )
    return ScheduleEReport(
        header=header,
        lines=lines,
        other_items=(),
        totals=draw(_totals),
        line12=draw(_detail),
    )


_combined = st.builds(
    CombinedScheduleEReport,
    tax_year=st.integers(2000, 2100),
    properties=st.lists(_reports(), min_size=0, max_size=3).map(tuple),
    totals=_totals,
    line12=_portfolio,
)


def _rows(data: bytes) -> list[list[str]]:
    return list(csv.reader(io.StringIO(data.decode("utf-8"))))


def _money_str(value: Decimal) -> str:
    return f"{value:.2f}"


def _assert_property_block(rows: list[list[str]], report: ScheduleEReport) -> int:
    """Check the three rows follow the line table; return the index of the first."""
    start = next(i for i, r in enumerate(rows) if r == ["Line", "Label", "Kind", "Amount"])
    idx = start + 1 + len(report.lines)
    sup = report.line12.superseded_manual_interest
    line12 = report.line(12)
    assert line12 is not None
    assert rows[start + 1 + report.lines.index(line12)][3] == _money_str(line12.total)
    assert rows[idx] == ["Line 12 Source", report.line12.source]
    assert rows[idx + 1] == [
        "Line 12 Superseded Manual Interest",
        _money_str(sup.amount),
    ]
    assert rows[idx + 2] == ["Line 12 Superseded Transaction Count", str(sup.count)]
    return idx


def _assert_json_line12(obj: dict, report: ScheduleEReport) -> None:
    sup = report.line12.superseded_manual_interest
    assert obj["line12"] == {
        "source": report.line12.source,
        "superseded_manual_interest": {
            "amount": _money_str(sup.amount),
            "count": sup.count,
        },
    }


@settings(deadline=None, max_examples=100)
@given(report=_reports())
def test_report_exports_match_line12(report: ScheduleEReport) -> None:
    _assert_property_block(_rows(_report_to_csv(report)), report)
    _assert_json_line12(json.loads(_report_to_json(report)), report)


@settings(deadline=None, max_examples=100)
@given(report=_combined)
def test_combined_exports_match_line12(report: CombinedScheduleEReport) -> None:
    rows = _rows(_combined_to_csv(report))
    p = report.line12
    sup = p.superseded_manual_interest

    # Each property block carries its own three rows, in order.
    starts = [i for i, r in enumerate(rows) if r == ["Line", "Label", "Kind", "Amount"]]
    assert len(starts) == len(report.properties)
    for start, column in zip(starts, report.properties):
        _assert_property_block(rows[start:], column)

    # Portfolio block.
    pi = rows.index(["Portfolio Totals"])
    tail = rows[pi:]
    assert ["Line 12 Total", _money_str(p.total)] in tail
    assert ["Line 12 Superseded Manual Interest", _money_str(sup.amount)] in tail
    assert ["Line 12 Superseded Transaction Count", str(sup.count)] in tail

    obj = json.loads(_combined_to_json(report))
    assert obj["line12"] == {
        "total": _money_str(p.total),
        "superseded_manual_interest": {
            "amount": _money_str(sup.amount),
            "count": sup.count,
        },
    }
    assert len(obj["properties"]) == len(report.properties)
    for entry, column in zip(obj["properties"], report.properties):
        _assert_json_line12(entry, column)
