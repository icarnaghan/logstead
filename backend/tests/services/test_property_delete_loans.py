"""PropertyService.delete guard: a property with a Loan cannot be deleted."""

from __future__ import annotations

from datetime import date
from decimal import Decimal

import boto3
import pytest
from moto import mock_aws

from logstead.models.loan import LoanInput
from logstead.models.property import PropertyInput
from logstead.repository import keys
from logstead.repository.dynamo_repo import DynamoRepository
from logstead.services.loan import LoanService
from logstead.services.property import PropertyService

TABLE_NAME = "Logstead"
USER = "user-1"


def _gsi(name: str, pk: str, sk: str) -> dict:
    return {
        "IndexName": name,
        "KeySchema": [
            {"AttributeName": pk, "KeyType": "HASH"},
            {"AttributeName": sk, "KeyType": "RANGE"},
        ],
        "Projection": {"ProjectionType": "ALL"},
    }


@pytest.fixture
def repo():
    with mock_aws():
        ddb = boto3.client("dynamodb", region_name="us-east-1")
        ddb.create_table(
            TableName=TABLE_NAME,
            AttributeDefinitions=[
                {"AttributeName": n, "AttributeType": "S"}
                for n in ("PK", "SK", "GSI1PK", "GSI1SK", "GSI2PK", "GSI2SK")
            ],
            KeySchema=[
                {"AttributeName": "PK", "KeyType": "HASH"},
                {"AttributeName": "SK", "KeyType": "RANGE"},
            ],
            GlobalSecondaryIndexes=[
                _gsi("GSI1", "GSI1PK", "GSI1SK"),
                _gsi("GSI2", "GSI2PK", "GSI2SK"),
            ],
            BillingMode="PAY_PER_REQUEST",
        )
        yield DynamoRepository(ddb, TABLE_NAME)


@pytest.fixture
def props(repo):
    return PropertyService(repo, USER)


@pytest.fixture
def loans(repo):
    return LoanService(repo, today=lambda: date(2025, 6, 1))


@pytest.fixture
def prop_id(props):
    res = props.create(PropertyInput(name="Cabin", address_text="1 Main St"))
    assert res.error is None
    return res.value.id


def _loan_input(property_id: str) -> LoanInput:
    return LoanInput(
        property_id=property_id,
        description="Mortgage",
        annual_interest_rate=Decimal("6.875"),
        monthly_payment=Decimal("1970.79"),
        anchor_balance=Decimal("290000.00"),
        anchor_date="2024-03-01",
    )


def test_delete_with_loan_is_conflict_and_property_intact(
    props, loans, prop_id
):
    loan = loans.create_loan(_loan_input(prop_id)).value

    res = props.delete(prop_id)

    assert res.error.kind == "conflict"
    assert props.get(prop_id).error is None
    assert [p.id for p in props.list()] == [prop_id]
    assert [v.id for v in loans.list_loans(prop_id).value] == [loan.id]


def test_delete_succeeds_after_loan_removed(props, loans, prop_id):
    loan = loans.create_loan(_loan_input(prop_id)).value
    assert props.delete(prop_id).error.kind == "conflict"

    assert loans.delete_loan(prop_id, loan.id).error is None

    assert props.delete(prop_id).error is None
    assert props.get(prop_id).error.kind == "not_found"
    assert props.list() == []


def test_rollup_only_rows_do_not_block_delete(props, loans, repo, prop_id):
    loan = loans.create_loan(_loan_input(prop_id)).value
    # Remove only the Loan row, leaving its yearly rollup rows behind.
    repo.delete_item(keys.property_scoped_pk(prop_id), keys.loan_sk(loan.id))
    rollups = repo.query(
        keys.property_scoped_pk(prop_id),
        sk_begins_with=keys.loan_year_list_prefix(loan.id),
        money_attrs=set(),
    )
    assert rollups  # precondition: rollup-only rows exist

    assert props.delete(prop_id).error is None
