"""Property-based test: transaction validation rejects invalid amounts and
missing fields.

Design Property 7 (Requirements 5.2, 5.3): *for any* transaction submission,
creation is rejected when the amount is less than or equal to zero, or when any
of property, date, amount, or category is missing, and the message identifies a
failing field; a submission with all required fields present and amount greater
than zero is accepted.

``TransactionService.create`` (``services/transaction.py``) validates the input
in a fixed order, each surfacing a field-identifying ``validation`` failure:

1. ``property_id`` present, 2. ``date`` present, 3. ``amount`` present,
4. ``category_id`` present, then 5. ``date`` parseable, 6. ``amount > 0``.

This test drives that invariant universally. It focuses squarely on the
Property 7 concern -- **amount > 0** and **required-field presence** -- so it
holds the category fixed to a valid, non-Other income category
(``rents-received``, Line 3) and always supplies a valid ISO date when the date
field is present. That keeps the description rule (Property 15, task 10.6) and
the unknown-category / bad-date paths from confounding this property.

Each required field (property, date, amount, category) is independently either
present or missing. ``amount`` is drawn across {positive two-decimal Decimal,
zero, negative}. The expected outcome:

* creation succeeds *iff* every required field is present **and** amount > 0
  (with a valid date and a known category, both guaranteed here);
* otherwise it fails with kind ``"validation"`` and ``error.field`` naming an
  offending field, matching the service's first-failing-field check order.

Each Hypothesis example provisions its own moto-backed single-table DynamoDB
(with the GSI2 tax-year index the service relies on) plus an S3 bucket needed to
construct the ``S3FileAdapter``, mirroring the fixture pattern in
``test_transaction.py``. Per-example provisioning is not instantaneous, so the
deadline is disabled; the example count is held at >= 100.
"""

from __future__ import annotations

import contextlib
from decimal import Decimal

import boto3
from hypothesis import given, settings
from hypothesis import strategies as st
from moto import mock_aws

from logstead.adapters.s3_files import S3FileAdapter
from logstead.models.transaction import TransactionInput
from logstead.repository.dynamo_repo import DynamoRepository
from logstead.services.transaction import TransactionService

TABLE_NAME = "Logstead"
BUCKET = "logstead-files-test"
REGION = "us-east-1"
PROPERTY_ID = "prop-1"
# A valid, known, non-Other category so the description rule and the
# unknown-category path never confound this property (Line 3, Rents received).
CATEGORY_ID = "rents-received"
# A valid ISO date used whenever the date field is present, so the bad-date
# path never confounds the required-field / amount>0 concern.
VALID_DATE = "2024-03-07"


@contextlib.contextmanager
def _moto_service():
    """Provision an isolated moto DynamoDB (base + GSI2) and S3 bucket.

    Yields a :class:`TransactionService` bound to freshly created resources so
    each Hypothesis example runs against a clean store.
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
        s3 = boto3.client("s3", region_name=REGION)
        s3.create_bucket(Bucket=BUCKET)
        yield TransactionService(
            DynamoRepository(ddb, TABLE_NAME), S3FileAdapter(s3, BUCKET)
        )


# --- Amount strategy: positive / zero / negative -----------------------------
#
# Positive amounts are two-decimal Decimals strictly greater than zero; zero and
# negatives are the invalid side of the amount>0 rule.
_positive_amount = st.decimals(
    min_value=Decimal("0.01"),
    max_value=Decimal("1000000.00"),
    places=2,
    allow_nan=False,
    allow_infinity=False,
)
_negative_amount = st.decimals(
    min_value=Decimal("-1000000.00"),
    max_value=Decimal("-0.01"),
    places=2,
    allow_nan=False,
    allow_infinity=False,
)
_amounts = st.one_of(_positive_amount, st.just(Decimal("0.00")), _negative_amount)


# The required fields the service checks for presence, in its check order. Each
# is independently present (True) or missing (False).
_REQUIRED_FIELDS = ("property_id", "date", "amount", "category_id")


# Feature: logstead, Property 7: Transaction validation rejects invalid amounts and missing fields
@settings(deadline=None, max_examples=200)
@given(
    amount=_amounts,
    property_present=st.booleans(),
    date_present=st.booleans(),
    amount_present=st.booleans(),
    category_present=st.booleans(),
)
def test_transaction_validation_rejects_invalid_amounts_and_missing_fields(
    amount: Decimal,
    property_present: bool,
    date_present: bool,
    amount_present: bool,
    category_present: bool,
) -> None:
    """Create succeeds iff all required fields present and amount > 0; else fails.

    Validates: Requirements 5.2, 5.3
    """
    presence = {
        "property_id": property_present,
        "date": date_present,
        "amount": amount_present,
        "category_id": category_present,
    }

    data = TransactionInput(
        property_id=PROPERTY_ID if property_present else None,
        date=VALID_DATE if date_present else None,
        amount=amount if amount_present else None,
        type="income",
        category_id=CATEGORY_ID if category_present else None,
        description=None,
    )

    all_present = all(presence.values())
    amount_positive = amount > Decimal("0.00")

    with _moto_service() as service:
        result = service.create(data)

        if all_present and amount_positive:
            # Every required field present, valid date, known category, and a
            # positive amount -> creation is accepted.
            assert result.is_ok, (
                f"expected success for amount={amount} presence={presence}"
            )
            txn = result.value
            assert txn.id
            assert txn.property_id == PROPERTY_ID
            assert txn.amount == amount
            assert txn.category_id == CATEGORY_ID
            assert txn.schedule_e_line == 3  # Rents received -> Line 3
            # Persisted and retrievable.
            listed = service.list_for_property(PROPERTY_ID)
            assert [t.id for t in listed.value] == [txn.id]
        else:
            # Something is invalid: a missing required field or amount <= 0.
            # Creation must be rejected with a validation error naming an
            # offending field, and nothing is persisted.
            assert not result.is_ok, (
                f"expected failure for amount={amount} presence={presence}"
            )
            assert result.error.kind == "validation"
            assert result.error.message  # a human-readable message is present

            # The service reports the FIRST offending field in its check order:
            # presence of property_id, date, amount, category_id, then amount>0.
            first_missing = next(
                (f for f in _REQUIRED_FIELDS if not presence[f]), None
            )
            expected_field = first_missing if first_missing is not None else "amount"
            assert result.error.field == expected_field, (
                f"expected field {expected_field!r}, got {result.error.field!r} "
                f"for amount={amount} presence={presence}"
            )

            # No transaction was persisted on the rejected path.
            assert service.list_for_property(PROPERTY_ID).value == []
