"""Pure ReportLab helpers for the Schedule E PDF worksheet.

This module performs no I/O, reads no clock, and does no money arithmetic.
Every figure arrives already computed by ``ReportingService``. User text
reaches a ReportLab ``Paragraph`` only through :func:`pdf_text`, which
escapes markup, because ``Paragraph`` parses an XML-like mini language.
"""

from __future__ import annotations

import html
import io
import unicodedata
from collections.abc import Mapping, Sequence
from dataclasses import dataclass
from datetime import date
from decimal import Decimal
from typing import TypeVar

from reportlab.lib import colors
from reportlab.lib.enums import TA_RIGHT
from reportlab.lib.pagesizes import letter
from reportlab.lib.styles import ParagraphStyle, getSampleStyleSheet
from reportlab.pdfgen import canvas as _canvas
from reportlab.platypus import PageBreak, Paragraph, SimpleDocTemplate, Spacer, Table, TableStyle

from logstead.services.report import CombinedScheduleEReport, ScheduleEReport

T = TypeVar("T")

# --- Fixed strings (no AI, no generated prose) --------------------------------

WORKSHEET_NOTE = "Laid out like Schedule E Part I. Not an IRS form."
DISCLAIMER = (
    "Built from your own records as an organizing aid. Not an IRS form and not "
    "tax advice. It does not tell you what to report."
)
IMPORTED_MARKER = "\u2020"  # dagger; encodable in Windows-1252
IMPORTED_FOOTNOTE = (
    f"{IMPORTED_MARKER} Includes values imported from a filed Schedule E."
)
LINE12_FROM_LOAN = "Line 12 comes from the loan schedule."
LINE12_FROM_TRANSACTIONS = "Line 12 comes from transactions you entered."
NO_OTHER_ITEMS = "No other expenses itemized"
NO_TOTAL_ENTERED = "No total entered"
REPAIRS_REVIEW_SENTENCE = (
    "You decide whether each entry is a repair or an improvement."
)

COMBINED_COLUMN_LABELS = ("A", "B", "C")
DEFAULT_CHUNK_SIZE = len(COMBINED_COLUMN_LABELS)


# --- Models -------------------------------------------------------------------


@dataclass(frozen=True)
class RepairsEntry:
    """One itemized Repairs entry (Schedule E line 14), copied by the caller."""

    id: str
    date: str
    description: str
    amount: Decimal


@dataclass(frozen=True)
class RepairsDetail:
    """Repairs summary copied from ``ItemizedSummary`` by the caller."""

    entries: tuple[RepairsEntry, ...]
    entered_total: Decimal | None
    itemized_sum: Decimal
    line_total: Decimal
    line_source: str


# --- Pure helpers -------------------------------------------------------------


def format_money(value: Decimal) -> str:
    """Format as ``$1,234.50``, or ``($1,234.50)`` when negative."""
    text = f"${abs(value):,.2f}"
    return f"({text})" if value < 0 and text != "$0.00" else text


def _encodable(char: str) -> str:
    try:
        char.encode("cp1252")
    except UnicodeEncodeError:
        return "?"
    return char


def plain_pdf_text(value: str | None) -> str:
    """Return text safe for the standard Helvetica font, without escaping.

    Control characters are removed. Characters outside Windows-1252 become
    ``?``. Use this for ``drawString`` and for document metadata.
    """
    if not value:
        return ""
    kept = (c for c in value if unicodedata.category(c) != "Cc")
    return "".join(_encodable(c) for c in kept)


def pdf_text(value: str | None) -> str:
    """Return ``value`` as literal text for a ReportLab ``Paragraph``.

    Applies :func:`plain_pdf_text`, then escapes ``&``, ``<``, and ``>`` so
    no markup (``<img>``, ``<font>``, ``<a>``) is interpreted.
    """
    return html.escape(plain_pdf_text(value), quote=False)


def chunk_columns(properties: Sequence[T], size: int = DEFAULT_CHUNK_SIZE) -> list[list[T]]:
    """Split ``properties`` into consecutive groups of at most ``size``."""
    if size < 1:
        raise ValueError("size must be at least 1")
    return [list(properties[i : i + size]) for i in range(0, len(properties), size)]


# --- Page numbering canvas ----------------------------------------------------


class NumberedCanvas(_canvas.Canvas):
    """Canvas that draws a footer with "Page N of M" on every page.

    ReportLab only knows the page count at the end, so page states are held
    back and drawn in ``save``. Subclass through :func:`make_numbered_canvas`
    to set the footer text.
    """

    footer_left: str = DISCLAIMER
    footer_middle: str = ""
    footer_generated: str = ""

    def __init__(self, *args, **kwargs) -> None:
        super().__init__(*args, **kwargs)
        self._saved_page_states: list[dict] = []

    def showPage(self) -> None:  # noqa: N802 - ReportLab API name
        self._saved_page_states.append(dict(self.__dict__))
        self._startPage()

    def save(self) -> None:
        total = len(self._saved_page_states)
        for state in self._saved_page_states:
            self.__dict__.update(state)
            self._draw_footer(total)
            super().showPage()
        super().save()

    def _draw_footer(self, total: int) -> None:
        width = letter[0]
        self.setFont("Helvetica", 7)
        self.drawString(36, 34, self.footer_left)
        self.drawString(36, 24, self.footer_middle)
        self.drawRightString(width - 36, 24, f"Page {self._pageNumber} of {total}")
        if self.footer_generated:
            self.drawRightString(width - 36, 34, self.footer_generated)


def make_numbered_canvas(
    property_name: str, tax_year: int | str, generated_on: date
) -> type[NumberedCanvas]:
    """Return a ``NumberedCanvas`` subclass with the footer text filled in."""
    middle = plain_pdf_text(f"{property_name}, tax year {tax_year}")
    generated = f"Generated {generated_on.isoformat()}"

    class _FooterCanvas(NumberedCanvas):
        footer_left = plain_pdf_text(DISCLAIMER)
        footer_middle = middle
        footer_generated = generated

    return _FooterCanvas


# --- Property report ----------------------------------------------------------

_REPAIRS_LINE = 14
_REPAIRS_SOURCE_NOTES = {
    "entered_total": "Line 14 uses the total you entered.",
    "itemized": "Line 14 uses your itemized entries.",
    "none": "Line 14 has no entered total and no itemized entries.",
}
_PAGE_MARGIN = 36


def _styles() -> dict[str, ParagraphStyle]:
    base = getSampleStyleSheet()["Normal"]
    return {
        "title": ParagraphStyle(
            "t", parent=base, fontName="Helvetica-Bold", fontSize=16, leading=20
        ),
        "h2": ParagraphStyle(
            "h2", parent=base, fontName="Helvetica-Bold", fontSize=11, leading=14,
            spaceBefore=10, spaceAfter=4,
        ),
        "body": ParagraphStyle("b", parent=base, fontName="Helvetica", fontSize=9, leading=11),
        "small": ParagraphStyle("s", parent=base, fontName="Helvetica", fontSize=8, leading=10),
        "right": ParagraphStyle(
            "r", parent=base, fontName="Helvetica", fontSize=9, leading=11, alignment=TA_RIGHT
        ),
        "bold": ParagraphStyle("bd", parent=base, fontName="Helvetica-Bold", fontSize=9, leading=11),
        "boldright": ParagraphStyle(
            "br", parent=base, fontName="Helvetica-Bold", fontSize=9, leading=11, alignment=TA_RIGHT
        ),
    }


def _p(text: str | None, style: ParagraphStyle) -> Paragraph:
    return Paragraph(pdf_text(text), style)


def _table(rows: list[list], widths: list[float], bold_rows: Sequence[int] = (), section_rows: Sequence[int] = ()) -> Table:
    # splitInRow lets a single very tall row (a very long description) break
    # across pages instead of raising LayoutError.
    table = Table(rows, colWidths=widths, repeatRows=1, splitInRow=1)
    commands = [
        ("VALIGN", (0, 0), (-1, -1), "TOP"),
        ("BACKGROUND", (0, 0), (-1, 0), colors.lightgrey),
        ("LINEBELOW", (0, 0), (-1, -1), 0.25, colors.grey),
    ]
    for row in section_rows:
        commands.append(("BACKGROUND", (0, row), (-1, row), colors.whitesmoke))
    table.setStyle(TableStyle(commands))
    return table


def _line12_note(report: ScheduleEReport) -> str:
    detail = report.line12
    text = LINE12_FROM_LOAN if detail.source == "loan-generated" else LINE12_FROM_TRANSACTIONS
    sup = detail.superseded_manual_interest
    if sup.count > 0:
        noun = "transaction" if sup.count == 1 else "transactions"
        text += (
            f" {sup.count} hand-entered mortgage interest {noun} totaling "
            f"{format_money(sup.amount)} were not used because loan interest took precedence."
        )
    return text


def _repairs_appendix(
    report: ScheduleEReport, repairs: RepairsDetail, styles: dict[str, ParagraphStyle]
) -> list:
    line14 = report.line(_REPAIRS_LINE)
    line14_amount = line14.total if line14 is not None else repairs.line_total
    entered = (
        NO_TOTAL_ENTERED if repairs.entered_total is None else format_money(repairs.entered_total)
    )
    flow: list = [
        _p("Appendix A, Repairs detail (line 14)", styles["h2"]),
        _p(f"Entered total: {entered}", styles["body"]),
        _p(f"Itemized entries total: {format_money(repairs.itemized_sum)}", styles["body"]),
        _p(f"Line 14 amount: {format_money(line14_amount)}", styles["body"]),
        _p(
            _REPAIRS_SOURCE_NOTES.get(repairs.line_source, _REPAIRS_SOURCE_NOTES["none"]),
            styles["body"],
        ),
        Spacer(1, 6),
    ]
    ordered = sorted(repairs.entries, key=lambda e: (e.date, e.id))
    rows: list[list] = [[_p("Date", styles["bold"]), _p("Description", styles["bold"]), _p("Amount", styles["boldright"])]]
    for entry in ordered:
        rows.append([
            _p(entry.date, styles["body"]),
            _p(entry.description, styles["body"]),
            _p(format_money(entry.amount), styles["right"]),
        ])
    flow.append(_table(rows, [70, 380, 90]))
    flow.append(Spacer(1, 6))
    flow.append(_p(REPAIRS_REVIEW_SENTENCE, styles["small"]))
    return flow


def render_property_pdf(
    report: ScheduleEReport, repairs: RepairsDetail | None, generated_on: date
) -> bytes:
    """Render one property's Schedule E worksheet as PDF bytes.

    Deterministic: ``invariant=1`` removes timestamps and random ids, and the
    only date printed is ``generated_on``. All figures come from ``report``.
    """
    styles = _styles()
    header = report.header
    buffer = io.BytesIO()
    doc = SimpleDocTemplate(
        buffer,
        pagesize=letter,
        leftMargin=_PAGE_MARGIN,
        rightMargin=_PAGE_MARGIN,
        topMargin=_PAGE_MARGIN,
        bottomMargin=60,
        title=plain_pdf_text(f"Schedule E worksheet, {header.property_name}, {header.tax_year}"),
        author="Logstead",
        invariant=1,
    )

    flow: list = [
        _p("Schedule E, Part I worksheet", styles["title"]),
        _p(header.property_name, styles["h2"]),
        _p(WORKSHEET_NOTE, styles["small"]),
        Spacer(1, 8),
    ]

    info = [
        [_p("Address", styles["bold"]), _p(header.address, styles["body"])],
        [_p("Property type", styles["bold"]), _p(header.property_type or "", styles["body"])],
        [_p("Tax year", styles["bold"]), _p(str(header.tax_year), styles["body"])],
        [_p("Fair rental days", styles["bold"]), _p(str(header.fair_rental_days), styles["body"])],
        [_p("Personal use days", styles["bold"]), _p(str(header.personal_use_days), styles["body"])],
    ]
    info_table = Table(info, colWidths=[110, 430])
    info_table.setStyle(TableStyle([("VALIGN", (0, 0), (-1, -1), "TOP")]))
    flow += [info_table, Spacer(1, 10)]

    rows: list[list] = [[_p("Line", styles["bold"]), _p("Description", styles["bold"]), _p("Amount", styles["boldright"])]]
    section_rows: list[int] = []
    bold_rows: list[int] = []
    any_imported = False

    def add_section(label: str) -> None:
        section_rows.append(len(rows))
        rows.append([_p("", styles["body"]), _p(label, styles["bold"]), _p("", styles["body"])])

    def add_total(number: str, label: str, amount: Decimal) -> None:
        bold_rows.append(len(rows))
        rows.append([
            _p(number, styles["bold"]), _p(label, styles["bold"]),
            _p(format_money(amount), styles["boldright"]),
        ])

    income = [ln for ln in report.lines if ln.kind == "income"]
    expense = [ln for ln in report.lines if ln.kind != "income"]

    def add_line(ln) -> None:
        nonlocal any_imported
        label = ln.label
        if ln.includes_imported:
            any_imported = True
            label = f"{label} {IMPORTED_MARKER}"
        rows.append([
            _p(str(ln.line), styles["body"]), _p(label, styles["body"]),
            _p(format_money(ln.total), styles["right"]),
        ])

    add_section("Income")
    for ln in income:
        add_line(ln)
    add_total("", "Total income", report.totals.total_income)
    add_section("Expenses")
    for ln in expense:
        add_line(ln)
    add_total("20", "Total expenses", report.totals.total_expenses)
    add_total("21", "Net income or (loss)", report.totals.net)

    flow.append(_table(rows, [40, 400, 100], bold_rows, section_rows))
    flow.append(Spacer(1, 6))
    if any_imported:
        flow.append(_p(IMPORTED_FOOTNOTE, styles["small"]))
    flow.append(_p(_line12_note(report), styles["small"]))

    flow.append(_p("Line 19, Other expenses", styles["h2"]))
    if report.other_items:
        other_rows: list[list] = [[_p("Description", styles["bold"]), _p("Amount", styles["boldright"])]]
        for item in report.other_items:
            other_rows.append([
                _p(item.description, styles["body"]),
                _p(format_money(item.amount), styles["right"]),
            ])
        flow.append(_table(other_rows, [440, 100]))
    else:
        flow.append(_p(NO_OTHER_ITEMS, styles["body"]))

    if repairs is not None and repairs.entries:
        flow.append(PageBreak())
        flow.extend(_repairs_appendix(report, repairs, styles))

    canvas_cls = make_numbered_canvas(header.property_name, header.tax_year, generated_on)
    doc.build(flow, canvasmaker=canvas_cls)
    return buffer.getvalue()


# --- Combined portfolio report ------------------------------------------------

_SHORT_ADDRESS_CHARS = 40
_COMBINED_LABEL_WIDTH = 180
_COMBINED_COLUMN_WIDTH = 120


def _short_address(address: str | None) -> str:
    text = address or ""
    if len(text) <= _SHORT_ADDRESS_CHARS:
        return text
    return text[: _SHORT_ADDRESS_CHARS - 3].rstrip() + "..."


def _portfolio_line12_note(combined: CombinedScheduleEReport) -> str:
    portfolio = combined.line12
    text = f"Portfolio Line 12 total: {format_money(portfolio.total)}."
    sup = portfolio.superseded_manual_interest
    if sup.count > 0:
        noun = "transaction" if sup.count == 1 else "transactions"
        text += (
            f" {sup.count} hand-entered mortgage interest {noun} totaling "
            f"{format_money(sup.amount)} were not used because loan interest took precedence."
        )
    return text


def _combined_chunk_table(
    chunk: Sequence[ScheduleEReport], styles: dict[str, ParagraphStyle]
) -> tuple[Table, bool]:
    """One table of up to three property columns. Returns (table, any_imported)."""
    head: list = [_p("Line", styles["bold"])]
    for label, report in zip(COMBINED_COLUMN_LABELS, chunk):
        head.append(
            Paragraph(
                f"<b>{label}</b> {pdf_text(report.header.property_name)}<br/>"
                f"{pdf_text(_short_address(report.header.address))}",
                styles["small"],
            )
        )
    rows: list[list] = [head]
    bold_rows: list[int] = []
    any_imported = False

    numbers = sorted({ln.line for report in chunk for ln in report.lines})
    labels: dict[int, str] = {}
    for report in chunk:
        for ln in report.lines:
            labels.setdefault(ln.line, ln.label)

    for number in numbers:
        row: list = [_p(f"{number}  {labels[number]}", styles["body"])]
        for report in chunk:
            ln = report.line(number)
            if ln is None:
                row.append(_p("", styles["right"]))
                continue
            text = format_money(ln.total)
            if ln.includes_imported:
                any_imported = True
                text = f"{text} {IMPORTED_MARKER}"
            row.append(_p(text, styles["right"]))
        rows.append(row)

    for number, label, attr in (
        ("", "Total income", "total_income"),
        ("20", "Total expenses", "total_expenses"),
        ("21", "Net income or (loss)", "net"),
    ):
        bold_rows.append(len(rows))
        text = f"{number}  {label}" if number else label
        row = [_p(text, styles["bold"])]
        for report in chunk:
            row.append(_p(format_money(getattr(report.totals, attr)), styles["boldright"]))
        rows.append(row)

    widths = [_COMBINED_LABEL_WIDTH] + [_COMBINED_COLUMN_WIDTH] * len(chunk)
    return _table(rows, widths, bold_rows), any_imported


def render_combined_pdf(
    combined: CombinedScheduleEReport,
    repairs: Mapping[str, RepairsDetail | None],
    generated_on: date,
) -> bytes:
    """Render the portfolio Schedule E worksheet as PDF bytes.

    ``repairs`` maps property id to its Repairs detail (or ``None``). One
    table is started for every three properties, columns labelled A, B, C.
    Deterministic and free of money arithmetic, like :func:`render_property_pdf`.
    """
    styles = _styles()
    tax_year = combined.tax_year
    buffer = io.BytesIO()
    doc = SimpleDocTemplate(
        buffer,
        pagesize=letter,
        leftMargin=_PAGE_MARGIN,
        rightMargin=_PAGE_MARGIN,
        topMargin=_PAGE_MARGIN,
        bottomMargin=60,
        title=plain_pdf_text(f"Schedule E worksheet, combined, {tax_year}"),
        author="Logstead",
        invariant=1,
    )

    flow: list = [
        _p("Schedule E, Part I worksheet", styles["title"]),
        _p(f"Combined portfolio, tax year {tax_year}", styles["h2"]),
        _p(WORKSHEET_NOTE, styles["small"]),
        Spacer(1, 8),
    ]

    any_imported = False
    for chunk in chunk_columns(combined.properties):
        table, imported = _combined_chunk_table(chunk, styles)
        any_imported = any_imported or imported
        flow += [table, Spacer(1, 10)]
    if any_imported:
        flow.append(_p(IMPORTED_FOOTNOTE, styles["small"]))

    flow.append(_p("Portfolio totals", styles["h2"]))
    totals_rows: list[list] = [[_p("Total", styles["bold"]), _p("Amount", styles["boldright"])]]
    for label, value in (
        ("Total income", combined.totals.total_income),
        ("Total expenses (line 20)", combined.totals.total_expenses),
        ("Net income or (loss) (line 21)", combined.totals.net),
    ):
        totals_rows.append([_p(label, styles["body"]), _p(format_money(value), styles["right"])])
    flow.append(_table(totals_rows, [400, 140]))
    flow.append(Spacer(1, 6))
    flow.append(_p(_portfolio_line12_note(combined), styles["small"]))

    for report in combined.properties:
        flow.append(_p(f"Line 19, Other expenses: {report.header.property_name}", styles["h2"]))
        if report.other_items:
            other_rows: list[list] = [
                [_p("Description", styles["bold"]), _p("Amount", styles["boldright"])]
            ]
            for item in report.other_items:
                other_rows.append([
                    _p(item.description, styles["body"]),
                    _p(format_money(item.amount), styles["right"]),
                ])
            flow.append(_table(other_rows, [440, 100]))
        else:
            flow.append(_p(NO_OTHER_ITEMS, styles["body"]))

    for report in combined.properties:
        detail = repairs.get(report.header.property_id)
        if detail is not None and detail.entries:
            flow.append(PageBreak())
            flow.append(_p(f"Property: {report.header.property_name}", styles["bold"]))
            flow.extend(_repairs_appendix(report, detail, styles))

    count = len(combined.properties)
    noun = "property" if count == 1 else "properties"
    canvas_cls = make_numbered_canvas(f"Combined portfolio, {count} {noun}", tax_year, generated_on)
    doc.build(flow, canvasmaker=canvas_cls)
    return buffer.getvalue()
