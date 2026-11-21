"""Example tests for ReportingService.line12_impact (task 6.3).

**Validates: Requirements 6.3, 9.16**
"""

from __future__ import annotations

from datetime import date
from decimal import Decimal

import boto3
import pytest
from moto import mock_aws

from logstead.adapters.s3_files import S3FileAdapter
from logstead.models.loan import LoanInput
from logstead.models.property import PropertyInput
from logstead.models.transaction import TransactionInput
from logstead.repository.dynamo_repo import DynamoRepository
from logstead.services.depreciation import DepreciationService
from logstead.services.loan import LoanService, StoredLoanError
from logstead.services.property import PropertyService
from logstead.services.report import ReportingService
from logstead.services.transaction import TransactionService

REGION = "us-east-1"
TABLE_NAME = "logstead-line12-impact-test"
BUCKET = "logstead-line12-impact-files"
USER = "user-line12-impact"
ZERO = Decimal("0.00")


@pytest.fixture
def env():
    with mock_aws():
        ddb = boto3.client("dynamodb", region_name=REGION)
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
                {
                    "IndexName": name,
                    "KeySchema": [
                        {"AttributeName": f"{name}PK", "KeyType": "HASH"},
                        {"AttributeName": f"{name}SK", "KeyType": "RANGE"},
                    ],
                    "Projection": {"ProjectionType": "ALL"},
                }
                for name in ("GSI1", "GSI2")
            ],
            BillingMode="PAY_PER_REQUEST",
        )
        s3 = boto3.client("s3", region_name=REGION)
        s3.create_bucket(Bucket=BUCKET)
        repo = DynamoRepository(ddb, TABLE_NAME)
        properties = PropertyService(repo, USER)
        transactions = TransactionService(repo, S3FileAdapter(s3, BUCKET))
        loans = LoanService(repo)
        report = ReportingService(
            transactions, DepreciationService(repo), properties, loans=loans
        )
        report_no_loans = ReportingService(
            transactions, DepreciationService(repo), properties, loans=None
        )
        pid = properties.create(
            PropertyInput(name="P", address_text="1 Main", property_type="single_family")
        ).value.id
        yield {
            "repo": repo,
            "transactions": transactions,
            "loans": loans,
            "report": report,
            "report_no_loans": report_no_loans,
            "pid": pid,
        }


def _add_loan(env, include: bool = True):
    return env["loans"].create_loan(
        LoanInput(
            property_id=env["pid"],
            description="Loan",
            annual_interest_rate=Decimal("6"),
            monthly_payment=Decimal("1000.00"),
            anchor_balance=Decimal("100000.00"),
            anchor_date="2024-01-01",
            extra_principal=ZERO,
            payoff_date=None,
            include_in_report=include,
        )
    ).value


def _add_manual(env, year: int, amount: str, cat: str = "mortgage-interest-banks"):
    r = env["transactions"].create(
        TransactionInput(
            property_id=env["pid"],
            date=date(year, 3, 1).isoformat(),
            amount=Decimal(amount),
            type="expense",
            category_id=cat,
            description=None,
        )
    )
    assert r.error is None, r.error


def test_only_years_with_loan_interest_and_manual_entries(env):
    _add_loan(env)
    _add_manual(env, 2025, "100.00")
    _add_manual(env, 2025, "50.50")
    _add_manual(env, 2024, "10.00")
    _add_manual(env, 2020, "999.00")  # no loan interest that year
    _add_manual(env, 2026, "5.00", cat="other-interest")  # not Line 12

    result = env["report"].line12_impact(env["pid"])
    assert result.error is None
    years = result.value
    assert [y.tax_year for y in years] == [2024, 2025]
    y2025 = years[1]
    assert y2025.loan_interest == env["loans"].property_effective_interest_for_year(
        env["pid"], 2025
    )
    assert y2025.loan_interest > ZERO
    assert y2025.superseded_manual_interest.amount == Decimal("150.50")
    assert y2025.superseded_manual_interest.count == 2
    assert years[0].superseded_manual_interest.count == 1


def test_loan_year_without_manual_entries_is_omitted(env):
    _add_loan(env)
    assert env["report"].line12_impact(env["pid"]).value == []


def test_excluded_loan_is_ignored(env):
    _add_loan(env, include=False)
    _add_manual(env, 2025, "100.00")
    assert env["report"].line12_impact(env["pid"]).value == []


def test_no_loan_service_returns_empty(env):
    _add_manual(env, 2025, "100.00")
    assert env["report_no_loans"].line12_impact(env["pid"]).value == []


def test_unknown_property_is_not_found(env):
    result = env["report"].line12_impact("does-not-exist")
    assert result.error is not None
    assert result.error.kind == "not_found"


def test_stored_loan_error_is_conflict(env, monkeypatch):
    _add_loan(env)
    _add_manual(env, 2025, "100.00")

    def boom(property_id):
        raise StoredLoanError("original_principal")

    monkeypatch.setattr(env["loans"], "report_years", boom)
    result = env["report"].line12_impact(env["pid"])
    assert result.error is not None
    assert result.error.kind == "conflict"


def test_anchor_year_partial_interest_supersedes_manual(env):
    # Anchor 2024-01-01: payments start 2024-02-01, so 2024 has partial
    # generated interest (11 payments) that still supersedes manual Line 12.
    loan = _add_loan(env)
    assert loan.interest_overrides == {}
    _add_manual(env, 2024, "300.00")

    years = env["report"].line12_impact(env["pid"]).value
    assert [y.tax_year for y in years] == [2024]
    assert years[0].loan_interest == env["loans"].property_effective_interest_for_year(
        env["pid"], 2024
    )
    assert years[0].loan_interest > ZERO
    assert years[0].superseded_manual_interest.amount == Decimal("300.00")
    assert years[0].superseded_manual_interest.count == 1


def test_pre_anchor_override_only_year_supersedes_manual(env):
    loan = _add_loan(env)
    r = env["loans"].set_interest_override(env["pid"], loan.id, 2022, "5000.00")
    assert r.error is None, r.error
    _add_manual(env, 2022, "100.00")
    _add_manual(env, 2021, "40.00")  # pre-anchor, no override: manual stands

    years = env["report"].line12_impact(env["pid"]).value
    assert [y.tax_year for y in years] == [2022]
    assert years[0].loan_interest == Decimal("5000.00")
    assert years[0].superseded_manual_interest.amount == Decimal("100.00")
    assert env["loans"].property_effective_interest_for_year(
        env["pid"], 2021
    ) == ZERO
