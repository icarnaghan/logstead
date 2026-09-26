"""Inline verification for the Dashboard Service (task 15.1, Requirement 11).

Exercises :class:`DashboardService` end-to-end against a ``moto``-backed table
(base + GSI1 + GSI2) and S3 bucket, composing the real Property, Transaction,
Depreciation, and Reporting services so no aggregate is faked. Coverage mirrors
task 15.1:

* portfolio totals + per-property breakdown for a tax year
  (Requirements 11.1, 11.2);
* the portfolio net equals the sum of the per-property nets, and each
  per-property net equals that property's Schedule E report net so the
  dashboard stays consistent with the report (design Property 26);
* the empty state returns an add-first-property prompt rather than an error
  (Requirement 11.4).

The Property-based test (15.2) and the standalone empty-state unit test (15.3)
are intentionally out of scope here.
"""

from __future__ import annotations

from decimal import Decimal

import boto3
import pytest
from moto import mock_aws

from logstead.adapters.s3_files import S3FileAdapter
from logstead.models.property import PropertyInput
from logstead.models.transaction import TransactionInput
from logstead.repository.dynamo_repo import DynamoRepository
from logstead.services.dashboard import (
    ADD_FIRST_PROPERTY_PROMPT,
    DashboardService,
)
from logstead.services.depreciation import DepreciationService
from logstead.services.property import PropertyService
from logstead.services.report import ReportingService
from logstead.services.transaction import TransactionService

TABLE_NAME = "Logstead"
BUCKET = "logstead-files-test"
REGION = "us-east-1"
USER = "user-abc"
TAX_YEAR = 2024


@pytest.fixture
def aws():
    """A moto context with the table (base + GSI1 + GSI2) and S3 bucket."""
    with mock_aws():
        ddb = boto3.client("dynamodb", region_name=REGION)
        ddb.create_table(
            TableName=TABLE_NAME,
            AttributeDefinitions=[
                {"AttributeName": "PK", "AttributeType": "S"},
                {"AttributeName": "SK", "AttributeType": "S"},
                {"AttributeName": "GSI1PK", "AttributeType": "S"},
                {"AttributeName": "GSI1SK", "AttributeType": "S"},
                {"AttributeName": "GSI2PK", "AttributeType": "S"},
                {"AttributeName": "GSI2SK", "AttributeType": "S"},
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
        yield ddb, s3


@pytest.fixture
def repo(aws):
    ddb, _ = aws
    return DynamoRepository(ddb, TABLE_NAME)


@pytest.fixture
def properties(repo):
    return PropertyService(repo, USER)


@pytest.fixture
def transactions(aws, repo):
    _, s3 = aws
    return TransactionService(repo, S3FileAdapter(s3, BUCKET))


@pytest.fixture
def depreciation(repo):
    return DepreciationService(repo)


@pytest.fixture
def reports(transactions, depreciation, properties):
    return ReportingService(transactions, depreciation, properties)


@pytest.fixture
def dashboard(properties, reports):
    return DashboardService(properties, reports)


# --- Seeding helpers ---------------------------------------------------------


def _make_property(properties: PropertyService, name: str) -> str:
    result = properties.create(
        PropertyInput(name=name, address_text=f"{name} St", property_type="single_family")
    )
    assert result.is_ok
    return result.value.id


def _txn(
    transactions: TransactionService,
    property_id: str,
    *,
    date: str,
    amount: str,
    type: str,
    category_id: str,
    description: str | None = None,
) -> None:
    result = transactions.create(
        TransactionInput(
            property_id=property_id,
            date=date,
            amount=Decimal(amount),
            type=type,
            category_id=category_id,
            description=description,
        )
    )
    assert result.is_ok, result.error


# --- Portfolio + per-property summaries (Requirements 11.1, 11.2) ------------


def test_dashboard_totals_and_per_property_match_reports(
    dashboard, reports, properties, transactions
):
    # Property A: income 2000, expenses 500 -> net 1500.
    pid_a = _make_property(properties, "Alpha")
    _txn(transactions, pid_a, date="2024-01-05", amount="2000.00",
         type="income", category_id="rents-received")
    _txn(transactions, pid_a, date="2024-02-05", amount="500.00",
         type="expense", category_id="repairs")

    # Property B: income 3000, expenses 1200 -> net 1800.
    pid_b = _make_property(properties, "Beta")
    _txn(transactions, pid_b, date="2024-03-05", amount="3000.00",
         type="income", category_id="rents-received")
    _txn(transactions, pid_b, date="2024-04-05", amount="1200.00",
         type="expense", category_id="utilities")

    summary = dashboard.portfolio_summary(TAX_YEAR)

    assert summary.tax_year == TAX_YEAR
    assert summary.has_properties is True
    assert summary.empty_state_prompt is None

    # Per-property breakdown (Requirement 11.2), keyed for order-independence.
    by_id = {p.property_id: p for p in summary.properties}
    assert set(by_id) == {pid_a, pid_b}

    assert by_id[pid_a].property_name == "Alpha"
    assert by_id[pid_a].total_income == Decimal("2000.00")
    assert by_id[pid_a].total_expenses == Decimal("500.00")
    assert by_id[pid_a].net == Decimal("1500.00")

    assert by_id[pid_b].total_income == Decimal("3000.00")
    assert by_id[pid_b].total_expenses == Decimal("1200.00")
    assert by_id[pid_b].net == Decimal("1800.00")

    # Portfolio totals (Requirement 11.1).
    assert summary.total_income == Decimal("5000.00")
    assert summary.total_expenses == Decimal("1700.00")
    assert summary.net == Decimal("3300.00")

    # Portfolio net == sum of per-property nets (design Property 26).
    assert summary.net == sum((p.net for p in summary.properties), Decimal("0.00"))

    # Each per-property figure matches that property's Schedule E report totals
    # (dashboard stays consistent with the report).
    for pid, ps in by_id.items():
        report_totals = reports.report_for(pid, TAX_YEAR).value.totals
        assert ps.total_income == report_totals.total_income
        assert ps.total_expenses == report_totals.total_expenses
        assert ps.net == report_totals.net

    # Portfolio net also equals the sum of the per-property report nets.
    report_net_sum = sum(
        (reports.report_for(pid, TAX_YEAR).value.totals.net for pid in by_id),
        Decimal("0.00"),
    )
    assert summary.net == report_net_sum


def test_dashboard_scopes_to_requested_tax_year(dashboard, properties, transactions):
    pid = _make_property(properties, "YearScoped")
    _txn(transactions, pid, date="2024-06-01", amount="1000.00",
         type="income", category_id="rents-received")
    _txn(transactions, pid, date="2023-06-01", amount="9999.00",
         type="income", category_id="rents-received")

    summary = dashboard.portfolio_summary(TAX_YEAR)
    assert summary.total_income == Decimal("1000.00")


# --- Empty state (Requirement 11.4) -----------------------------------------


def test_dashboard_empty_state_returns_prompt_not_error(dashboard):
    assert dashboard.has_properties() is False

    summary = dashboard.portfolio_summary(TAX_YEAR)
    assert summary.has_properties is False
    assert summary.empty_state_prompt == ADD_FIRST_PROPERTY_PROMPT
    assert summary.properties == ()
    assert summary.total_income == Decimal("0.00")
    assert summary.total_expenses == Decimal("0.00")
    assert summary.net == Decimal("0.00")


def test_summary_alias_matches_portfolio_summary(dashboard, properties, transactions):
    pid = _make_property(properties, "Alias")
    _txn(transactions, pid, date="2024-01-05", amount="100.00",
         type="income", category_id="rents-received")

    assert dashboard.summary(TAX_YEAR) == dashboard.portfolio_summary(TAX_YEAR)
