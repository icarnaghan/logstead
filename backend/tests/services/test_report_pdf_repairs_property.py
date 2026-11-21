"""Property test for the Repairs appendix.

# Feature: accountant-package, Property 5: Repairs appendix
**Validates: Requirements 3.1, 3.2, 3.3, 3.4, 3.5, 3.6, 3.7**
"""
from __future__ import annotations

import io
from datetime import date, timedelta
from decimal import Decimal

from hypothesis import HealthCheck, given, settings
from hypothesis import strategies as st
from pypdf import PdfReader

from logstead.services.report import (
    ReportHeader,
    ReportLine,
    ReportTotals,
    ScheduleEReport,
)
from logstead.services.report_pdf import (
    NO_TOTAL_ENTERED,
    REPAIRS_REVIEW_SENTENCE,
    RepairsDetail,
    RepairsEntry,
    format_money,
    render_property_pdf,
)

_money = st.decimals(
    min_value=Decimal("-99999.99"), max_value=Decimal("99999.99"),
    places=2, allow_nan=False, allow_infinity=False,
)
_LABELS = {
    3: "Rents received", 4: "Royalties received", 5: "Advertising", 6: "Auto and travel",
    7: "Cleaning and maintenance", 8: "Commissions", 9: "Insurance", 10: "Legal and professional",
    11: "Management fees", 12: "Mortgage interest paid to banks", 13: "Other interest",
    14: "Repairs", 15: "Supplies", 16: "Taxes", 17: "Utilities", 18: "Depreciation",
    19: "Other expenses",
}
_SOURCE_NOTES = {
    "entered_total": "Line 14 uses the total you entered.",
    "itemized": "Line 14 uses your itemized entries.",
    "none": "Line 14 has no entered total and no itemized entries.",
}


@st.composite
def _cases(draw):
    count = draw(st.integers(0, 12))
    ids = draw(st.lists(st.text(alphabet="0123456789abcdef", min_size=4, max_size=8),
                        min_size=count, max_size=count, unique=True))
    # Few distinct dates so the id tiebreak is exercised; descriptions are unique tokens.
    entries = tuple(
        RepairsEntry(
            id=entry_id,
            date=(date(2024, 1, 1) + timedelta(days=draw(st.integers(0, 3)))).isoformat(),
            description=f"Work{k:02d}z fix",
            amount=draw(_money),
        )
        for k, entry_id in enumerate(ids)
    )
    line_total = draw(_money)
    detail = RepairsDetail(
        entries=entries,
        entered_total=draw(st.one_of(st.none(), _money)),
        itemized_sum=draw(_money),
        line_total=line_total,
        line_source=draw(st.sampled_from(["entered_total", "itemized", "none"])),
    )
    lines = tuple(
        ReportLine(n, label, "income" if n <= 4 else "expense",
                   line_total if n == 14 else draw(_money))
        for n, label in _LABELS.items()
    )
    header = ReportHeader("p1", "Name abc", "1 Main Street", "Duplex", 2024, 365, 0)
    report = ScheduleEReport(header, lines, (), ReportTotals(draw(_money), draw(_money), draw(_money)))
    return report, detail


def _text(pdf: bytes) -> str:
    return " ".join(" ".join((p.extract_text() or "").split()) for p in PdfReader(io.BytesIO(pdf)).pages)


@settings(max_examples=40, deadline=None, suppress_health_check=[HealthCheck.too_slow])
@given(_cases(), st.booleans())
def test_repairs_appendix(case, pass_none: bool) -> None:
    report, detail = case
    repairs = None if pass_none else detail
    text = _text(render_property_pdf(report, repairs, date(2025, 1, 2)))

    present = repairs is not None and len(detail.entries) > 0
    assert ("Appendix A" in text) == present
    assert (REPAIRS_REVIEW_SENTENCE in text) == present
    if not present:
        assert "Itemized entries total" not in text
        return

    appendix = text[text.index("Appendix A"):]
    entered = NO_TOTAL_ENTERED if detail.entered_total is None else format_money(detail.entered_total)
    assert f"Entered total: {entered}" in appendix
    assert (NO_TOTAL_ENTERED in appendix) == (detail.entered_total is None)
    assert f"Itemized entries total: {format_money(detail.itemized_sum)}" in appendix

    # Line 14 amount equals both the report's line 14 and the summary's line_total.
    line14 = report.line(14).total
    assert line14 == detail.line_total
    assert f"Line 14 amount: {format_money(line14)}" in appendix
    assert _SOURCE_NOTES[detail.line_source] in appendix

    # Entries in date-then-id order, each date, description, amount.
    pos = appendix.index("Description")
    for e in sorted(detail.entries, key=lambda x: (x.date, x.id)):
        for needle in (e.date, e.description, format_money(e.amount)):
            found = appendix.find(needle, pos)
            assert found >= 0, f"missing or out of order: {needle!r}"
            pos = found + len(needle)

    # The user decides; nothing is called a capital improvement.
    assert "capital" not in appendix.lower()
