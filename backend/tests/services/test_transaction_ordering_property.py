"""Property-based test: transaction listing is ordered by date descending.

Design Property 8 (Requirements 5.4): *for any* set of transactions for a
property, the listing is a permutation of that set ordered by date descending.

``TransactionService.list_for_property`` (``services/transaction.py``) returns
transactions newest-first. It achieves this by encoding an inverted date into
the DynamoDB sort key (``TXN#<invDate>#<id>`` where
``invDate = 99999999 - YYYYMMDD``) so a natural ascending sort-key ``query``
yields date-descending results regardless of the order in which transactions
were created.

This test drives that invariant universally. It generates a set of
transactions with varied dates -- freely including ties (several transactions
sharing the same date) -- and creates them in a Hypothesis-controlled
(effectively random) order. It then asserts:

* the returned dates are non-increasing (``>=``) -- i.e. sorted newest-first,
  with ties permitted; and
* the listing is a permutation of exactly the transactions created (no rows
  dropped, none duplicated, no extras).

To keep the focus squarely on the ordering concern, every generated
transaction uses a valid, known, non-Other income category
(``rents-received``, Line 3) and a positive amount, so the validation and
description rules never confound this property.

Each Hypothesis example provisions its own moto-backed single-table DynamoDB
(with the GSI2 tax-year index the service relies on) plus an S3 bucket needed to
construct the ``S3FileAdapter``, mirroring the fixture pattern in
``test_transaction.py``. Per-example provisioning is not instantaneous, so the
deadline is disabled; the example count is held at >= 100.
"""

from __future__ import annotations

import contextlib
import datetime as dt
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
# A valid, known, non-Other income category (Line 3, Rents received) so the
# validation / description rules never confound the ordering concern.
CATEGORY_ID = "rents-received"


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


# --- Strategies --------------------------------------------------------------
#
# Dates span a wide range (across years, months, days) as ISO strings. Drawing
# from a list of dates *with* ``unique=False`` lets several transactions share
# the same date, exercising the tie case explicitly.
_dates = st.dates(
    min_value=dt.date(2000, 1, 1), max_value=dt.date(2035, 12, 31)
).map(lambda d: d.isoformat())

# Positive two-decimal amounts, so the amount>0 rule always holds.
_amounts = st.decimals(
    min_value=Decimal("0.01"),
    max_value=Decimal("1000000.00"),
    places=2,
    allow_nan=False,
    allow_infinity=False,
)


# A non-empty set of (date, amount) pairs, dates deliberately NOT unique so
# ties occur. Hypothesis shuffles/permutes the list across examples, giving the
# "random insertion order" the property calls for.
_transaction_specs = st.lists(
    st.tuples(_dates, _amounts),
    min_size=1,
    max_size=12,
)


# Feature: logstead, Property 8: Transaction listing is ordered by date descending
@settings(deadline=None, max_examples=150)
@given(specs=_transaction_specs)
def test_transaction_listing_is_ordered_by_date_descending(
    specs: list[tuple[str, Decimal]],
) -> None:
    """Listing is a date-descending permutation of the created transactions.

    Validates: Requirements 5.4
    """
    with _moto_service() as service:
        created_ids: list[str] = []
        created_dates: list[str] = []
        for date_str, amount in specs:
            result = service.create(
                TransactionInput(
                    property_id=PROPERTY_ID,
                    date=date_str,
                    amount=amount,
                    type="income",
                    category_id=CATEGORY_ID,
                    description=None,
                )
            )
            assert result.is_ok, f"create failed for {date_str} {amount}"
            created_ids.append(result.value.id)
            created_dates.append(date_str)

        listed = service.list_for_property(PROPERTY_ID)
        assert listed.is_ok
        txns = listed.value

        # 1) The listing is a permutation of exactly what was created: same
        #    count, same set of ids (nothing dropped, duplicated, or added).
        assert len(txns) == len(created_ids)
        assert sorted(t.id for t in txns) == sorted(created_ids)

        # 2) Dates are non-increasing (newest-first), ties permitted (>=).
        listed_dates = [t.date for t in txns]
        for earlier, later in zip(listed_dates, listed_dates[1:]):
            assert earlier >= later, (
                f"ordering violated: {earlier!r} precedes {later!r} in "
                f"{listed_dates}"
            )

        # 3) The listing's date multiset equals the created date multiset:
        #    the listing is precisely the sorted (desc) permutation.
        assert listed_dates == sorted(created_dates, reverse=True)
