"""Unit tests for the DynamoDB single-table repository against moto.

These exercise the core repository primitives (put/get/query/delete/
transact_write) plus the two behaviors that matter most for correctness:

* Money attributes are stored as two-decimal strings and parsed back to
  ``Decimal`` with no drift (Requirement 13.3).
* Absent optional attributes are omitted on write so items stay sparse, and are
  reported as unset on read (Requirements 12.2, 12.3).

This is a focused verification of task 3.1 — the full sparse round-trip property
test (3.2) and the broader persistence integration suite (3.3) are separate.
"""

from __future__ import annotations

from decimal import Decimal

import boto3
import pytest
from moto import mock_aws

from logstead.repository import keys
from logstead.repository.dynamo_repo import DynamoRepository

TABLE_NAME = "Logstead"


@pytest.fixture
def client():
    with mock_aws():
        ddb = boto3.client("dynamodb", region_name="us-east-1")
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
        yield ddb


@pytest.fixture
def repo(client):
    return DynamoRepository(client, TABLE_NAME)


def _txn_item(prop_id, txn_id, d, amount, **extra):
    from datetime import date

    year = d.year
    item = {
        "PK": keys.property_scoped_pk(prop_id),
        "SK": keys.transaction_sk(d, txn_id),
        "GSI2PK": keys.gsi2_year_pk(prop_id, year),
        "GSI2SK": keys.gsi2_transaction_sk(d, txn_id),
        "type": "expense",
        "id": txn_id,
        "amount": amount,
    }
    item.update(extra)
    return item


def test_put_and_get_round_trips_money_as_decimal(repo):
    from datetime import date

    prop_id = "p1"
    item = _txn_item(prop_id, "t1", date(2024, 3, 7), Decimal("1234.5"))
    repo.put_item(item)

    got = repo.get_item(item["PK"], item["SK"])
    assert got is not None
    assert got["amount"] == Decimal("1234.50")
    assert isinstance(got["amount"], Decimal)
    assert got["id"] == "t1"


def test_money_stored_as_string_not_number(repo, client):
    from datetime import date

    item = _txn_item("p1", "t1", date(2024, 1, 1), Decimal("10.00"))
    repo.put_item(item)

    raw = client.get_item(
        TableName=TABLE_NAME,
        Key={"PK": {"S": item["PK"]}, "SK": {"S": item["SK"]}},
    )["Item"]
    # Money is a string attribute (S), never a Number (N).
    assert raw["amount"] == {"S": "10.00"}
    assert "N" not in raw["amount"]


def test_absent_optional_attributes_are_omitted(repo, client):
    from datetime import date

    # description is None -> must not be written at all (sparse item).
    item = _txn_item("p1", "t1", date(2024, 1, 1), Decimal("5.00"), description=None)
    repo.put_item(item)

    raw = client.get_item(
        TableName=TABLE_NAME,
        Key={"PK": {"S": item["PK"]}, "SK": {"S": item["SK"]}},
    )["Item"]
    assert "description" not in raw

    got = repo.get_item(item["PK"], item["SK"])
    # Absent attribute is reported as unset (simply not present).
    assert "description" not in got


def test_get_item_missing_returns_none(repo):
    assert repo.get_item("USER#nope", "PROFILE") is None


def test_query_begins_with_orders_by_date_descending(repo):
    from datetime import date

    prop_id = "p1"
    # Insert out of order; inverted-date SK should yield newest-first.
    repo.put_item(_txn_item(prop_id, "a", date(2024, 1, 10), Decimal("1.00")))
    repo.put_item(_txn_item(prop_id, "b", date(2024, 6, 15), Decimal("2.00")))
    repo.put_item(_txn_item(prop_id, "c", date(2023, 12, 1), Decimal("3.00")))

    results = repo.query(
        keys.property_scoped_pk(prop_id),
        sk_begins_with=keys.transaction_list_prefix(),
    )
    dates = [keys.date_from_inverted(r["SK"].split("#")[1]) for r in results]
    assert dates == [date(2024, 6, 15), date(2024, 1, 10), date(2023, 12, 1)]
    # Money parsed back to Decimal for every row.
    assert all(isinstance(r["amount"], Decimal) for r in results)


def test_query_gsi2_by_tax_year(repo):
    from datetime import date

    prop_id = "p1"
    repo.put_item(_txn_item(prop_id, "y2024", date(2024, 5, 5), Decimal("100.00")))
    repo.put_item(_txn_item(prop_id, "y2023", date(2023, 5, 5), Decimal("200.00")))

    results = repo.query(
        keys.gsi2_year_pk(prop_id, 2024),
        sk_begins_with=keys.gsi2_transaction_prefix(),
        index_name="GSI2",
    )
    ids = {r["id"] for r in results}
    assert ids == {"y2024"}


def test_delete_item(repo):
    from datetime import date

    item = _txn_item("p1", "t1", date(2024, 1, 1), Decimal("5.00"))
    repo.put_item(item)
    assert repo.get_item(item["PK"], item["SK"]) is not None

    repo.delete_item(item["PK"], item["SK"])
    assert repo.get_item(item["PK"], item["SK"]) is None


def test_transact_write_puts_multiple_items_atomically(repo):
    user_item = {
        "PK": keys.user_pk("u1"),
        "SK": keys.property_user_sk("p1"),
        "name": "Maple St",
    }
    meta_item = {
        "PK": keys.property_scoped_pk("p1"),
        "SK": keys.property_meta_sk(),
        "name": "Maple St",
    }
    repo.transact_write([{"put": user_item}, {"put": meta_item}])

    assert repo.get_item(user_item["PK"], user_item["SK"]) is not None
    assert repo.get_item(meta_item["PK"], meta_item["SK"]) is not None


def test_transact_write_mixed_put_and_delete(repo):
    asset = {
        "PK": keys.property_scoped_pk("p1"),
        "SK": keys.asset_sk("a1"),
        "costBasis": Decimal("2750.00"),
    }
    repo.put_item(asset)
    # Delete the asset and add a schedule row atomically.
    sched = {
        "PK": keys.property_scoped_pk("p1"),
        "SK": keys.schedule_row_sk("a1", 2024),
        "amount": Decimal("100.00"),
        "remainingBasis": Decimal("2650.00"),
    }
    repo.transact_write(
        [
            {"delete": {"pk": asset["PK"], "sk": asset["SK"]}},
            {"put": sched},
        ]
    )
    assert repo.get_item(asset["PK"], asset["SK"]) is None
    got = repo.get_item(sched["PK"], sched["SK"])
    assert got["amount"] == Decimal("100.00")
    assert got["remainingBasis"] == Decimal("2650.00")


def test_transact_write_rejects_bad_entry(repo):
    with pytest.raises(ValueError):
        repo.transact_write([{"oops": {}}])
