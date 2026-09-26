"""Unit tests for ``validate_document`` (Requirements 3, 4, 5, 13).

One focused test per validation rule, following the design's "Validation model"
order. Each asserts the ``Result`` outcome, and — for failures — that the error
``kind`` is ``"validation"``, the ``field`` names the offending field, and the
message identifies the offending entity/value/version. A happy-path document
asserts ``Result.success`` with money parsed to exact two-decimal ``Decimal``.

``validate_document`` is pure (no store), so these tests need no AWS fixtures.
"""

from __future__ import annotations

import copy
from decimal import Decimal

from logstead.models.backup import SCHEMA_VERSION, BackupDocument
from logstead.services.backup import validate_document


def _valid_document() -> dict:
    """A minimal but complete valid backup document with two properties."""
    return {
        "schema_version": SCHEMA_VERSION,
        "exported_at": "2025-02-14T10:30:00+00:00",
        "properties": [
            {
                "id": "prop-1",
                "name": "Maple Street Duplex",
                "address_text": "123 Maple St, Springfield, IL 62704",
                "property_type": "single_family",
                "created_at": "2023-01-05T12:00:00+00:00",
                "updated_at": "2024-11-02T09:15:00+00:00",
                "details": {
                    "formatted_address": "123 Maple St",
                    "latitude": "39.781721",
                    "longitude": "-89.650148",
                    "last_sale_price": "245000.00",
                    "tax_assessments": [{"year": 2023, "value": "230000.00"}],
                },
                "note": "Tenant lease renews each August.",
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
                        "description": None,
                        "created_at": "2024-03-01T08:00:00+00:00",
                        "updated_at": "2024-03-01T08:00:00+00:00",
                    }
                ],
                "assets": [
                    {
                        "id": "asset-1",
                        "property_id": "prop-1",
                        "description": "HVAC system",
                        "cost_basis": "8000.00",
                        "placed_in_service_date": "2023-06-15",
                        "recovery_period_years": "27.5",
                        "created_at": "2023-06-15T10:00:00+00:00",
                        "updated_at": "2023-06-15T10:00:00+00:00",
                    }
                ],
            },
            {
                "id": "prop-2",
                "name": "Oak Avenue Condo",
                "address_text": "500 Oak Ave, Springfield, IL 62704",
                "transactions": [],
                "assets": [],
                "usage": [],
            },
        ],
    }


# --- Happy path --------------------------------------------------------------


def test_valid_document_parses_to_typed_backup_document():
    """A valid document returns success with money parsed to exact Decimal."""
    result = validate_document(_valid_document())

    assert result.is_ok
    doc = result.value
    assert isinstance(doc, BackupDocument)
    assert doc.schema_version == SCHEMA_VERSION
    assert len(doc.properties) == 2

    prop = doc.properties[0]
    txn = prop.transactions[0]
    assert isinstance(txn.amount, Decimal)
    assert txn.amount == Decimal("1850.00")

    asset = prop.assets[0]
    assert isinstance(asset.cost_basis, Decimal)
    assert asset.cost_basis == Decimal("8000.00")
    assert asset.recovery_period_years == Decimal("27.5")

    # Details money/coordinates parsed to Decimal, full precision on coords.
    assert prop.details is not None
    assert prop.details.last_sale_price == Decimal("245000.00")
    assert prop.details.latitude == Decimal("39.781721")
    assert prop.details.tax_assessments[0].value == Decimal("230000.00")


# --- 1. JSON object shape (Requirement 3.1) ----------------------------------


def test_non_object_body_is_rejected():
    result = validate_document([1, 2, 3])
    assert not result.is_ok
    assert result.error.kind == "validation"
    assert "properties array" in result.error.message


def test_missing_properties_array_is_rejected():
    result = validate_document({"schema_version": SCHEMA_VERSION})
    assert not result.is_ok
    assert result.error.kind == "validation"
    assert "properties array" in result.error.message


# --- 2. Schema version (Requirements 5.1, 5.2) -------------------------------


def test_missing_schema_version_is_rejected():
    doc = _valid_document()
    del doc["schema_version"]
    result = validate_document(doc)
    assert not result.is_ok
    assert result.error.kind == "validation"
    assert result.error.field == "schema_version"


def test_unsupported_schema_version_names_the_version():
    doc = _valid_document()
    doc["schema_version"] = "99"
    result = validate_document(doc)
    assert not result.is_ok
    assert result.error.kind == "validation"
    assert result.error.field == "schema_version"
    assert "99" in result.error.message


# --- 3. Per-entity required fields (Requirement 3.2) -------------------------

# Property: id / name / address_text.


def test_property_missing_id_identifies_entity_and_field():
    doc = _valid_document()
    del doc["properties"][0]["id"]
    result = validate_document(doc)
    assert not result.is_ok
    assert result.error.field == "id"
    # With no id, the entity label falls back to the bare "property" type.
    assert "property" in result.error.message


def test_property_missing_name_identifies_entity_and_field():
    doc = _valid_document()
    del doc["properties"][0]["name"]
    result = validate_document(doc)
    assert not result.is_ok
    assert result.error.field == "name"
    assert "property" in result.error.message
    assert "prop-1" in result.error.message


def test_property_missing_address_text_is_rejected():
    doc = _valid_document()
    del doc["properties"][0]["address_text"]
    result = validate_document(doc)
    assert not result.is_ok
    assert result.error.field == "address_text"
    assert "property" in result.error.message
    assert "prop-1" in result.error.message


# Transaction: id / property_id / date / amount / type / category_id.


def test_transaction_missing_id_identifies_entity_and_field():
    doc = _valid_document()
    del doc["properties"][0]["transactions"][0]["id"]
    result = validate_document(doc)
    assert not result.is_ok
    assert result.error.field == "id"
    assert "transaction" in result.error.message


def test_transaction_missing_property_id_identifies_entity_and_field():
    doc = _valid_document()
    del doc["properties"][0]["transactions"][0]["property_id"]
    result = validate_document(doc)
    assert not result.is_ok
    assert result.error.field == "property_id"
    assert "transaction" in result.error.message
    assert "txn-1" in result.error.message


def test_transaction_missing_date_identifies_entity_and_field():
    doc = _valid_document()
    del doc["properties"][0]["transactions"][0]["date"]
    result = validate_document(doc)
    assert not result.is_ok
    assert result.error.field == "date"
    assert "transaction" in result.error.message
    assert "txn-1" in result.error.message


def test_transaction_missing_amount_identifies_entity_and_field():
    doc = _valid_document()
    del doc["properties"][0]["transactions"][0]["amount"]
    result = validate_document(doc)
    assert not result.is_ok
    assert result.error.field == "amount"
    assert "transaction" in result.error.message
    assert "txn-1" in result.error.message


def test_transaction_missing_type_identifies_entity_and_field():
    doc = _valid_document()
    del doc["properties"][0]["transactions"][0]["type"]
    result = validate_document(doc)
    assert not result.is_ok
    assert result.error.field == "type"
    assert "transaction" in result.error.message
    assert "txn-1" in result.error.message


# Asset: id / property_id / description / cost_basis / placed_in_service_date.


def test_asset_missing_id_identifies_entity_and_field():
    doc = _valid_document()
    del doc["properties"][0]["assets"][0]["id"]
    result = validate_document(doc)
    assert not result.is_ok
    assert result.error.field == "id"
    assert "asset" in result.error.message


def test_asset_missing_property_id_identifies_entity_and_field():
    doc = _valid_document()
    del doc["properties"][0]["assets"][0]["property_id"]
    result = validate_document(doc)
    assert not result.is_ok
    assert result.error.field == "property_id"
    assert "asset" in result.error.message
    assert "asset-1" in result.error.message


def test_asset_missing_description_identifies_entity_and_field():
    doc = _valid_document()
    del doc["properties"][0]["assets"][0]["description"]
    result = validate_document(doc)
    assert not result.is_ok
    assert result.error.field == "description"
    assert "asset" in result.error.message
    assert "asset-1" in result.error.message


def test_asset_missing_cost_basis_identifies_entity_and_field():
    doc = _valid_document()
    del doc["properties"][0]["assets"][0]["cost_basis"]
    result = validate_document(doc)
    assert not result.is_ok
    assert result.error.field == "cost_basis"
    assert "asset" in result.error.message
    assert "asset-1" in result.error.message


def test_asset_missing_placed_in_service_date_identifies_entity_and_field():
    doc = _valid_document()
    del doc["properties"][0]["assets"][0]["placed_in_service_date"]
    result = validate_document(doc)
    assert not result.is_ok
    assert result.error.field == "placed_in_service_date"
    assert "asset" in result.error.message
    assert "asset-1" in result.error.message


# --- 4. Money / coordinate format (Requirements 3.4, 13.2) -------------------


def test_bad_transaction_amount_string_is_rejected():
    doc = _valid_document()
    doc["properties"][0]["transactions"][0]["amount"] = "not-a-number"
    result = validate_document(doc)
    assert not result.is_ok
    assert result.error.field == "amount"
    assert "not-a-number" in result.error.message


def test_float_money_is_rejected():
    doc = _valid_document()
    doc["properties"][0]["assets"][0]["cost_basis"] = 8000.0
    result = validate_document(doc)
    assert not result.is_ok
    assert result.error.field == "cost_basis"


def test_bad_details_money_field_is_rejected():
    doc = _valid_document()
    doc["properties"][0]["details"]["last_sale_price"] = "lots"
    result = validate_document(doc)
    assert not result.is_ok
    assert result.error.field == "details.last_sale_price"
    assert "lots" in result.error.message


def test_bad_coordinate_string_is_rejected():
    doc = _valid_document()
    doc["properties"][0]["details"]["latitude"] = "north"
    result = validate_document(doc)
    assert not result.is_ok
    assert result.error.field == "details.latitude"
    assert "north" in result.error.message


# --- 5. Category integrity (Requirements 4.1, 4.2) ---------------------------


def test_unknown_category_id_is_rejected_and_named():
    doc = _valid_document()
    doc["properties"][0]["transactions"][0]["category_id"] = "made-up-slug"
    result = validate_document(doc)
    assert not result.is_ok
    assert result.error.field == "category_id"
    assert "made-up-slug" in result.error.message


def test_missing_category_id_identifies_the_transaction():
    doc = _valid_document()
    del doc["properties"][0]["transactions"][0]["category_id"]
    result = validate_document(doc)
    assert not result.is_ok
    assert result.error.field == "category_id"
    assert "transaction" in result.error.message
    assert "txn-1" in result.error.message


# --- 6. Cross-reference sanity -----------------------------------------------


def test_transaction_property_id_mismatch_is_rejected():
    doc = _valid_document()
    doc["properties"][0]["transactions"][0]["property_id"] = "ghost-prop"
    result = validate_document(doc)
    assert not result.is_ok
    assert result.error.field == "property_id"
    assert "ghost-prop" in result.error.message


def test_asset_property_id_mismatch_is_rejected():
    doc = _valid_document()
    doc["properties"][0]["assets"][0]["property_id"] = "ghost-prop"
    result = validate_document(doc)
    assert not result.is_ok
    assert result.error.field == "property_id"
    assert "ghost-prop" in result.error.message


# --- Regression guard: the helper produces a genuinely valid document --------


def test_valid_document_fixture_is_not_accidentally_mutated():
    """The valid fixture stays valid (guards against copy-by-reference bugs)."""
    doc = _valid_document()
    snapshot = copy.deepcopy(doc)
    validate_document(doc)
    assert doc == snapshot
