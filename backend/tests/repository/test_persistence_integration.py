"""Integration tests for persistence round-trips (Requirements 13.1, 13.2, 5.4, 5.5).

These tests exercise the :class:`DynamoRepository` against a moto-backed
DynamoDB table end-to-end, covering the behaviors that matter for durable,
multi-year Schedule E record keeping:

* **Single-table writes/reads** round-trip representative item types — a
  property (meta + user-view rows), a transaction, and a depreciable asset —
  through the one physical table (Req 13.1).
* **Date-descending transaction listing** via the inverted-date sort key
  returns a property's transactions newest-first (Req 5.4).
* **Tax-year-scoped GSI2 queries** return exactly the transactions whose date
  falls in the selected tax year and nothing from adjacent years (Req 5.5).
* **Money string round-trips** preserve two-decimal ``Decimal`` amounts with no
  drift after a write/read cycle (Req 13.1 / 13.3 boundary).
* **Survives sign-out / sign-in**: a *fresh* ``DynamoRepository`` instance
  pointed at the same table still reads previously-written data, and prior
  tax-year records remain retrievable without expiration (Req 13.1, 13.2).

Unlike ``test_dynamo_repo.py`` (which unit-tests the repository primitives),
this suite treats the repository as a black box and asserts on persistence
guarantees a user would notice across sessions and years.
"""

from __future__ import annotations

from datetime import date
from decimal import Decimal

import boto3
import pytest
from moto import mock_aws

from logstead.repository import keys
from logstead.repository.dynamo_repo import DynamoRepository

TABLE_NAME = "Logstead"
REGION = "us-east-1"


@pytest.fixture
def aws():
    """Start moto for the duration of a test so state persists across repos.

    The moto mock is what stands in for the durable DynamoDB table. Keeping it
    active for the whole test lets us build a *new* ``DynamoRepository`` against
    the same table to simulate a sign-out/sign-in (Req 13.1).
    """
    with mock_aws():
        yield


@pytest.fixture
def client(aws):
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
    return ddb


@pytest.fixture
def repo(client):
    return DynamoRepository(client, TABLE_NAME)


# --- Item builders -----------------------------------------------------------
# Small helpers that produce representative items for each domain type, keyed
# via the real key scheme so we exercise the same layout the services will use.


def _property_rows(user_id: str, prop_id: str, name: str, address: str):
    """The two rows a property occupies: the user-view row and the meta mirror."""
    user_row = {
        "PK": keys.user_pk(user_id),
        "SK": keys.property_user_sk(prop_id),
        "type": "property",
        "id": prop_id,
        "name": name,
        "address": address,
        "propertyType": "single_family",
    }
    meta_row = {
        "PK": keys.property_scoped_pk(prop_id),
        "SK": keys.property_meta_sk(),
        "type": "property",
        "id": prop_id,
        "name": name,
        "address": address,
        "propertyType": "single_family",
    }
    return user_row, meta_row


def _transaction_row(prop_id: str, txn_id: str, d: date, amount: Decimal, **extra):
    item = {
        "PK": keys.property_scoped_pk(prop_id),
        "SK": keys.transaction_sk(d, txn_id),
        "GSI2PK": keys.gsi2_year_pk(prop_id, d.year),
        "GSI2SK": keys.gsi2_transaction_sk(d, txn_id),
        "type": "expense",
        "id": txn_id,
        "date": d.isoformat(),
        "amount": amount,
    }
    item.update(extra)
    return item


def _asset_row(prop_id: str, asset_id: str, cost_basis: Decimal, **extra):
    item = {
        "PK": keys.property_scoped_pk(prop_id),
        "SK": keys.asset_sk(asset_id),
        "type": "asset",
        "id": asset_id,
        "description": "Roof replacement",
        "costBasis": cost_basis,
        "recoveryPeriod": Decimal("27.5"),
        "placedInService": "2024-06-15",
    }
    item.update(extra)
    return item


# --- 1. Single-table writes/reads round-trip (Req 13.1) ----------------------


def test_property_transaction_asset_round_trip_single_table(repo):
    """A property, a transaction, and an asset all persist and read back.

    All three item types live in the one physical table and are retrievable by
    their primary keys with their attributes intact (Req 13.1).
    """
    user_id = "u1"
    prop_id = "p1"
    user_row, meta_row = _property_rows(user_id, prop_id, "Maple St", "1 Maple St")
    repo.transact_write([{"put": user_row}, {"put": meta_row}])

    txn = _transaction_row(
        prop_id, "t1", date(2024, 3, 7), Decimal("1200.00"), category="repairs"
    )
    repo.put_item(txn)

    asset = _asset_row(prop_id, "a1", Decimal("27500.00"))
    repo.put_item(asset)

    # Property: both rows come back.
    got_user = repo.get_item(user_row["PK"], user_row["SK"])
    got_meta = repo.get_item(meta_row["PK"], meta_row["SK"])
    assert got_user is not None and got_user["name"] == "Maple St"
    assert got_meta is not None and got_meta["address"] == "1 Maple St"
    assert got_user["propertyType"] == "single_family"

    # Transaction: retrievable with money parsed to Decimal.
    got_txn = repo.get_item(txn["PK"], txn["SK"])
    assert got_txn is not None
    assert got_txn["id"] == "t1"
    assert got_txn["amount"] == Decimal("1200.00")
    assert got_txn["category"] == "repairs"

    # Asset: retrievable with cost basis parsed to Decimal.
    got_asset = repo.get_item(asset["PK"], asset["SK"])
    assert got_asset is not None
    assert got_asset["costBasis"] == Decimal("27500.00")
    assert got_asset["description"] == "Roof replacement"


# --- 2. Date-descending transaction listing (Req 5.4) -----------------------


def test_transaction_listing_is_date_descending(repo):
    """Listing a property's transactions returns them newest-first (Req 5.4).

    Items are inserted out of chronological order; the inverted-date sort key
    must still yield a strictly date-descending listing.
    """
    prop_id = "p1"
    inserted = [
        ("older", date(2024, 1, 3)),
        ("newest", date(2024, 11, 30)),
        ("middle", date(2024, 6, 15)),
        ("oldest", date(2023, 12, 31)),
    ]
    for txn_id, d in inserted:
        repo.put_item(_transaction_row(prop_id, txn_id, d, Decimal("10.00")))

    results = repo.query(
        keys.property_scoped_pk(prop_id),
        sk_begins_with=keys.transaction_list_prefix(),
    )
    dates = [date.fromisoformat(r["date"]) for r in results]
    assert dates == sorted(dates, reverse=True)
    assert [r["id"] for r in results] == ["newest", "middle", "older", "oldest"]


# --- 3. Tax-year-scoped GSI2 query returns exactly in-year (Req 5.5) ---------


def test_gsi2_tax_year_query_returns_exactly_in_year(repo):
    """A GSI2 tax-year query returns only that year's transactions (Req 5.5).

    Transactions span three tax years including the year boundaries (Jan 1 and
    Dec 31); querying 2024 must return exactly the four 2024 rows and exclude
    the 2023 and 2025 rows even though they sit one day either side.
    """
    prop_id = "p1"
    rows = [
        ("y2023_dec31", date(2023, 12, 31)),
        ("y2024_jan1", date(2024, 1, 1)),
        ("y2024_mid", date(2024, 7, 4)),
        ("y2024_nov", date(2024, 11, 2)),
        ("y2024_dec31", date(2024, 12, 31)),
        ("y2025_jan1", date(2025, 1, 1)),
    ]
    for txn_id, d in rows:
        repo.put_item(_transaction_row(prop_id, txn_id, d, Decimal("50.00")))

    results = repo.query(
        keys.gsi2_year_pk(prop_id, 2024),
        sk_begins_with=keys.gsi2_transaction_prefix(),
        index_name="GSI2",
    )
    ids = {r["id"] for r in results}
    assert ids == {"y2024_jan1", "y2024_mid", "y2024_nov", "y2024_dec31"}

    # And the in-year results are themselves date-descending on the GSI (5.4/5.5).
    dates = [date.fromisoformat(r["date"]) for r in results]
    assert dates == sorted(dates, reverse=True)


# --- 4. Money string round-trips with no drift ------------------------------


@pytest.mark.parametrize(
    "amount",
    [
        Decimal("0.00"),
        Decimal("0.01"),
        Decimal("9.99"),
        Decimal("100.00"),
        Decimal("1234.50"),
        Decimal("99999999.99"),
    ],
)
def test_money_amounts_round_trip_without_drift(repo, amount):
    """Money written as Decimal reads back as the identical two-decimal Decimal.

    Amounts are persisted as fixed two-decimal strings, so a write/read cycle
    must be exact for representative values including zero, one cent, and large
    amounts (Req 13.1 boundary; 13.3).
    """
    prop_id = "p1"
    txn = _transaction_row(prop_id, "t1", date(2024, 2, 2), amount)
    repo.put_item(txn)

    got = repo.get_item(txn["PK"], txn["SK"])
    assert got is not None
    assert isinstance(got["amount"], Decimal)
    assert got["amount"] == amount.quantize(Decimal("0.01"))


def test_asset_cost_and_remaining_basis_round_trip(repo):
    """Multiple money attributes on one item all round-trip to Decimal."""
    prop_id = "p1"
    sched = {
        "PK": keys.property_scoped_pk(prop_id),
        "SK": keys.schedule_row_sk("a1", 2024),
        "type": "schedule_row",
        "amount": Decimal("500.01"),
        "remainingBasis": Decimal("26999.99"),
    }
    repo.put_item(sched)

    got = repo.get_item(sched["PK"], sched["SK"])
    assert got is not None
    assert got["amount"] == Decimal("500.01")
    assert got["remainingBasis"] == Decimal("26999.99")


# --- 5. Survives sign-out / sign-in (Req 13.1, 13.2) ------------------------


def test_data_persists_across_fresh_repository_instance(client):
    """Data written by one repo is readable by a brand-new repo (Req 13.1).

    A fresh ``DynamoRepository`` against the same table simulates the user
    signing out and back in: the property, transaction, and asset written in
    the first "session" are all present in the second.
    """
    session_one = DynamoRepository(client, TABLE_NAME)

    user_id, prop_id = "u1", "p1"
    user_row, meta_row = _property_rows(user_id, prop_id, "Elm Ave", "9 Elm Ave")
    session_one.transact_write([{"put": user_row}, {"put": meta_row}])
    session_one.put_item(
        _transaction_row(prop_id, "t1", date(2024, 4, 1), Decimal("875.25"))
    )
    session_one.put_item(_asset_row(prop_id, "a1", Decimal("12000.00")))

    # --- Simulate sign-out / sign-in: a new repository, same table. ---
    session_two = DynamoRepository(client, TABLE_NAME)

    assert session_two.get_item(user_row["PK"], user_row["SK"]) is not None
    got_txn = session_two.get_item(
        keys.property_scoped_pk(prop_id), keys.transaction_sk(date(2024, 4, 1), "t1")
    )
    assert got_txn is not None
    assert got_txn["amount"] == Decimal("875.25")
    got_asset = session_two.get_item(
        keys.property_scoped_pk(prop_id), keys.asset_sk("a1")
    )
    assert got_asset is not None
    assert got_asset["costBasis"] == Decimal("12000.00")


def test_updates_and_deletes_persist_across_sessions(client):
    """An update and a delete made in one session are visible in the next (13.1)."""
    session_one = DynamoRepository(client, TABLE_NAME)
    prop_id = "p1"

    keep = _transaction_row(prop_id, "keep", date(2024, 5, 5), Decimal("10.00"))
    drop = _transaction_row(prop_id, "drop", date(2024, 5, 6), Decimal("20.00"))
    session_one.put_item(keep)
    session_one.put_item(drop)

    # Update "keep" (replace with a new amount) and delete "drop".
    updated = _transaction_row(prop_id, "keep", date(2024, 5, 5), Decimal("33.33"))
    session_one.put_item(updated)
    session_one.delete_item(drop["PK"], drop["SK"])

    session_two = DynamoRepository(client, TABLE_NAME)
    got_keep = session_two.get_item(keep["PK"], keep["SK"])
    assert got_keep is not None and got_keep["amount"] == Decimal("33.33")
    assert session_two.get_item(drop["PK"], drop["SK"]) is None


def test_prior_tax_year_records_are_retained(client):
    """Prior-year transactions and assets remain retrievable (Req 13.2).

    Records for 2022, 2023, and 2024 all persist without expiration. A fresh
    session can still query each prior year's transactions via GSI2 and read the
    prior-year asset row.
    """
    session_one = DynamoRepository(client, TABLE_NAME)
    prop_id = "p1"

    per_year = {
        2022: ("t2022", date(2022, 8, 8), Decimal("111.00")),
        2023: ("t2023", date(2023, 8, 8), Decimal("222.00")),
        2024: ("t2024", date(2024, 8, 8), Decimal("333.00")),
    }
    for _year, (txn_id, d, amount) in per_year.items():
        session_one.put_item(_transaction_row(prop_id, txn_id, d, amount))
    session_one.put_item(_asset_row(prop_id, "old_asset", Decimal("5000.00")))

    # New session: every prior year is still queryable and unchanged.
    session_two = DynamoRepository(client, TABLE_NAME)
    for year, (txn_id, _d, amount) in per_year.items():
        results = session_two.query(
            keys.gsi2_year_pk(prop_id, year),
            sk_begins_with=keys.gsi2_transaction_prefix(),
            index_name="GSI2",
        )
        assert [r["id"] for r in results] == [txn_id]
        assert results[0]["amount"] == amount

    got_asset = session_two.get_item(
        keys.property_scoped_pk(prop_id), keys.asset_sk("old_asset")
    )
    assert got_asset is not None
    assert got_asset["costBasis"] == Decimal("5000.00")
