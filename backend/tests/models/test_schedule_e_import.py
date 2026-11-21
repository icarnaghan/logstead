"""Shape/default tests for the Schedule E Import service-layer models (Task 2.2).

Proves the documented field defaults hold and that the outcome dataclasses
carry the fields the design specifies. No money is parsed in these models;
amounts pass through as strings/``Decimal``/``None`` to the service boundary.
"""

from __future__ import annotations

from decimal import Decimal

from logstead.models.property import PropertyInput
from logstead.models.schedule_e_import import (
    EntryOutcome,
    ImportOutcome,
    ImportSubmission,
    LineAmountInput,
    PropertyEntryInput,
    RemoveOutcome,
)


def test_line_amount_input_description_defaults_none() -> None:
    line = LineAmountInput(schedule_e_line=3, amount="24000.00")
    assert line.schedule_e_line == 3
    assert line.amount == "24000.00"
    assert line.description is None


def test_line_amount_input_accepts_decimal_and_none_amount() -> None:
    # Amounts pass through verbatim; the model does no parsing.
    assert LineAmountInput(schedule_e_line=14, amount=Decimal("1875.50")).amount == Decimal(
        "1875.50"
    )
    assert LineAmountInput(schedule_e_line=5, amount=None).amount is None


def test_property_entry_input_mapping_fields_optional_lines_default_empty() -> None:
    entry = PropertyEntryInput()
    assert entry.property_id is None
    assert entry.new_property is None
    assert entry.lines == []


def test_property_entry_input_lines_default_is_not_shared() -> None:
    a = PropertyEntryInput()
    b = PropertyEntryInput()
    a.lines.append(LineAmountInput(schedule_e_line=3, amount="1.00"))
    assert b.lines == []


def test_property_entry_input_carries_inline_property() -> None:
    new_prop = PropertyInput(name="Maple Duplex B", address_text="12 Maple St")
    entry = PropertyEntryInput(new_property=new_prop)
    assert entry.property_id is None
    assert entry.new_property is new_prop


def test_import_submission_tax_year_optional() -> None:
    submission = ImportSubmission(tax_year=None, entries=[])
    assert submission.tax_year is None
    assert submission.entries == []

    with_year = ImportSubmission(tax_year=2023, entries=[PropertyEntryInput()])
    assert with_year.tax_year == 2023
    assert len(with_year.entries) == 1


def test_entry_outcome_carries_documented_fields() -> None:
    outcome = EntryOutcome(
        property_id="p1",
        created_transaction_ids=["t1", "t2"],
        deleted_prior_count=3,
        created_inline_property=True,
    )
    assert outcome.property_id == "p1"
    assert outcome.created_transaction_ids == ["t1", "t2"]
    assert outcome.deleted_prior_count == 3
    assert outcome.created_inline_property is True


def test_import_outcome_carries_documented_fields() -> None:
    entry = EntryOutcome(
        property_id="p1",
        created_transaction_ids=[],
        deleted_prior_count=0,
        created_inline_property=False,
    )
    outcome = ImportOutcome(tax_year=2023, entries=[entry])
    assert outcome.tax_year == 2023
    assert outcome.entries == [entry]


def test_remove_outcome_carries_documented_fields() -> None:
    outcome = RemoveOutcome(property_id="p1", tax_year=2023, deleted_count=5)
    assert outcome.property_id == "p1"
    assert outcome.tax_year == 2023
    assert outcome.deleted_count == 5
