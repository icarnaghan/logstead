"""Shape/default tests for the Schedule E extraction service-layer models (Task 2.2).

Proves the dataclass field names/types match the documented wire shape, the
documented defaults hold (optionals default ``None``, list fields default to a
fresh empty list), and that ``ExtractedLine`` has no way to represent Line 18
beyond an ordinary ``int`` value — the *parser allow-set* ``{3,4,5-17,19}``, not
the type, is what excludes 18 (Req 4.5, 8.4). No money is parsed in these
models; ``amount`` is already a two-decimal money string by the time it reaches
them.
"""

from __future__ import annotations

import dataclasses
import typing

from logstead.models.schedule_e_extraction import (
    CompleteOutcome,
    ExtractedColumn,
    ExtractedLine,
    ExtractionJobView,
    JobStatus,
    ReviewDraft,
    StartExtractionOutcome,
)


def test_job_status_literal_members() -> None:
    assert set(typing.get_args(JobStatus)) == {
        "pending",
        "processing",
        "complete",
        "failed",
    }


def test_complete_outcome_literal_members() -> None:
    assert set(typing.get_args(CompleteOutcome)) == {"draft", "no_schedule_e_found"}


def test_start_extraction_outcome_shape() -> None:
    outcome = StartExtractionOutcome(job_id="7b1f", upload_url="https://s3/signed-put")
    assert outcome.job_id == "7b1f"
    assert outcome.upload_url == "https://s3/signed-put"
    # Both fields are required (no defaults).
    fields = {f.name: f for f in dataclasses.fields(StartExtractionOutcome)}
    assert fields["job_id"].default is dataclasses.MISSING
    assert fields["upload_url"].default is dataclasses.MISSING


def test_extracted_line_fields_and_confidence_defaults_none() -> None:
    line = ExtractedLine(schedule_e_line=3, amount="24000.00", needs_verification=False)
    assert line.schedule_e_line == 3
    assert line.amount == "24000.00"
    assert line.needs_verification is False
    assert line.confidence is None

    with_conf = ExtractedLine(
        schedule_e_line=14, amount="1875.50", needs_verification=True, confidence=42.0
    )
    assert with_conf.confidence == 42.0


def test_extracted_line_amount_is_a_string_wire_shape() -> None:
    # amount is a two-decimal money string already normalized by the service;
    # the model does no parsing. Unreadable → "0.00" + needs_verification.
    unreadable = ExtractedLine(schedule_e_line=5, amount="0.00", needs_verification=True)
    assert unreadable.amount == "0.00"
    assert unreadable.needs_verification is True


def test_extracted_line_has_no_line_18_field() -> None:
    # The dataclass exposes exactly one line-number field: a plain int. There is
    # no separate depreciation / Line-18 field, so the type carries no way to
    # represent "Line 18" beyond the int value itself. The parser allow-set
    # {3,4,5-17,19}, not the type, is what excludes 18 (Req 4.5, 8.4).
    field_names = {f.name for f in dataclasses.fields(ExtractedLine)}
    assert field_names == {"schedule_e_line", "amount", "needs_verification", "confidence"}
    assert "line_18" not in field_names
    assert "depreciation" not in field_names

    schedule_e_line_field = next(
        f for f in dataclasses.fields(ExtractedLine) if f.name == "schedule_e_line"
    )
    assert schedule_e_line_field.type in ("int", int)

    # The type does NOT enforce the allow-set — 18 is a representable int value.
    # This documents that exclusion of 18 is the parser's responsibility, not
    # the model's: constructing one here is possible, which is exactly why the
    # pure parser must never produce it.
    representable = ExtractedLine(schedule_e_line=18, amount="0.00", needs_verification=True)
    assert representable.schedule_e_line == 18


def test_extracted_column_fields_and_lines_default_empty() -> None:
    column = ExtractedColumn(
        address_text=None,
        address_confidence=None,
        suggested_property_id=None,
        suggested_property_name=None,
        mapping_confidence=None,
    )
    assert column.address_text is None
    assert column.address_confidence is None
    assert column.suggested_property_id is None
    assert column.suggested_property_name is None
    assert column.mapping_confidence is None
    assert column.lines == []


def test_extracted_column_lines_default_is_not_shared() -> None:
    a = ExtractedColumn(
        address_text=None,
        address_confidence=None,
        suggested_property_id=None,
        suggested_property_name=None,
        mapping_confidence=None,
    )
    b = ExtractedColumn(
        address_text=None,
        address_confidence=None,
        suggested_property_id=None,
        suggested_property_name=None,
        mapping_confidence=None,
    )
    a.lines.append(ExtractedLine(schedule_e_line=3, amount="1.00", needs_verification=False))
    assert b.lines == []


def test_extracted_column_carries_suggestion() -> None:
    column = ExtractedColumn(
        address_text="12 Maple St",
        address_confidence=97.1,
        suggested_property_id="1111",
        suggested_property_name="Maple Duplex",
        mapping_confidence=0.86,
        lines=[ExtractedLine(schedule_e_line=3, amount="24000.00", needs_verification=False)],
    )
    assert column.address_text == "12 Maple St"
    assert column.suggested_property_id == "1111"
    assert column.suggested_property_name == "Maple Duplex"
    assert column.mapping_confidence == 0.86
    assert len(column.lines) == 1


def test_review_draft_fields_and_columns_default_empty() -> None:
    draft = ReviewDraft(tax_year=None, tax_year_needs_verification=True)
    assert draft.tax_year is None
    assert draft.tax_year_needs_verification is True
    assert draft.columns == []

    with_year = ReviewDraft(tax_year=2023, tax_year_needs_verification=False)
    assert with_year.tax_year == 2023
    assert with_year.tax_year_needs_verification is False


def test_review_draft_columns_default_is_not_shared() -> None:
    a = ReviewDraft(tax_year=None, tax_year_needs_verification=True)
    b = ReviewDraft(tax_year=None, tax_year_needs_verification=True)
    a.columns.append(
        ExtractedColumn(
            address_text=None,
            address_confidence=None,
            suggested_property_id=None,
            suggested_property_name=None,
            mapping_confidence=None,
        )
    )
    assert b.columns == []


def test_review_draft_has_no_line_18_anywhere() -> None:
    # No ExtractedLine in a draft should ever carry Line 18; the model allows it
    # but a well-formed draft (as the parser produces) does not.
    draft = ReviewDraft(
        tax_year=2023,
        tax_year_needs_verification=False,
        columns=[
            ExtractedColumn(
                address_text="12 Maple St",
                address_confidence=97.1,
                suggested_property_id=None,
                suggested_property_name=None,
                mapping_confidence=None,
                lines=[
                    ExtractedLine(schedule_e_line=3, amount="24000.00", needs_verification=False),
                    ExtractedLine(schedule_e_line=19, amount="100.00", needs_verification=False),
                ],
            )
        ],
    )
    all_lines = [ln.schedule_e_line for col in draft.columns for ln in col.lines]
    assert 18 not in all_lines


def test_extraction_job_view_defaults_hold() -> None:
    view = ExtractionJobView(job_id="7b1f", status="processing")
    assert view.job_id == "7b1f"
    assert view.status == "processing"
    assert view.outcome is None
    assert view.message is None
    assert view.review_draft is None


def test_extraction_job_view_complete_with_draft() -> None:
    draft = ReviewDraft(tax_year=2023, tax_year_needs_verification=False)
    view = ExtractionJobView(
        job_id="7b1f", status="complete", outcome="draft", review_draft=draft
    )
    assert view.status == "complete"
    assert view.outcome == "draft"
    assert view.review_draft is draft
    assert view.message is None


def test_extraction_job_view_failed_carries_message() -> None:
    view = ExtractionJobView(
        job_id="7b1f",
        status="failed",
        message="The document could not be read; a valid PDF is required.",
    )
    assert view.status == "failed"
    assert view.message is not None
    assert view.outcome is None
    assert view.review_draft is None
