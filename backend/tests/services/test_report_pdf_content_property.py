"""Property test for the PDF text content.

# Feature: accountant-package, Property 1: The PDF text carries every report figure
**Validates: Requirements 1.2, 1.3, 1.4, 1.5, 1.6, 1.7, 1.8, 2.4, 21.1, 21.2**
"""
from __future__ import annotations

import io
import re
from datetime import date
from decimal import Decimal

from hypothesis import HealthCheck, given, settings
from hypothesis import strategies as st
from pypdf import PdfReader

from logstead.services.report import (
    Line12Detail,
    OtherItem,
    ReportHeader,
    ReportLine,
    ReportTotals,
    ScheduleEReport,
    SupersededManualInterest,
)
from logstead.services.report_pdf import (
    DISCLAIMER,
    IMPORTED_MARKER,
    LINE12_FROM_LOAN,
    LINE12_FROM_TRANSACTIONS,
    WORKSHEET_NOTE,
    format_money,
    render_property_pdf,
)

_money = st.decimals(
    min_value=Decimal("-9999999.99"), max_value=Decimal("9999999.99"),
    places=2, allow_nan=False, allow_infinity=False,
)
_words = st.text(alphabet="abcdefghijklmnopqrstuvwxyz", min_size=3, max_size=12)
_LABELS = {
    3: "Rents received", 4: "Royalties received", 5: "Advertising", 6: "Auto and travel",
    7: "Cleaning and maintenance", 8: "Commissions", 9: "Insurance", 10: "Legal and professional",
    11: "Management fees", 12: "Mortgage interest paid to banks", 13: "Other interest",
    14: "Repairs", 15: "Supplies", 16: "Taxes", 17: "Utilities", 18: "Depreciation",
    19: "Other expenses",
}


@st.composite
def _reports(draw):
    header = ReportHeader(
        property_id="p1",
        property_name="Name " + draw(_words),
        address=draw(_words) + " Street " + draw(_words),
        property_type=draw(st.sampled_from(["Single Family", "Duplex", "Vacation"])),
        tax_year=draw(st.integers(2000, 2100)),
        fair_rental_days=draw(st.integers(0, 365)),
        personal_use_days=draw(st.integers(0, 365)),
    )
    lines = tuple(
        ReportLine(n, label, "income" if n <= 4 else "expense", draw(_money), draw(st.booleans()))
        for n, label in _LABELS.items()
    )
    others = tuple(
        OtherItem(f"Item{i} {draw(_words)}", draw(_money))
        for i in range(draw(st.integers(0, 70)))
    )
    count = draw(st.integers(0, 5))
    detail = Line12Detail(
        source=draw(st.sampled_from(["loan-generated", "transaction-entered"])),
        superseded_manual_interest=SupersededManualInterest(
            amount=draw(_money) if count else Decimal("0.00"), count=count
        ),
    )
    totals = ReportTotals(draw(_money), draw(_money), draw(_money))
    return ScheduleEReport(header, lines, others, totals, detail)


def _text(pdf: bytes) -> tuple[str, list[str]]:
    pages = [" ".join((p.extract_text() or "").split()) for p in PdfReader(io.BytesIO(pdf)).pages]
    return " ".join(pages), pages


def _walk(text: str, needles: list[str]) -> None:
    """Assert each needle appears after the previous one."""
    pos = 0
    for needle in needles:
        found = text.find(needle, pos)
        assert found >= 0, f"missing or out of order: {needle!r}"
        pos = found + len(needle)


@settings(max_examples=40, deadline=None, suppress_health_check=[HealthCheck.too_slow])
@given(_reports(), st.dates(min_value=date(2000, 1, 1), max_value=date(2100, 12, 31)))
def test_pdf_text_carries_every_report_figure(report: ScheduleEReport, generated_on: date) -> None:
    text, pages = _text(render_property_pdf(report, None, generated_on))
    h = report.header

    for value in (
        h.property_name, h.address, h.property_type, str(h.tax_year),
        str(h.fair_rental_days), str(h.personal_use_days), generated_on.isoformat(),
        WORKSHEET_NOTE,
    ):
        assert value in text

    # Lines in ascending order, label then amount, then the totals.
    ordered = sorted(report.lines, key=lambda ln: ln.line)
    needles: list[str] = []
    for ln in ordered:
        needles += [ln.label, format_money(ln.total)]
    assert [ln.line for ln in report.lines] == [ln.line for ln in ordered]
    _walk(text, needles)
    for amount in (report.totals.total_income, report.totals.total_expenses, report.totals.net):
        assert format_money(amount) in text
    _walk(text, ["Total income", format_money(report.totals.total_income)])
    _walk(text, ["Total expenses", format_money(report.totals.total_expenses)])
    _walk(text, ["Net income or (loss)", format_money(report.totals.net)])

    # Other items in order, each description then amount.
    if report.other_items:
        start = text.find("Line 19, Other expenses")
        assert start >= 0
        _walk(text[start:], [s for i in report.other_items for s in (i.description, format_money(i.amount))])

    # Footnote marker if and only if some line has includes_imported.
    assert (IMPORTED_MARKER in text) == any(ln.includes_imported for ln in report.lines)

    # Line 12 source sentence and superseded details.
    sup = report.line12.superseded_manual_interest
    source = LINE12_FROM_LOAN if report.line12.source == "loan-generated" else LINE12_FROM_TRANSACTIONS
    assert source in text
    if sup.count > 0:
        assert f"{sup.count} hand-entered mortgage interest" in text
        assert format_money(sup.amount) in text
    else:
        assert "hand-entered" not in text

    # Disclaimer, property name, tax year, and page number on every page.
    disclaimer = " ".join(DISCLAIMER.split())
    for number, page in enumerate(pages, start=1):
        assert disclaimer in page
        assert h.property_name in page and str(h.tax_year) in page
        assert re.search(rf"Page {number} of {len(pages)}", page)


def test_long_report_spans_several_pages() -> None:
    others = tuple(OtherItem(f"Item{i} widget", Decimal("1.00") * i) for i in range(120))
    lines = tuple(ReportLine(n, label, "income" if n <= 4 else "expense", Decimal("5.00")) for n, label in _LABELS.items())
    header = ReportHeader("p1", "Long Name", "1 Main Street", "Duplex", 2024, 365, 0)
    report = ScheduleEReport(header, lines, others, ReportTotals(Decimal("10.00"), Decimal("20.00"), Decimal("-10.00")))
    text, pages = _text(render_property_pdf(report, None, date(2025, 1, 2)))
    assert len(pages) >= 3
    assert all(" ".join(DISCLAIMER.split()) in p for p in pages)
    _walk(text, [s for i in others for s in (i.description, format_money(i.amount))])
