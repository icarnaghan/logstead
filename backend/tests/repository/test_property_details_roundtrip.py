"""Property-based test for PropertyDetails sparse round-trip (Task 3.2).

# Feature: logstead, Property 4: Property_Details round-trip preserves present fields

Validates: Requirements 2.9, 3.3, 3.8, 12.1, 12.2, 12.3

For any ``PropertyDetails`` value with an arbitrary subset of its fields present
(and the rest absent), persisting it through :class:`DynamoRepository` and reading
it back returns every present field unchanged and reports every absent field as
unset, without error. Absent attributes are never written (verified against the
raw DynamoDB item), and the sparse nested ``features`` map round-trips the same
way. Exercised against DynamoDB via moto so the DynamoDB representation itself is
covered, not just the in-memory mapping.
"""

from __future__ import annotations

from dataclasses import fields
from decimal import Decimal

import boto3
from hypothesis import given, settings
from hypothesis import strategies as st
from moto import mock_aws

from logstead.models.property import PropertyDetails, PropertyFeatures
from logstead.repository import keys
from logstead.repository.dynamo_repo import DynamoRepository
from logstead.repository.mappers import (
    FEATURES_ATTR,
    item_to_property_details,
    property_details_to_item,
)

TABLE_NAME = "Logstead"


def _create_table(ddb):
    ddb.create_table(
        TableName=TABLE_NAME,
        AttributeDefinitions=[
            {"AttributeName": "PK", "AttributeType": "S"},
            {"AttributeName": "SK", "AttributeType": "S"},
        ],
        KeySchema=[
            {"AttributeName": "PK", "KeyType": "HASH"},
            {"AttributeName": "SK", "KeyType": "RANGE"},
        ],
        BillingMode="PAY_PER_REQUEST",
    )


# --- Strategies --------------------------------------------------------------
#
# Each optional field draws either its own value or ``None`` (absent), so
# Hypothesis explores arbitrary subsets of present fields, including the
# all-absent and all-present extremes.

_text = st.text(min_size=1, max_size=40)


def _opt(strategy):
    """Optional field: present value or ``None`` (absent)."""
    return st.one_of(st.none(), strategy)


# Decimal fields use bounded, exact two-decimal-ish values that survive the
# DynamoDB Number round-trip without drift.
_decimal = st.decimals(
    min_value=Decimal("0"),
    max_value=Decimal("100000"),
    allow_nan=False,
    allow_infinity=False,
    places=4,
)


_count = st.integers(min_value=0, max_value=20)

_features = st.builds(
    PropertyFeatures,
    architecture_type=_opt(_text),
    exterior_type=_opt(_text),
    foundation_type=_opt(_text),
    roof_type=_opt(_text),
    view_type=_opt(_text),
    heating=_opt(st.booleans()),
    heating_type=_opt(_text),
    cooling=_opt(st.booleans()),
    cooling_type=_opt(_text),
    garage=_opt(st.booleans()),
    garage_spaces=_opt(_count),
    garage_type=_opt(_text),
    pool=_opt(st.booleans()),
    pool_type=_opt(_text),
    fireplace=_opt(st.booleans()),
    fireplace_type=_opt(_text),
    floor_count=_opt(_count),
    room_count=_opt(_count),
    unit_count=_opt(_count),
)


property_details = st.builds(
    PropertyDetails,
    formatted_address=_opt(_text),
    address_line1=_opt(_text),
    address_line2=_opt(_text),
    city=_opt(_text),
    state=_opt(_text),
    zip_code=_opt(_text),
    county=_opt(_text),
    latitude=_opt(_decimal),
    longitude=_opt(_decimal),
    property_type=_opt(_text),
    bedrooms=_opt(st.integers(min_value=0, max_value=50)),
    bathrooms=_opt(_decimal),
    living_area_sqft=_opt(st.integers(min_value=0, max_value=1_000_000)),
    lot_size=_opt(_decimal),
    year_built=_opt(st.integers(min_value=1800, max_value=2100)),
    features=_features,
)


_SCALAR_FIELDS = [f.name for f in fields(PropertyDetails) if f.name != FEATURES_ATTR]
_FEATURE_FIELDS = [f.name for f in fields(PropertyFeatures)]


# Deadline disabled: each example provisions a fresh moto table, whose setup
# time varies run-to-run and is unrelated to the property under test.
@settings(deadline=None)
@given(details=property_details)
def test_property_details_sparse_round_trip(details: PropertyDetails):
    # Fresh moto table per example keeps examples independent.
    with mock_aws():
        ddb = boto3.client("dynamodb", region_name="us-east-1")
        _create_table(ddb)
        repo = DynamoRepository(ddb, TABLE_NAME)

        property_id = "prop-1"
        pk = keys.property_scoped_pk(property_id)
        sk = keys.property_details_sk()

        item = {"PK": pk, "SK": sk, **property_details_to_item(details)}
        repo.put_item(item)

        raw = ddb.get_item(
            TableName=TABLE_NAME, Key={"PK": {"S": pk}, "SK": {"S": sk}}
        )["Item"]

        # Absent scalar fields are never written (sparse item; 12.2).
        for name in _SCALAR_FIELDS:
            if getattr(details, name) is None:
                assert name not in raw, f"absent field {name!r} should not be stored"

        # Absent feature sub-fields are never written; an all-absent features map
        # is omitted entirely.
        any_feature = any(
            getattr(details.features, name) is not None for name in _FEATURE_FIELDS
        )
        if not any_feature:
            assert FEATURES_ATTR not in raw
        else:
            stored_features = raw[FEATURES_ATTR]["M"]
            for name in _FEATURE_FIELDS:
                if getattr(details.features, name) is None:
                    assert name not in stored_features

        # Read back through the repository and rebuild the dataclass.
        got_item = repo.get_item(pk, sk)
        rebuilt = item_to_property_details(got_item)

        # Present scalar fields are returned unchanged; absent stay unset (None).
        for name in _SCALAR_FIELDS:
            assert getattr(rebuilt, name) == getattr(details, name)

        # Present feature sub-fields unchanged; absent stay unset.
        for name in _FEATURE_FIELDS:
            assert getattr(rebuilt.features, name) == getattr(details.features, name)

        # The full dataclass round-trips exactly.
        assert rebuilt == details
