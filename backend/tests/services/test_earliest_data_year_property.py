"""Property-based test: earliest data year is the minimum activity year.

Feature: carryforward-tolerance-and-year-range, Property 10: Earliest data year
is the minimum activity year.

*For any* set of transaction dates and asset placed-in-service dates (either
possibly empty), ``earliest_data_year`` equals the minimum of the years, or
``None`` when both are empty. Some transactions carry receipts (``#DOC#`` rows
share the transaction's date token), including the earliest one, which must not
change the answer.

**Validates: Requirements 7.2, 7.3, 7.4, 7.5, 7.6, 7.9**
"""

from __future__ import annotations

import contextlib
from datetime import date
from decimal import Decimal

import boto3
from hypothesis import given, settings
from hypothesis import strategies as st
from moto import mock_aws

from logstead.adapters.s3_files import S3FileAdapter
from logstead.models.depreciation import AssetInput
from logstead.models.property import PropertyInput
from logstead.models.transaction import TransactionInput
from logstead.repository.dynamo_repo import DynamoRepository
from logstead.services.dashboard import earliest_data_year
from logstead.services.depreciation import DepreciationService
from logstead.services.property import PropertyService
from logstead.services.transaction import TransactionService

TABLE_NAME = "Logstead"
BUCKET = "logstead-files-test"
REGION = "us-east-1"
USER = "user-abc"


@contextlib.contextmanager
def _moto_services():
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
        yield (
            PropertyService(repo, USER),
            TransactionService(repo, S3FileAdapter(s3, BUCKET)),
            DepreciationService(repo),
        )


_dates = st.dates(min_value=date(1990, 1, 1), max_value=date(2040, 12, 31))

# (date, attach a receipt?)
_txns = st.lists(st.tuples(_dates, st.booleans()), max_size=8)
_assets = st.lists(_dates, max_size=4)


# Feature: carryforward-tolerance-and-year-range, Property 10: Earliest data year
# is the minimum activity year
# **Validates: Requirements 7.2, 7.3, 7.4, 7.5, 7.6, 7.9**
@settings(deadline=None, max_examples=100)
@given(txns=_txns, assets=_assets, receipt_on_earliest=st.booleans())
def test_earliest_data_year_is_minimum_activity_year(
    txns: list[tuple[date, bool]], assets: list[date], receipt_on_earliest: bool
) -> None:
    with _moto_services() as (properties, transactions, depreciation):
        created = properties.create(
            PropertyInput(
                name="Prop0", address_text="1 Main St", property_type="single_family"
            )
        )
        assert created.is_ok, created.error
        pid = created.value.id

        earliest_txn_index = (
            min(range(len(txns)), key=lambda i: txns[i][0]) if txns else None
        )
        for index, (d, with_receipt) in enumerate(txns):
            result = transactions.create(
                TransactionInput(
                    property_id=pid,
                    date=d.isoformat(),
                    amount=Decimal("10.00"),
                    type="income",
                    category_id="rents-received",
                )
            )
            assert result.is_ok, result.error
            attach = with_receipt or (
                receipt_on_earliest and index == earliest_txn_index
            )
            if attach:
                receipt = transactions.attach_receipt(
                    pid, result.value.id, "r.pdf", "application/pdf"
                )
                assert receipt.is_ok, receipt.error

        for d in assets:
            result = depreciation.create_asset(
                AssetInput(
                    property_id=pid,
                    description="HVAC",
                    cost_basis=Decimal("1000.00"),
                    placed_in_service_date=d.isoformat(),
                )
            )
            assert result.is_ok, result.error

        years = [d.year for d, _ in txns] + [d.year for d in assets]
        expected = min(years) if years else None
        assert earliest_data_year(pid, transactions, depreciation) == expected
