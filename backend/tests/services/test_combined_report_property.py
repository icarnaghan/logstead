"""Property-based test: combined-report totals equal per-property sums.

Design Property 24 (Requirement 10.6): *for any* set of per-property reports for
a tax year, each value in the portfolio totals column equals the sum of that
value across all per-property columns.

``ReportingService.combined_report(property_ids | None, tax_year)`` builds one
per-property :class:`ScheduleEReport` column plus a portfolio
:class:`ReportTotals` column. This property drives that aggregation universally:
it generates several properties, each with an arbitrary mix of income and
expense transactions dated within a single target tax year, persists them, then
asserts the combined report's portfolio ``total_income`` / ``total_expenses`` /
``net`` equal the exact ``Decimal`` sums of the per-property totals — and that
``net`` also equals ``total_income - total_expenses`` and the sum of per-property
nets. It further checks the combined report renders exactly one column per
property, and that ``combined_report(None, ...)`` covers exactly the user's
properties.

Each Hypothesis example provisions its own moto-backed single-table DynamoDB
(base + GSI1 + GSI2) plus an S3 bucket needed to construct the
``S3FileAdapter``, mirroring the fixture pattern in ``test_report.py``.
Per-example provisioning is not instantaneous, so the deadline is disabled; the
example count is held at 100 to keep the moto-backed run reasonable.
"""

from __future__ import annotations

import contextlib
from decimal import Decimal

import boto3
from hypothesis import given, settings
from hypothesis import strategies as st
from moto import mock_aws

from logstead.adapters.s3_files import S3FileAdapter
from logstead.models.property import PropertyInput
from logstead.models.transaction import TransactionInput
from logstead.repository.dynamo_repo import DynamoRepository
from logstead.services.depreciation import DepreciationService
from logstead.services.property import PropertyService
from logstead.services.report import ReportingService
from logstead.services.transaction import TransactionService

TABLE_NAME = "Logstead"
BUCKET = "logstead-files-test"
REGION = "us-east-1"
USER = "user-abc"
TAX_YEAR = 2024


@contextlib.contextmanager
def _moto_service():
    """Provision an isolated moto DynamoDB (base + GSI1 + GSI2) and S3 bucket.

    Yields the composed Property, Transaction, and Reporting services bound to
    freshly created resources so each Hypothesis example runs against a clean
    store with no aggregate faked.
    """
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
        repo = DynamoRepository(ddb, TABLE_NAME)
        properties = PropertyService(repo, USER)
        transactions = TransactionService(repo, S3FileAdapter(s3, BUCKET))
        depreciation = DepreciationService(repo)
        yield (
            ReportingService(transactions, depreciation, properties),
            properties,
            transactions,
        )


# --- Strategies ---------------------------------------------------------------
#
# Each transaction is an (type, category, amount) triple dated within the target
# tax year. Two known, non-Other categories are used so the description rule and
# the unknown-category path never confound this property: an income line (Line 3,
# Rents received) and an expense line (Line 14, Repairs).
_amounts = st.decimals(
    min_value=Decimal("0.01"),
    max_value=Decimal("1000000.00"),
    places=2,
    allow_nan=False,
    allow_infinity=False,
)

_txn = st.tuples(
    st.sampled_from(
        [("income", "rents-received"), ("expense", "repairs")]
    ),
    _amounts,
)

# A property is an arbitrary (possibly empty) list of transactions.
_property_txns = st.lists(_txn, min_size=0, max_size=12)


def _iso_date(index: int) -> str:
    """A deterministic in-year ISO date, cycling day/month to stay valid."""
    month = (index % 12) + 1
    day = (index % 28) + 1
    return f"{TAX_YEAR:04d}-{month:02d}-{day:02d}"


# Feature: logstead, Property 24: Combined report totals equal per-property sums
@settings(deadline=None, max_examples=100)
@given(properties_txns=st.lists(_property_txns, min_size=1, max_size=4))
def test_combined_report_totals_equal_per_property_sums(
    properties_txns: list[list[tuple[tuple[str, str], Decimal]]],
) -> None:
    """The portfolio totals column equals the sum of the per-property totals.

    Validates: Requirement 10.6
    """
    with _moto_service() as (service, properties, transactions):
        property_ids: list[str] = []
        for p_index, txns in enumerate(properties_txns):
            created = properties.create(
                PropertyInput(
                    name=f"Prop{p_index}",
                    address_text=f"{p_index} Main St",
                    property_type="single_family",
                )
            )
            assert created.is_ok, created.error
            pid = created.value.id
            property_ids.append(pid)

            for t_index, ((ttype, category), amount) in enumerate(txns):
                result = transactions.create(
                    TransactionInput(
                        property_id=pid,
                        date=_iso_date(t_index),
                        amount=amount,
                        type=ttype,
                        category_id=category,
                        description=None,
                    )
                )
                assert result.is_ok, result.error

        result = service.combined_report(property_ids, TAX_YEAR)
        assert result.is_ok, result.error
        combined = result.value

        # (d) One per-property column per property, in supplied order.
        assert combined.tax_year == TAX_YEAR
        assert len(combined.properties) == len(property_ids)
        assert [c.header.property_id for c in combined.properties] == property_ids

        # Exact-Decimal per-property sums.
        sum_income = sum(
            (c.totals.total_income for c in combined.properties), Decimal("0.00")
        )
        sum_expenses = sum(
            (c.totals.total_expenses for c in combined.properties), Decimal("0.00")
        )
        sum_net = sum(
            (c.totals.net for c in combined.properties), Decimal("0.00")
        )

        # (a) income, (b) expenses, (c) net all equal the per-property sums, and
        # net reconciles to income - expenses.
        assert combined.totals.total_income == sum_income
        assert combined.totals.total_expenses == sum_expenses
        assert combined.totals.net == sum_net
        assert combined.totals.net == (
            combined.totals.total_income - combined.totals.total_expenses
        )

        # combined_report(None, ...) covers exactly the user's properties and
        # yields identical portfolio totals.
        all_props = service.combined_report(None, TAX_YEAR)
        assert all_props.is_ok
        assert {c.header.property_id for c in all_props.value.properties} == set(
            property_ids
        )
        assert all_props.value.totals.total_income == combined.totals.total_income
        assert all_props.value.totals.total_expenses == combined.totals.total_expenses
        assert all_props.value.totals.net == combined.totals.net
