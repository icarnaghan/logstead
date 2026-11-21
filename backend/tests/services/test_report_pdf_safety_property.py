"""Property test for PDF text safety.

# Feature: accountant-package, Property 3: PDF text safety
**Validates: Requirements 5.1, 5.2, 5.3, 5.4**
"""
from __future__ import annotations

import builtins
import io
import socket
import unicodedata
from datetime import date
from decimal import Decimal
from pathlib import Path
from unittest import mock

import reportlab
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
from logstead.services.report_pdf import RepairsDetail, RepairsEntry, render_property_pdf

_ADVERSARIAL = [
    "<b>bold</b> & <i>x</i>",
    '<img src="http://example.invalid/x.png"/>',
    '<img src="file:///etc/passwd" width="10" height="10"/>',
    '<font color="red" size="30">big</font>',
    '<a href="http://example.invalid">link</a>',
    "&amp; &lt; &#65; &nbsp; <",
    "<para>unclosed <b>",
    "tab\there\x00nul\x07bell\x1besc\r\nline",
    "caf\u00e9 \u20ac \u2020 \u4e2d\u6587 \U0001f600 \u0416",
    "A" * 4000,
    "word " * 800,
]
_text = st.one_of(
    st.sampled_from(_ADVERSARIAL),
    st.text(max_size=60),
    st.text(alphabet="<>&/\"'=abimgsrcfont \x00\x07\n\t\u20ac\u4e2d", max_size=80),
    st.text(min_size=2000, max_size=3000, alphabet="ab<>&x"),
)
_money = st.just(Decimal("1.00"))
_LABELS = {
    3: "Rents received", 4: "Royalties received", 5: "Advertising", 6: "Auto and travel",
    7: "Cleaning and maintenance", 8: "Commissions", 9: "Insurance", 10: "Legal and professional",
    11: "Management fees", 12: "Mortgage interest paid to banks", 13: "Other interest",
    14: "Repairs", 15: "Supplies", 16: "Taxes", 17: "Utilities", 18: "Depreciation",
    19: "Other expenses",
}


def _expected(value: str) -> str:
    """Drop control characters, map non-Windows-1252 to ``?``, drop whitespace."""
    out = []
    for ch in value:
        if unicodedata.category(ch) == "Cc":
            continue
        try:
            ch.encode("cp1252")
        except UnicodeEncodeError:
            ch = "?"
        out.append(ch)
    return "".join("".join(out).split())


def _extract(pdf: bytes) -> str:
    reader = PdfReader(io.BytesIO(pdf))
    return "".join("".join((p.extract_text() or "").split()) for p in reader.pages)


def _build(name: str, address: str, descs: list[str], repair_desc: str) -> bytes:
    header = ReportHeader(
        property_id="p1", property_name=name, address=address, property_type="Single Family",
        tax_year=2024, fair_rental_days=1, personal_use_days=0,
    )
    lines = tuple(
        ReportLine(n, label, "income" if n <= 4 else "expense", Decimal("1.00"), False)
        for n, label in _LABELS.items()
    )
    others = tuple(OtherItem(d, Decimal("1.00")) for d in descs)
    detail = Line12Detail("transaction-entered", SupersededManualInterest(Decimal("0.00"), 0))
    report = ScheduleEReport(header, lines, others, ReportTotals(Decimal("1.00"), Decimal("1.00"), Decimal("0.00")), detail)
    repairs = RepairsDetail(
        entries=(RepairsEntry("r1", "2024-01-01", repair_desc, Decimal("1.00")),),
        entered_total=None, itemized_sum=Decimal("1.00"), line_total=Decimal("1.00"),
        line_source="itemized",
    )
    return render_property_pdf(report, repairs, date(2025, 1, 15))


def _forbid_socket(*_a, **_k):
    raise AssertionError("network use during PDF render")


@settings(max_examples=100, deadline=None, suppress_health_check=list(HealthCheck))
@given(name=_text, address=_text, descs=st.lists(_text, min_size=0, max_size=3), repair_desc=_text)
def test_pdf_text_is_literal_and_offline(name, address, descs, repair_desc):
    real_open = builtins.open
    opened: list[str] = []

    def spy_open(file, *args, **kwargs):
        opened.append(str(file))
        return real_open(file, *args, **kwargs)

    with mock.patch.object(socket, "socket", _forbid_socket), \
         mock.patch.object(socket, "create_connection", _forbid_socket), \
         mock.patch.object(builtins, "open", spy_open):
        pdf = _build(name, address, descs, repair_desc)

    root = str(Path(reportlab.__file__).parent)
    stray = [f for f in opened if not f.startswith(root)]
    assert not stray, f"unexpected files opened: {stray}"

    text = _extract(pdf)
    for value in (name, address, *descs, repair_desc):
        expected = _expected(value)
        if len(expected) > 1500:
            # A value this long may break across pages, with the footer between
            # the two halves, so check its head and tail instead of the whole.
            parts = (expected[:200], expected[-200:])
        else:
            parts = (expected,)
        for part in parts:
            assert part in text, f"value missing from PDF text: {value[:60]!r}"
