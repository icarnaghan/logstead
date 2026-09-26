"""Property-based test for guarded property deletion (Task 6.3).

# Feature: logstead, Property 3: Property deletion is guarded by associations

Validates: Requirements 2.6, 2.7

For any property with an arbitrary set of associated transactions and
depreciable assets (possibly empty), deletion succeeds *exactly when* both sets
are empty, and is otherwise rejected with a ``conflict`` result while the
property remains intact.

The property is exercised against DynamoDB via moto (fresh single-table
instance with GSI1 per example, mirroring the smoke test's table). For each
example we create a property, then seed a random number of raw transaction
and/or asset rows directly under its child partition using the key helpers
(as ``test_property_service_smoke`` does), and assert:

* zero associations  -> ``delete`` succeeds and ``get`` is ``not_found``;
* one or more assocs -> ``delete`` fails with kind ``"conflict"`` and the
  property still exists (``get`` is ok).

The transaction/asset counts are drawn independently and include zero, so both
branches of the guard are hit across the run.
"""

from __future__ import annotations

from datetime import date, timedelta
from decimal import Decimal

import boto3
from hypothesis import given, settings
from hypothesis import strategies as st
from moto import mock_aws

from logstead.models.property import PropertyInput
from logstead.models.user import UserContext
from logstead.repository import keys
from logstead.repository.dynamo_repo import DynamoRepository
from logstead.services.property import PropertyService

TABLE_NAME = "Logstead"


def _create_table(ddb) -> None:
    """Provision the single-table Logstead schema (base table + GSI1)."""
    ddb.create_table(
        TableName=TABLE_NAME,
        AttributeDefinitions=[
            {"AttributeName": "PK", "AttributeType": "S"},
            {"AttributeName": "SK", "AttributeType": "S"},
            {"AttributeName": "GSI1PK", "AttributeType": "S"},
            {"AttributeName": "GSI1SK", "AttributeType": "S"},
        ],
        KeySchema=[
            {"AttributeName": "PK", "KeyType": "HASH"},
            {"AttributeName": "SK", "KeyType": "RANGE"},
        ],
        GlobalSecondaryIndexes=[
            {
                "IndexName": "GSI1",
                "KeySchema": [
                    {"AttributeName": "GSI1PK", "KeyType": "HASH"},
                    {"AttributeName": "GSI1SK", "KeyType": "RANGE"},
                ],
                "Projection": {"ProjectionType": "ALL"},
            },
        ],
        BillingMode="PAY_PER_REQUEST",
    )


def _seed_transactions(repo: DynamoRepository, property_id: str, count: int) -> None:
    """Put ``count`` raw transaction rows under the property's child partition."""
    base = date(2024, 1, 1)
    for i in range(count):
        txn_date = base + timedelta(days=i)
        repo.put_item(
            {
                "PK": keys.property_scoped_pk(property_id),
                "SK": keys.transaction_sk(txn_date, f"txn-{i}"),
                "amount": Decimal("100.00"),
            }
        )


def _seed_assets(repo: DynamoRepository, property_id: str, count: int) -> None:
    """Put ``count`` raw asset rows under the property's child partition."""
    for i in range(count):
        repo.put_item(
            {
                "PK": keys.property_scoped_pk(property_id),
                "SK": keys.asset_sk(f"asset-{i}"),
                "costBasis": Decimal("5000.00"),
            }
        )


# Larger counts keep the input space wide enough to run the required minimum of
# 100 examples while still frequently hitting zero (both empty),
# only-transactions, only-assets, and both-present combinations.
_counts = st.integers(min_value=0, max_value=6)

# A varied (non-blank) name per example widens the input space so Hypothesis
# does not exhaust it before the required 100 examples; it does not affect the
# deletion guard, which turns solely on the associated-record counts.
_name = st.text(min_size=1, max_size=30).filter(lambda s: s.strip() != "")


# Deadline disabled: each example provisions a fresh moto table whose setup time
# varies run-to-run and is unrelated to the deletion guard under test.
@settings(deadline=None)
@given(txn_count=_counts, asset_count=_counts, name=_name)
# Feature: logstead, Property 3: Property deletion is guarded by associations
def test_property_deletion_is_guarded_by_associations(
    txn_count: int, asset_count: int, name: str
) -> None:
    with mock_aws():
        ddb = boto3.client("dynamodb", region_name="us-east-1")
        _create_table(ddb)
        repo = DynamoRepository(ddb, TABLE_NAME)
        service = PropertyService(repo, UserContext(user_id="user-1"))

        prop = service.create(
            PropertyInput(name=name, address_text="1 Maple St")
        ).value

        _seed_transactions(repo, prop.id, txn_count)
        _seed_assets(repo, prop.id, asset_count)

        has_associations = txn_count > 0 or asset_count > 0
        result = service.delete(prop.id)

        if has_associations:
            # Guard rejects deletion and leaves the property in place.
            assert not result.is_ok
            assert result.error.kind == "conflict"
            assert service.get(prop.id).is_ok
        else:
            # No associations: deletion succeeds and the property is gone.
            assert result.is_ok
            assert service.get(prop.id).error.kind == "not_found"
