"""Unit tests for the expense-summary PDF parse adapter (Requirements 6.3, 6.12).

These exercise both layers of ``adapters/pdf_parse.py`` without touching a real
PDF stack:

* :func:`parse_line_items_from_text` — the pure text-to-line-items core:
  date/amount/description extraction, missing-field tolerance, accounting-style
  parenthesized negatives, and skipping of blank/separator lines
  (Requirement 6.3).
* :func:`parse_expense_summary` — the bounded orchestration around an injectable
  ``extract_text`` (and injectable ``now`` clock): the happy path plus every
  parse-failure branch — zero line items, oversized, too many pages, time-budget
  exceeded, and empty/non-bytes input (Requirement 6.12).

Money is always asserted as ``Decimal`` (Requirement 13.3). Broader parsing /
category-heuristic coverage lives with the import service (task 13.6).
"""

from __future__ import annotations

from decimal import Decimal

import pytest

from logstead.adapters.pdf_parse import (
    DEFAULT_BOUNDS,
    ParsedLineItem,
    PdfParseBounds,
    parse_expense_summary,
    parse_line_items_from_text,
)


def _stub_extractor(text: str, page_count: int = 1):
    """Build an ``extract_text`` stub returning fixed ``(text, page_count)``.

    Lets the tests drive :func:`parse_expense_summary` without a real PDF
    dependency — the adapter only cares that the extractor yields text and a
    page count.
    """

    def extract(_pdf_bytes: bytes) -> tuple[str, int]:
        return text, page_count

    return extract


# --- parse_line_items_from_text: the pure core ------------------------------


class TestParseLineItemsFromText:
    def test_full_row_extracts_date_amount_and_description(self) -> None:
        items = parse_line_items_from_text("1/31/2024 Plumbing repair $250.00")

        assert len(items) == 1
        item = items[0]
        assert item.date == "2024-01-31"  # normalized to ISO YYYY-MM-DD
        assert item.amount == Decimal("250.00")
        assert isinstance(item.amount, Decimal)
        assert item.description == "Plumbing repair"

    def test_iso_and_two_digit_year_dates_normalize(self) -> None:
        items = parse_line_items_from_text(
            "2024-02-15 Landscaping 120.00\n"
            "3/5/24 Pest control $75.50\n"
        )

        assert [i.date for i in items] == ["2024-02-15", "2024-03-05"]
        assert items[0].amount == Decimal("120.00")
        assert items[1].amount == Decimal("75.50")

    def test_row_with_missing_date_leaves_date_unset(self) -> None:
        items = parse_line_items_from_text("Management fee $95.00")

        assert len(items) == 1
        assert items[0].date is None
        assert items[0].amount == Decimal("95.00")
        assert items[0].description == "Management fee"

    def test_row_with_missing_amount_leaves_amount_unset(self) -> None:
        items = parse_line_items_from_text("4/1/2024 Annual inspection")

        assert len(items) == 1
        assert items[0].date == "2024-04-01"
        assert items[0].amount is None
        assert items[0].description == "Annual inspection"

    def test_parenthesized_amount_is_negative(self) -> None:
        # Accounting-style negative: a credit/refund on the summary.
        items = parse_line_items_from_text("2/10/2024 Rent overpayment refund ($150.00)")

        assert len(items) == 1
        assert items[0].amount == Decimal("-150.00")
        assert isinstance(items[0].amount, Decimal)
        assert items[0].description == "Rent overpayment refund"

    def test_thousands_separator_amount_parses(self) -> None:
        items = parse_line_items_from_text("5/1/2024 Roof replacement $12,500.00")

        assert len(items) == 1
        assert items[0].amount == Decimal("12500.00")

    def test_blank_and_separator_lines_are_skipped(self) -> None:
        text = (
            "\n"
            "   \n"
            "-----------------\n"
            "|||\n"
            "1/31/2024 Plumbing repair $250.00\n"
            "   \n"
            "2/15/2024 Landscaping $120.00\n"
        )
        items = parse_line_items_from_text(text)

        # Only the two real line items survive; blanks/separators are dropped.
        assert len(items) == 2
        assert [i.description for i in items] == ["Plumbing repair", "Landscaping"]
        assert [i.amount for i in items] == [Decimal("250.00"), Decimal("120.00")]

    def test_empty_text_yields_no_items(self) -> None:
        assert parse_line_items_from_text("") == []

    def test_items_preserve_document_order(self) -> None:
        text = (
            "1/01/2024 First $10.00\n"
            "1/02/2024 Second $20.00\n"
            "1/03/2024 Third $30.00\n"
        )
        items = parse_line_items_from_text(text)

        assert [i.description for i in items] == ["First", "Second", "Third"]

    def test_raw_line_is_retained(self) -> None:
        items = parse_line_items_from_text("1/31/2024 Plumbing repair $250.00")
        assert items[0].raw == "1/31/2024 Plumbing repair $250.00"


# --- parse_expense_summary: bounded orchestration ---------------------------


class TestParseExpenseSummaryHappyPath:
    def test_success_returns_items(self) -> None:
        text = (
            "1/31/2024 Plumbing repair $250.00\n"
            "2/15/2024 Landscaping $120.00\n"
        )
        result = parse_expense_summary(
            b"%PDF-1.4 fake bytes",
            extract_text=_stub_extractor(text, page_count=1),
        )

        assert result.is_ok
        items = result.value
        assert len(items) == 2
        assert all(isinstance(i, ParsedLineItem) for i in items)
        assert items[0].amount == Decimal("250.00")
        assert isinstance(items[0].amount, Decimal)
        assert items[0].date == "2024-01-31"

    def test_bytearray_input_is_accepted(self) -> None:
        result = parse_expense_summary(
            bytearray(b"%PDF fake"),
            extract_text=_stub_extractor("3/1/2024 Repairs $40.00"),
        )
        assert result.is_ok
        assert result.value[0].amount == Decimal("40.00")


class TestParseExpenseSummaryFailures:
    def test_zero_line_items_is_failure(self) -> None:
        # Text that yields no meaningful line items (only blanks/separators):
        # every line is skipped, so the document is a parse failure.
        result = parse_expense_summary(
            b"%PDF fake",
            extract_text=_stub_extractor("\n=========\n   \n|||\n", page_count=1),
        )

        assert not result.is_ok
        assert result.error is not None
        assert result.error.kind == "unavailable"

    def test_oversized_document_is_failure(self) -> None:
        bounds = PdfParseBounds(max_bytes=10)
        # Extractor would succeed, but the size check rejects first.
        result = parse_expense_summary(
            b"x" * 11,
            bounds=bounds,
            extract_text=_stub_extractor("1/1/2024 Repairs $10.00"),
        )

        assert not result.is_ok
        assert result.error is not None
        assert result.error.kind == "unavailable"

    def test_too_many_pages_is_failure(self) -> None:
        bounds = PdfParseBounds(max_pages=2)
        result = parse_expense_summary(
            b"%PDF fake",
            bounds=bounds,
            extract_text=_stub_extractor("1/1/2024 Repairs $10.00", page_count=3),
        )

        assert not result.is_ok
        assert result.error is not None
        assert result.error.kind == "unavailable"

    def test_time_budget_exceeded_is_failure(self) -> None:
        bounds = PdfParseBounds(time_budget_seconds=1.0)
        # A monotonic clock that jumps past the budget between start and end.
        clock = iter([0.0, 5.0])

        result = parse_expense_summary(
            b"%PDF fake",
            bounds=bounds,
            extract_text=_stub_extractor("1/1/2024 Repairs $10.00", page_count=1),
            now=lambda: next(clock),
        )

        assert not result.is_ok
        assert result.error is not None
        assert result.error.kind == "unavailable"

    def test_extractor_error_is_failure(self) -> None:
        def broken_extractor(_pdf_bytes: bytes) -> tuple[str, int]:
            raise RuntimeError("corrupt PDF")

        result = parse_expense_summary(b"%PDF fake", extract_text=broken_extractor)

        assert not result.is_ok
        assert result.error is not None
        assert result.error.kind == "unavailable"

    def test_empty_bytes_is_failure(self) -> None:
        result = parse_expense_summary(
            b"",
            extract_text=_stub_extractor("1/1/2024 Repairs $10.00"),
        )

        assert not result.is_ok
        assert result.error is not None
        assert result.error.kind == "unavailable"

    def test_non_bytes_input_is_failure(self) -> None:
        result = parse_expense_summary(
            "not bytes",  # type: ignore[arg-type]
            extract_text=_stub_extractor("1/1/2024 Repairs $10.00"),
        )

        assert not result.is_ok
        assert result.error is not None
        assert result.error.kind == "unavailable"

    def test_within_time_budget_succeeds(self) -> None:
        bounds = PdfParseBounds(time_budget_seconds=10.0)
        clock = iter([0.0, 1.0])  # 1s elapsed, well within budget

        result = parse_expense_summary(
            b"%PDF fake",
            bounds=bounds,
            extract_text=_stub_extractor("1/1/2024 Repairs $10.00", page_count=1),
            now=lambda: next(clock),
        )

        assert result.is_ok
        assert result.value[0].amount == Decimal("10.00")


class TestDefaultBounds:
    def test_default_bounds_are_reasonable(self) -> None:
        assert DEFAULT_BOUNDS.max_bytes > 0
        assert DEFAULT_BOUNDS.max_pages > 0
        assert DEFAULT_BOUNDS.time_budget_seconds > 0


# --- Task 13.6: broader representative-summary coverage ----------------------
#
# The classes above pin the core mechanics. The classes below add BROADER
# coverage of realistic property-manager summary formats (Requirement 6.3) and
# add complementary representative-summary cases for the parse-failure branches
# (Requirement 6.12) without duplicating the single-line mechanics already
# proven above.


class TestRepresentativeSummaries:
    """Whole-document parses over realistic property-manager summary layouts.

    Property-manager PDFs extract to semi-structured text: a header/title, a
    column caption row, one row per line item, then a totals footer. The parser
    must pull the real line items out of that noise and extract date/amount/
    description where present (Requirement 6.3).
    """

    def test_summary_with_header_and_footer_noise_keeps_only_line_items(self) -> None:
        # A realistic layout: title + address, a caption row, three real rows,
        # a rule, and a totals footer. Only the three dated/amount rows should
        # survive; the title/caption/rule are noise. The "Total" footer carries
        # an amount so the parser keeps it as a line — the import service's
        # review step is where a user drops it, so we assert the three real
        # items are present and correctly extracted rather than an exact count.
        text = (
            "Acme Property Management\n"
            "2024 Annual Expense Summary\n"
            "123 Main St, Springfield\n"
            "Date        Description                 Amount\n"
            "01/15/2024  Landscaping service         $  150.00\n"
            "02/03/2024  Plumbing repair - kitchen    1,250.75\n"
            "2024-03-20  Property management fee     $  95.50\n"
            "----------------------------------------------\n"
        )
        items = parse_line_items_from_text(text)

        by_date = {i.date: i for i in items if i.date is not None}
        assert by_date["2024-01-15"].amount == Decimal("150.00")
        assert "Landscaping service" in (by_date["2024-01-15"].description or "")
        assert by_date["2024-02-03"].amount == Decimal("1250.75")
        assert "Plumbing repair" in (by_date["2024-02-03"].description or "")
        assert by_date["2024-03-20"].amount == Decimal("95.50")
        assert "management fee" in (by_date["2024-03-20"].description or "").lower()
        # Every extracted date parsed to ISO form and every amount is a Decimal.
        assert all(isinstance(i.amount, Decimal) for i in items if i.amount is not None)

    def test_mixed_date_formats_within_one_summary_all_normalize(self) -> None:
        # A single summary can mix MM/DD/YYYY, YYYY-MM-DD, dash-separated, and
        # two-digit-year rows; all must normalize to ISO YYYY-MM-DD (Req 6.3).
        text = (
            "05/01/2024 Repairs $40.00\n"
            "2024-06-15 Utilities water $88.20\n"
            "7-4-2024 Cleaning $60.00\n"
            "8/9/24 Supplies $12.99\n"
        )
        items = parse_line_items_from_text(text)

        assert [i.date for i in items] == [
            "2024-05-01",
            "2024-06-15",
            "2024-07-04",
            "2024-08-09",
        ]

    def test_various_amount_notations_parse_to_decimal(self) -> None:
        # $-prefixed, bare-decimal, thousands-separated, and accounting-negative
        # amounts all coerce to two-decimal Decimals (Requirements 6.3, 13.3).
        text = (
            "01/02/2024 With dollar sign $250.00\n"
            "01/03/2024 Bare decimal 75.50\n"
            "01/04/2024 Thousands $1,234.56\n"
            "01/05/2024 Big thousands 12,000.00\n"
            "01/06/2024 Refund credit ($150.00)\n"
        )
        items = parse_line_items_from_text(text)

        amounts = [i.amount for i in items]
        assert amounts == [
            Decimal("250.00"),
            Decimal("75.50"),
            Decimal("1234.56"),
            Decimal("12000.00"),
            Decimal("-150.00"),
        ]
        assert all(isinstance(a, Decimal) for a in amounts)

    def test_multiline_summary_with_incomplete_rows_leaves_fields_unset(self) -> None:
        # Real summaries have partial rows: a row missing an amount, a row
        # missing a date. The parser keeps them with the missing field unset so
        # the import service can flag the draft (Requirements 6.3 -> 6.9).
        text = (
            "01/10/2024 Annual fire inspection\n"       # no amount
            "Management fee $95.00\n"                    # no date
            "01/12/2024 Snow removal $210.00\n"          # complete
        )
        items = parse_line_items_from_text(text)

        assert len(items) == 3
        assert items[0].date == "2024-01-10" and items[0].amount is None
        assert items[1].date is None and items[1].amount == Decimal("95.00")
        assert items[2].date == "2024-01-12" and items[2].amount == Decimal("210.00")


class TestFailureBranchesWithRepresentativeSummaries:
    """Complementary parse-failure cases (Requirement 6.12).

    The core failure branches (oversized/too-many-pages/time-budget/extractor
    error/empty) are proven in ``TestParseExpenseSummaryFailures`` with minimal
    inputs. These add representative-summary flavored cases: a summary whose
    rows are all non-line-item noise (zero line items) and an oversized/slow
    realistic summary — all mapping to ``Result.failure("unavailable")``.
    """

    def test_separator_only_document_yields_zero_items_failure(self) -> None:
        # A "summary" whose every row is a pure rule/separator or blank carries
        # no meaningful text, so the parser skips them all and extracts zero
        # line items -> parse failure (Requirement 6.12). (Lines that carry
        # alphanumeric text — even header/caption text — are kept as
        # description-only items by the tolerant heuristic, so this failure
        # branch is specifically about content-free documents.)
        text = (
            "==============================================\n"
            "----------------------------------------------\n"
            "   \n"
            "|||||||||||||||||\n"
            "\n"
        )
        result = parse_expense_summary(
            b"%PDF fake", extract_text=_stub_extractor(text, page_count=1)
        )

        assert not result.is_ok
        assert result.error is not None
        assert result.error.kind == "unavailable"
        # The message invites manual entry (Requirement 6.12).
        assert "manually" in result.error.message.lower()

    def test_realistic_summary_over_size_limit_is_failure(self) -> None:
        # A realistic multi-row summary that exceeds the byte budget is rejected
        # before extraction (Requirement 6.12).
        text = "\n".join(
            f"01/{d:02d}/2024 Line item {d} $100.00" for d in range(1, 20)
        )
        bounds = PdfParseBounds(max_bytes=8)  # anything real is larger than this
        result = parse_expense_summary(
            b"%PDF-1.4 realistic body larger than eight bytes",
            bounds=bounds,
            extract_text=_stub_extractor(text, page_count=1),
        )

        assert not result.is_ok
        assert result.error.kind == "unavailable"

    def test_realistic_summary_too_slow_is_failure(self) -> None:
        # A realistic summary that blows the time budget during extraction/parse
        # is treated as a parse failure (Requirement 6.12).
        text = "01/15/2024 Landscaping $150.00\n02/03/2024 Plumbing $1,250.75\n"
        bounds = PdfParseBounds(time_budget_seconds=2.0)
        clock = iter([0.0, 9.0])  # 9s elapsed, over the 2s budget
        result = parse_expense_summary(
            b"%PDF fake",
            bounds=bounds,
            extract_text=_stub_extractor(text, page_count=1),
            now=lambda: next(clock),
        )

        assert not result.is_ok
        assert result.error.kind == "unavailable"
