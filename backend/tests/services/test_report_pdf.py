"""Example tests for the PDF renderer (accountant-package task 2.10).

**Validates: Requirements 1.7, 1.8, 2.1, 2.5, 3.3, 5.5, 21.1, 21.2**
"""
from __future__ import annotations

import ast
import io
import re
from datetime import date
from decimal import Decimal
from pathlib import Path

from pypdf import PdfReader

from logstead.services import report_pdf
from logstead.services.report import (
    CombinedScheduleEReport,
    Line12Detail,
    Line12Portfolio,
    OtherItem,
    ReportHeader,
    ReportLine,
    ReportTotals,
    ScheduleEReport,
    SupersededManualInterest,
)
from logstead.services.report_pdf import (
    DISCLAIMER,
    IMPORTED_FOOTNOTE,
    IMPORTED_MARKER,
    LINE12_FROM_LOAN,
    LINE12_FROM_TRANSACTIONS,
    NO_TOTAL_ENTERED,
    REPAIRS_REVIEW_SENTENCE,
    RepairsDetail,
    RepairsEntry,
    render_combined_pdf,
    render_property_pdf,
)

ZERO = Decimal("0.00")
GENERATED = date(2025, 1, 2)
_LINES = list(range(3, 20))


def _report(
    *,
    imported_line: int | None = None,
    line12: Line12Detail | None = None,
    line14: Decimal = ZERO,
    name: str = "Maple House",
    pid: str = "p1",
) -> ScheduleEReport:
    lines = tuple(
        ReportLine(
            n, f"Label {n}", "income" if n <= 4 else "expense",
            line14 if n == 14 else ZERO, includes_imported=(n == imported_line),
        )
        for n in _LINES
    )
    header = ReportHeader(pid, name, "1 Main Street", "Duplex", 2024, 365, 0)
    return ScheduleEReport(
        header, lines, (), ReportTotals(ZERO, ZERO, ZERO), line12 or Line12Detail()
    )


def _pages(pdf: bytes) -> list[str]:
    reader = PdfReader(io.BytesIO(pdf))
    return [" ".join((p.extract_text() or "").split()) for p in reader.pages]


def _text(pdf: bytes) -> str:
    return " ".join(_pages(pdf))


def _repairs(entered: Decimal | None, source: str = "itemized") -> RepairsDetail:
    entries = (
        RepairsEntry("b", "2024-03-01", "Fix sink", Decimal("120.00")),
        RepairsEntry("a", "2024-02-01", "Patch roof", Decimal("80.50")),
    )
    return RepairsDetail(entries, entered, Decimal("200.50"), Decimal("200.50"), source)


def test_all_zero_report_is_valid_pdf() -> None:
    pdf = render_property_pdf(_report(), None, GENERATED)
    assert pdf.startswith(b"%PDF")
    reader = PdfReader(io.BytesIO(pdf))
    assert len(reader.pages) >= 1
    text = _text(pdf)
    assert "$0.00" in text
    assert "No other expenses itemized" in text


def test_line12_wording_loan_generated() -> None:
    detail = Line12Detail(source="loan-generated")
    assert LINE12_FROM_LOAN in _text(render_property_pdf(_report(line12=detail), None, GENERATED))


def test_line12_wording_transaction_entered() -> None:
    text = _text(render_property_pdf(_report(), None, GENERATED))
    assert LINE12_FROM_TRANSACTIONS in text
    assert "hand-entered" not in text


def test_line12_wording_superseded_interest() -> None:
    sup = SupersededManualInterest(amount=Decimal("1234.50"), count=2)
    detail = Line12Detail(source="loan-generated", superseded_manual_interest=sup)
    text = _text(render_property_pdf(_report(line12=detail), None, GENERATED))
    assert "2 hand-entered mortgage interest transactions totaling $1,234.50 were not used" in text

    one = SupersededManualInterest(amount=Decimal("5.00"), count=1)
    detail = Line12Detail(source="loan-generated", superseded_manual_interest=one)
    text = _text(render_property_pdf(_report(line12=detail), None, GENERATED))
    assert "1 hand-entered mortgage interest transaction totaling $5.00 were not used" in text


def test_combined_line12_superseded_wording() -> None:
    sup = SupersededManualInterest(amount=Decimal("300.00"), count=3)
    combined = CombinedScheduleEReport(
        2024, (_report(),), ReportTotals(ZERO, ZERO, ZERO),
        Line12Portfolio(Decimal("9000.00"), sup),
    )
    text = _text(render_combined_pdf(combined, {}, GENERATED))
    assert "Portfolio Line 12 total: $9,000.00." in text
    assert "3 hand-entered mortgage interest transactions totaling $300.00" in text


def test_dagger_footnote_only_when_a_line_is_imported() -> None:
    marked = _text(render_property_pdf(_report(imported_line=9), None, GENERATED))
    assert "Includes values imported from a filed Schedule E." in marked
    assert marked.count(IMPORTED_FOOTNOTE) == 1
    assert f"Label 9 {IMPORTED_MARKER}" in marked

    plain = _text(render_property_pdf(_report(), None, GENERATED))
    assert "imported from a filed Schedule E" not in plain
    assert IMPORTED_MARKER not in plain


def test_repairs_appendix_with_entered_total() -> None:
    repairs = _repairs(Decimal("250.00"), "entered_total")
    text = _text(render_property_pdf(_report(line14=Decimal("250.00")), repairs, GENERATED))
    appendix = text[text.index("Appendix A"):]
    assert "Entered total: $250.00" in appendix
    assert NO_TOTAL_ENTERED not in appendix
    assert "Itemized entries total: $200.50" in appendix
    assert "Line 14 amount: $250.00" in appendix
    assert "Line 14 uses the total you entered." in appendix
    assert REPAIRS_REVIEW_SENTENCE in appendix
    assert appendix.index("Patch roof") < appendix.index("Fix sink")  # date order


def test_repairs_appendix_without_entered_total() -> None:
    repairs = _repairs(None)
    text = _text(render_property_pdf(_report(line14=Decimal("200.50")), repairs, GENERATED))
    appendix = text[text.index("Appendix A"):]
    assert f"Entered total: {NO_TOTAL_ENTERED}" in appendix
    assert "Line 14 uses your itemized entries." in appendix


def test_no_appendix_without_entries() -> None:
    empty = RepairsDetail((), None, ZERO, ZERO, "none")
    for repairs in (None, empty):
        text = _text(render_property_pdf(_report(), repairs, GENERATED))
        assert "Appendix A" not in text
        assert REPAIRS_REVIEW_SENTENCE not in text


def test_disclaimer_on_every_page() -> None:
    many = tuple(
        RepairsEntry(f"{i:03d}", "2024-01-01", f"Job {i}", Decimal("1.00")) for i in range(150)
    )
    repairs = RepairsDetail(many, None, Decimal("150.00"), Decimal("150.00"), "itemized")
    pdf = render_property_pdf(_report(), repairs, GENERATED)
    pages = _pages(pdf)
    assert len(pages) >= 3
    normalized = " ".join(DISCLAIMER.split())
    for number, page in enumerate(pages, start=1):
        assert normalized in page
        assert f"Page {number} of {len(pages)}" in page
        assert "Maple House, tax year 2024" in page

    combined = CombinedScheduleEReport(
        2024, tuple(_report(name=f"P{i}", pid=f"p{i}") for i in range(4)),
        ReportTotals(ZERO, ZERO, ZERO),
    )
    for page in _pages(render_combined_pdf(combined, {}, GENERATED)):
        assert normalized in page


# --- Source scan ---------------------------------------------------------------

_SOURCE = Path(report_pdf.__file__).read_text(encoding="utf-8")
_MONEY_NAMES = {
    "amount", "total", "net", "total_income", "total_expenses", "itemized_sum",
    "entered_total", "line_total", "loan_interest", "value", "Decimal",
}
_ARITH = (ast.Add, ast.Sub, ast.Mult, ast.Div, ast.FloorDiv, ast.Mod, ast.Pow)


def _mentions_money(node: ast.AST) -> bool:
    """True when ``node`` names a money value; text built in f-strings is skipped."""
    if isinstance(node, ast.JoinedStr):
        return False
    if isinstance(node, ast.Name) and node.id in _MONEY_NAMES:
        return True
    if isinstance(node, ast.Attribute) and node.attr in _MONEY_NAMES:
        return True
    return any(_mentions_money(child) for child in ast.iter_child_nodes(node))


def test_source_has_no_money_arithmetic() -> None:
    offenders: list[str] = []
    for node in ast.walk(ast.parse(_SOURCE)):
        if isinstance(node, ast.BinOp) and isinstance(node.op, _ARITH):
            if _mentions_money(node.left) or _mentions_money(node.right):
                offenders.append(f"line {node.lineno}: binary operator")
        elif isinstance(node, ast.AugAssign) and isinstance(node.op, _ARITH):
            if _mentions_money(node.target) or _mentions_money(node.value):
                offenders.append(f"line {node.lineno}: augmented assignment")
        elif isinstance(node, ast.UnaryOp) and isinstance(node.op, ast.USub):
            if _mentions_money(node.operand):
                offenders.append(f"line {node.lineno}: negation")
        elif isinstance(node, ast.Call):
            func = node.func
            name = func.id if isinstance(func, ast.Name) else getattr(func, "attr", "")
            if name in {"sum", "quantize", "fsum", "round"}:
                offenders.append(f"line {node.lineno}: {name}()")
    assert offenders == []


def test_scan_detects_money_arithmetic() -> None:
    bad = ast.parse("x = report.totals.net + line.total\ny = sum(a)\nz = amount.quantize(q)")
    hits = [
        n for n in ast.walk(bad)
        if (isinstance(n, ast.BinOp) and _mentions_money(n))
        or (isinstance(n, ast.Call) and getattr(n.func, "attr", getattr(n.func, "id", ""))
            in {"sum", "quantize"})
    ]
    assert len(hits) == 3


def test_source_has_no_precedence_terms() -> None:
    # The Line 12 note must say loan interest "took precedence"; that fixed sentence is allowed.
    allowed = "because loan interest took precedence"
    stripped = _SOURCE.replace(allowed, "")
    assert not re.search(r"precedence", stripped, re.IGNORECASE)
    for term in ("carryforward", "carry_forward", "tolerance"):
        assert term not in stripped.lower()
