"""Property-based test for backup document validation (Property 3).

# Feature: backup-restore, Property 3: An invalid document is rejected without mutating the store

Design Property 3 (Requirements 3.1, 3.2, 3.3, 3.4, 4.1, 5.1, 5.2): *for any*
backup document made invalid in exactly one way — a non-object structure, a
dropped required field, a malformed money string, a ``category_id`` outside the
catalog, or a missing/unsupported schema version — ``validate_document`` returns
a ``validation`` failure that identifies the offending location.

This task is validation-only: ``validate_document`` is pure and touches no
store, so the "byte-for-byte unchanged store" half of Property 3 is trivially
satisfied here (there is nothing to mutate) and is exercised end-to-end at the
restore layer in a later task. This test asserts the ``Result`` contract: for a
document invalidated in exactly one generated way, the outcome is a
``validation`` failure with a message (and, where applicable, a ``field``)
naming the fault.

A single valid base document is built, then exactly ONE generated invalidity is
applied per example (the flavor is parameterized by a Hypothesis strategy). The
base document is always confirmed valid first, so any observed failure is
attributable to the injected invalidity alone.
"""

from __future__ import annotations

import copy
from typing import Any

from hypothesis import given, settings
from hypothesis import strategies as st

from logstead.models.backup import SCHEMA_VERSION
from logstead.services.backup import validate_document


def _valid_base() -> dict[str, Any]:
    """A valid backup document used as the starting point for each example."""
    return {
        "schema_version": SCHEMA_VERSION,
        "exported_at": "2025-02-14T10:30:00+00:00",
        "properties": [
            {
                "id": "prop-1",
                "name": "Maple Street Duplex",
                "address_text": "123 Maple St",
                "details": {
                    "formatted_address": "123 Maple St",
                    "latitude": "39.781721",
                    "longitude": "-89.650148",
                },
                "usage": [
                    {
                        "tax_year": 2023,
                        "fair_rental_days": 300,
                        "personal_use_days": 0,
                    }
                ],
                "transactions": [
                    {
                        "id": "txn-1",
                        "property_id": "prop-1",
                        "date": "2024-03-01",
                        "amount": "1850.00",
                        "type": "income",
                        "category_id": "rents-received",
                    }
                ],
                "assets": [
                    {
                        "id": "asset-1",
                        "property_id": "prop-1",
                        "description": "HVAC",
                        "cost_basis": "8000.00",
                        "placed_in_service_date": "2023-06-15",
                    }
                ],
            }
        ],
    }


# The set of ways to invalidate the base document in exactly one place. Each
# mutator returns (doc, expected_field_or_None) where the field is asserted when
# the validator surfaces one for that flavor.
def _drop_property_field(doc: dict[str, Any]) -> tuple[dict[str, Any], str | None]:
    del doc["properties"][0]["address_text"]
    return doc, "address_text"


def _drop_transaction_field(
    doc: dict[str, Any]
) -> tuple[dict[str, Any], str | None]:
    del doc["properties"][0]["transactions"][0]["date"]
    return doc, "date"


def _drop_asset_field(doc: dict[str, Any]) -> tuple[dict[str, Any], str | None]:
    del doc["properties"][0]["assets"][0]["cost_basis"]
    return doc, "cost_basis"


def _malformed_money(doc: dict[str, Any]) -> tuple[dict[str, Any], str | None]:
    doc["properties"][0]["transactions"][0]["amount"] = "twelve dollars"
    return doc, "amount"


def _unknown_category(doc: dict[str, Any]) -> tuple[dict[str, Any], str | None]:
    doc["properties"][0]["transactions"][0]["category_id"] = "no-such-category"
    return doc, "category_id"


def _bad_coordinate(doc: dict[str, Any]) -> tuple[dict[str, Any], str | None]:
    doc["properties"][0]["details"]["latitude"] = "not-a-coordinate"
    return doc, "details.latitude"


def _cross_reference_mismatch(
    doc: dict[str, Any]
) -> tuple[dict[str, Any], str | None]:
    # Point a transaction at a property that is not present in the document.
    doc["properties"][0]["transactions"][0]["property_id"] = "prop-does-not-exist"
    return doc, "property_id"


def _missing_version(doc: dict[str, Any]) -> tuple[dict[str, Any], str | None]:
    del doc["schema_version"]
    return doc, "schema_version"


def _unsupported_version(
    doc: dict[str, Any]
) -> tuple[dict[str, Any], str | None]:
    doc["schema_version"] = "9999"
    return doc, "schema_version"


def _non_object(doc: dict[str, Any]) -> tuple[Any, str | None]:
    # Replace the whole document with a non-object structure.
    return [doc], None


_MUTATORS = (
    _drop_property_field,
    _drop_transaction_field,
    _drop_asset_field,
    _malformed_money,
    _bad_coordinate,
    _unknown_category,
    _cross_reference_mismatch,
    _missing_version,
    _unsupported_version,
    _non_object,
)


# Feature: backup-restore, Property 3: An invalid document is rejected without mutating the store
@settings(max_examples=100, deadline=None)
@given(mutator=st.sampled_from(_MUTATORS))
def test_document_invalid_in_one_way_is_rejected(mutator) -> None:
    """A document broken in exactly one way is rejected, naming the fault.

    Validates: Requirements 3.1, 3.2, 3.3, 3.4, 4.1, 5.1, 5.2
    """
    # The base is valid on its own, so any failure is due to the injected fault.
    base = _valid_base()
    assert validate_document(copy.deepcopy(base)).is_ok

    invalid_doc, expected_field = mutator(copy.deepcopy(base))

    result = validate_document(invalid_doc)

    assert not result.is_ok, "an invalid document must be rejected"
    assert result.error.kind == "validation"
    assert result.error.message, "the failure must carry a human-readable message"
    if expected_field is not None:
        assert result.error.field == expected_field, (
            f"expected field {expected_field!r}, got {result.error.field!r}"
        )
