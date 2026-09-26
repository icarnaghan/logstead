"""Unit tests for the Schedule E category catalog and seeding (task 4.1).

Covers Requirements 7.1 (income categories), 7.2 (expense categories), and 7.5
(Line 18 excluded). Verifies the code-defined catalog is correct and that
``seed_categories`` + ``list_categories`` round-trip through a moto-backed
DynamoDB table with the expected count, lines, and flags.

The Property 14 property-based test lives with task 4.2 and is intentionally
not implemented here.
"""

from __future__ import annotations

import boto3
import pytest
from moto import mock_aws

from logstead.repository import keys
from logstead.repository.dynamo_repo import DynamoRepository
from logstead.services.category import (
    CATEGORY_CATALOG,
    list_categories,
    seed_categories,
)

TABLE_NAME = "Logstead"

# Expected Schedule E lines: income 3-4, expenses 5-17 and 19; NOT 18.
_EXPECTED_INCOME_LINES = {3, 4}
_EXPECTED_EXPENSE_LINES = {5, 6, 7, 8, 9, 10, 11, 12, 13, 14, 15, 16, 17, 19}
_EXPECTED_LINES = _EXPECTED_INCOME_LINES | _EXPECTED_EXPENSE_LINES


@pytest.fixture
def client():
    with mock_aws():
        ddb = boto3.client("dynamodb", region_name="us-east-1")
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
        yield ddb


@pytest.fixture
def repo(client):
    return DynamoRepository(client, TABLE_NAME)


# --- Catalog definition (no persistence) -------------------------------------

def test_catalog_has_expected_lines_and_no_line_18():
    lines = [c.schedule_e_line for c in CATEGORY_CATALOG]
    assert set(lines) == _EXPECTED_LINES
    # Line 18 (Depreciation) is excluded from assignable categories (7.5).
    assert 18 not in lines
    # No duplicate lines in the catalog.
    assert len(lines) == len(set(lines))


def test_catalog_income_and_expense_split():
    income = {c.schedule_e_line for c in CATEGORY_CATALOG if c.kind == "income"}
    expense = {c.schedule_e_line for c in CATEGORY_CATALOG if c.kind == "expense"}
    assert income == _EXPECTED_INCOME_LINES
    assert expense == _EXPECTED_EXPENSE_LINES


def test_other_line_19_requires_description():
    other = next(c for c in CATEGORY_CATALOG if c.schedule_e_line == 19)
    assert other.kind == "expense"
    assert other.label == "Other"
    assert other.requires_description is True
    # Only Line 19 requires a description.
    for c in CATEGORY_CATALOG:
        if c.schedule_e_line != 19:
            assert c.requires_description is False


def test_income_lines_labels():
    by_line = {c.schedule_e_line: c for c in CATEGORY_CATALOG}
    assert by_line[3].label == "Rents received"
    assert by_line[4].label == "Royalties received"


# --- Seed + list round-trip (moto-backed) ------------------------------------

def test_seed_then_list_round_trips_full_catalog(repo):
    seed_categories(repo)
    listed = list_categories(repo)

    assert len(listed) == len(CATEGORY_CATALOG)
    assert {c.schedule_e_line for c in listed} == _EXPECTED_LINES
    assert 18 not in {c.schedule_e_line for c in listed}
    # Round-trip preserves every field for every category.
    assert set(listed) == set(CATEGORY_CATALOG)


def test_seed_writes_category_items_with_meta_sk(repo, client):
    seed_categories(repo)
    other = next(c for c in CATEGORY_CATALOG if c.schedule_e_line == 19)
    raw = client.get_item(
        TableName=TABLE_NAME,
        Key={
            "PK": {"S": keys.category_pk(other.id)},
            "SK": {"S": keys.category_sk()},
        },
    )["Item"]
    assert raw["kind"] == {"S": "expense"}
    assert raw["scheduleELine"] == {"N": "19"}
    assert raw["requiresDescription"] == {"BOOL": True}


def test_list_before_seed_is_empty(repo):
    assert list_categories(repo) == []


def test_seed_is_idempotent(repo):
    seed_categories(repo)
    seed_categories(repo)
    listed = list_categories(repo)
    assert len(listed) == len(CATEGORY_CATALOG)
    assert set(listed) == set(CATEGORY_CATALOG)
