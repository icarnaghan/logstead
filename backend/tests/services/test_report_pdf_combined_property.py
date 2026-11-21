"""Property test for the combined portfolio PDF layout and totals.

# Feature: accountant-package, Property 6: Combined layout and totals
**Validates: Requirements 4.2, 4.3, 4.6**
"""
from __future__ import annotations

import io
import math
import re
from datetime import date
from decimal import Decimal

from hypothesis import HealthCheck, given, settings
from hypothesis import strategies as st
from pypdf import PdfReader

from logstead.services.report import (
    CombinedScheduleEReport,
    Line12Portfolio,
    OtherItem,
    ReportHeader,
    ReportLine,
    ReportTotals,
    ScheduleEReport,
    SupersededManualInterest,
)
from logstead.services.report_pdf import (
    COMBINED_COLUMN_LABELS,
    chunk_columns,
    format_money,
    render_combined_pdf,
)

_money = st.decimals(
    min_value=Decimal("-9999999.99"), max_value=Decimal("9999999.99"),
    places=2, allow_nan=False, allow_infinity=False,
)
_LABELS = {3: "Rents received", 5: "Advertising", 12: "Mortgage interest", 14: "Repairs", 19: "Other expenses"}


@st.composite
def _combined(draw):
    n = draw(st.integers(1, 10))
    reports = []
    for i in range(n):
        header = ReportHeader(f"id{i}", f"Prop{i + 1}", f"{i + 1} Main", "Duplex", 2024, 365, 0)
        lines = tuple(
            ReportLine(num, label, "income" if num <= 4 else "expense", draw(_money))
            for num, label in _LABELS.items()
        )
        others = tuple(OtherItem(f"Misc{i}x{j}", draw(_money)) for j in range(draw(st.integers(0, 2))))
        totals = ReportTotals(draw(_money), draw(_money), draw(_money))
        reports.append(ScheduleEReport(header, lines, others, totals))
    count = draw(st.integers(0, 12))
    line12 = Line12Portfolio(
        total=draw(_money),
        superseded_manual_interest=SupersededManualInterest(
            amount=draw(_money) if count else Decimal("0.00"), count=count
        ),
    )
    return CombinedScheduleEReport(2024, tuple(reports), ReportTotals(draw(_money), draw(_money), draw(_money)), line12)


def _text(pdf: bytes) -> str:
    reader = PdfReader(io.BytesIO(pdf))
    return " ".join(" ".join((p.extract_text() or "").split()) for p in reader.pages)


@settings(max_examples=40, deadline=None, suppress_health_check=[HealthCheck.too_slow])
@given(_combined())
def test_combined_layout_and_totals(combined: CombinedScheduleEReport) -> None:
    n = len(combined.properties)

    # chunk_columns: ceil(N / 3) groups of at most three, original order.
    groups = chunk_columns(combined.properties)
    assert len(groups) == math.ceil(n / 3)
    assert all(1 <= len(g) <= 3 for g in groups)
    assert [p for g in groups for p in g] == list(combined.properties)

    text = _text(render_combined_pdf(combined, {}, date(2025, 1, 2)))

    # Column letters A, B, C label the members of each group, and a new table
    # starts for every group.
    for group in groups:
        for letter_, report in zip(COMBINED_COLUMN_LABELS, group):
            assert re.search(rf"(?<![A-Za-z]){letter_} {re.escape(report.header.property_name)}(?!\d)", text)
    assert text.count("21 Net income or (loss)") == len(groups)

    # Portfolio totals equal the combined report's totals.
    start = text.find("Portfolio totals")
    assert start >= 0
    tail = text[start:]
    for label, value in (
        ("Total income", combined.totals.total_income),
        ("Total expenses (line 20)", combined.totals.total_expenses),
        ("Net income or (loss) (line 21)", combined.totals.net),
    ):
        assert f"{label} {format_money(value)}" in tail

    # Line 12 total with the summed superseded count and amount.
    assert f"Portfolio Line 12 total: {format_money(combined.line12.total)}." in tail
    sup = combined.line12.superseded_manual_interest
    if sup.count > 0:
        assert f"{sup.count} hand-entered mortgage interest" in tail
        assert format_money(sup.amount) in tail
    else:
        assert "hand-entered" not in tail
