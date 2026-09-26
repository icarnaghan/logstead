"""Property-based test: asset validation rejects invalid basis and missing fields.

Design Property 16 (Requirements 8.2, 8.3): *for any* depreciable-asset
submission, creation is rejected when the cost basis is less than or equal to
zero, or when any of property, description, cost basis, placed-in-service date,
or recovery period is missing, and the message identifies a failing field; an
otherwise-valid submission with cost basis greater than zero is accepted.

``DepreciationService.create_asset`` (``services/depreciation.py``) validates
its input in a fixed order, each surfacing a field-identifying ``validation``
failure (see :meth:`DepreciationService._validate`):

1. ``property_id`` present, 2. ``description`` present,
3. ``placed_in_service_date`` present, then 4. ``cost_basis`` required and
``> 0`` (field ``cost_basis``), then 5. ``recovery_period_years`` — which is
**optional** and defaults to ``27.5`` when absent, but when provided must be
``> 0`` (field ``recovery_period_years``).

This test drives that invariant universally. The recovery period is genuinely
optional (Requirement 8.4), so it is never "missing" in the rejection sense:
when unspecified the asset is created with the ``27.5`` default; when specified
here it is always a valid positive value, so it never confounds the
required-field / cost-basis>0 concern.

Each required field (property, description, placed-in-service date, cost basis)
is independently either present or missing. ``cost_basis`` is drawn across
{positive two-decimal Decimal, zero, negative}. The expected outcome:

* creation succeeds *iff* every required field is present **and** cost basis > 0
  (recovery optional);
* on success, the recovery period defaults to ``Decimal("27.5")`` when it was
  absent, and equals the provided value otherwise;
* otherwise it fails with kind ``"validation"`` and ``error.field`` naming an
  offending field, matching the service's first-failing-field check order.

Each Hypothesis example provisions its own moto-backed single-table DynamoDB.
The base table is all ``create_asset`` needs for the put and schedule
materialization, but the materialized schedule rows carry GSI2 keys, so the
GSI2 tax-year index is included to mirror the fixture pattern in
``test_depreciation_schedule.py`` and stay safe. Per-example provisioning is
not instantaneous, so the deadline is disabled; the example count is held
at >= 100.
"""

from __future__ import annotations

import contextlib
from decimal import Decimal

import boto3
from hypothesis import given, settings
from hypothesis import strategies as st
from moto import mock_aws

from logstead.models.depreciation import DEFAULT_RECOVERY_PERIOD_YEARS, AssetInput
from logstead.repository.dynamo_repo import DynamoRepository
from logstead.services.depreciation import DepreciationService

TABLE_NAME = "Logstead"
REGION = "us-east-1"
PROPERTY_ID = "prop-1"
# A valid description and ISO placed-in-service date used whenever those fields
# are present, so they never confound the required-field / cost-basis concern.
VALID_DESCRIPTION = "Roof"
VALID_DATE = "2024-03-15"


@contextlib.contextmanager
def _moto_service():
    """Provision an isolated moto DynamoDB (base + GSI2).

    Yields a :class:`DepreciationService` bound to a freshly created table so
    each Hypothesis example runs against a clean store. ``create_asset`` only
    needs the base table for the asset put and its schedule materialization, but
    the schedule rows carry GSI2 keys, so GSI2 is included to be safe (mirroring
    ``test_depreciation_schedule.py``).
    """
    with mock_aws():
        ddb = boto3.client("dynamodb", region_name=REGION)
        ddb.create_table(
            TableName=TABLE_NAME,
            AttributeDefinitions=[
                {"AttributeName": "PK", "AttributeType": "S"},
                {"AttributeName": "SK", "AttributeType": "S"},
                {"AttributeName": "GSI2PK", "AttributeType": "S"},
                {"AttributeName": "GSI2SK", "AttributeType": "S"},
            ],
            KeySchema=[
                {"AttributeName": "PK", "KeyType": "HASH"},
                {"AttributeName": "SK", "KeyType": "RANGE"},
            ],
            GlobalSecondaryIndexes=[
                {
                    "IndexName": "GSI2",
                    "KeySchema": [
                        {"AttributeName": "GSI2PK", "KeyType": "HASH"},
                        {"AttributeName": "GSI2SK", "KeyType": "RANGE"},
                    ],
                    "Projection": {"ProjectionType": "ALL"},
                },
            ],
            BillingMode="PAY_PER_REQUEST",
        )
        yield DepreciationService(DynamoRepository(ddb, TABLE_NAME))


# --- Cost-basis strategy: positive / zero / negative -------------------------
#
# Positive amounts are two-decimal Decimals strictly greater than zero; zero and
# negatives are the invalid side of the cost-basis>0 rule.
_positive_basis = st.decimals(
    min_value=Decimal("0.01"),
    max_value=Decimal("10000000.00"),
    places=2,
    allow_nan=False,
    allow_infinity=False,
)
_negative_basis = st.decimals(
    min_value=Decimal("-10000000.00"),
    max_value=Decimal("-0.01"),
    places=2,
    allow_nan=False,
    allow_infinity=False,
)
_cost_bases = st.one_of(
    _positive_basis, st.just(Decimal("0.00")), _negative_basis
)

# When a recovery period is provided it is always a valid positive value, so it
# never confounds the required-field / cost-basis concern. Includes the 27.5
# residential-rental default among the positives.
_recovery_periods = st.one_of(
    st.just(Decimal("27.5")),
    st.just(Decimal("5")),
    st.just(Decimal("39")),
    st.decimals(
        min_value=Decimal("0.5"),
        max_value=Decimal("50"),
        places=1,
        allow_nan=False,
        allow_infinity=False,
    ),
)


# The required fields the service checks for presence, in its check order. Each
# is independently present (True) or missing (False). Recovery period is NOT in
# this list — it is optional and defaults to 27.5.
_REQUIRED_FIELDS = (
    "property_id",
    "description",
    "placed_in_service_date",
    "cost_basis",
)


# Feature: logstead, Property 16: Asset validation rejects invalid basis and missing fields
@settings(deadline=None, max_examples=200)
@given(
    cost_basis=_cost_bases,
    recovery=_recovery_periods,
    property_present=st.booleans(),
    description_present=st.booleans(),
    date_present=st.booleans(),
    cost_present=st.booleans(),
    recovery_present=st.booleans(),
)
def test_asset_validation_rejects_invalid_basis_and_missing_fields(
    cost_basis: Decimal,
    recovery: Decimal,
    property_present: bool,
    description_present: bool,
    date_present: bool,
    cost_present: bool,
    recovery_present: bool,
) -> None:
    """Create succeeds iff required fields present and cost basis > 0; else fails.

    On success the recovery period defaults to 27.5 when absent and equals the
    provided value otherwise.

    Validates: Requirements 8.2, 8.3
    """
    presence = {
        "property_id": property_present,
        "description": description_present,
        "placed_in_service_date": date_present,
        "cost_basis": cost_present,
    }

    data = AssetInput(
        property_id=PROPERTY_ID if property_present else None,
        description=VALID_DESCRIPTION if description_present else None,
        cost_basis=cost_basis if cost_present else None,
        placed_in_service_date=VALID_DATE if date_present else None,
        recovery_period_years=recovery if recovery_present else None,
    )

    all_present = all(presence.values())
    # cost_basis>0 only matters when the cost basis is actually supplied; when
    # it is absent the required-field check fires first.
    cost_positive = cost_present and cost_basis > Decimal("0.00")

    with _moto_service() as service:
        result = service.create_asset(data)

        if all_present and cost_positive:
            # Every required field present and a positive cost basis (with an
            # optional, always-valid recovery period) -> creation is accepted.
            assert result.is_ok, (
                f"expected success for cost_basis={cost_basis} "
                f"recovery_present={recovery_present} presence={presence}"
            )
            asset = result.value
            assert asset.id
            assert asset.property_id == PROPERTY_ID
            assert asset.description == VALID_DESCRIPTION
            assert asset.cost_basis == cost_basis
            assert asset.placed_in_service_date == VALID_DATE

            # Recovery period defaults to 27.5 when it was absent, else equals
            # the provided value (Requirement 8.4).
            if recovery_present:
                assert asset.recovery_period_years == recovery
            else:
                assert asset.recovery_period_years == DEFAULT_RECOVERY_PERIOD_YEARS
                assert asset.recovery_period_years == Decimal("27.5")

            # Persisted and retrievable.
            listed = service.list_assets(PROPERTY_ID)
            assert [a.id for a in listed] == [asset.id]
        else:
            # Something is invalid: a missing required field or cost basis <= 0.
            # Creation must be rejected with a validation error naming an
            # offending field, and nothing is persisted.
            assert not result.is_ok, (
                f"expected failure for cost_basis={cost_basis} "
                f"cost_present={cost_present} presence={presence}"
            )
            assert result.error.kind == "validation"
            assert result.error.message  # a human-readable message is present

            # The service reports the FIRST offending field in its check order:
            # property_id, description, placed_in_service_date, then cost_basis
            # (presence, then > 0). A present-but-non-positive cost basis fails
            # on the cost_basis field.
            first_missing = next(
                (f for f in _REQUIRED_FIELDS if not presence[f]), None
            )
            expected_field = (
                first_missing if first_missing is not None else "cost_basis"
            )
            assert result.error.field == expected_field, (
                f"expected field {expected_field!r}, got {result.error.field!r} "
                f"for cost_basis={cost_basis} presence={presence}"
            )

            # No asset was persisted on the rejected path.
            assert service.list_assets(PROPERTY_ID) == []
