"""Property-based test: rows outside the itemized rule sum as before.

Design Property 4 (Requirements 4.1, 4.5, 6.6, 11.7, 12.2): *for any*
collection of transactions where every row is either unmarked (legacy rows
stored without an ``itemized`` attribute included), or marked ``itemized`` but
in a category outside ``ITEMIZED_CATEGORIES``, or in a non-itemized category,
each report line total equals the plain sum of that line's rows -- identical to
the pre-feature report.

The real ``ReportingService`` runs over moto-backed DynamoDB. Rows are written
three ways so the whole input space is covered:

* through ``TransactionService.create`` (any category, unmarked, optionally
  ``imported``) -- this includes unmarked ``repairs`` rows, which are entered
  totals and must still sum plainly (multiple rows add up);
* directly through the repository as marked rows in non-itemized expense
  categories (the service refuses to create these, but stored or restored data
  could contain them, and the report must treat them as plain totals);
* directly through the repository as legacy items with no ``itemized`` key.

The expected values come from a plain-sum model computed in the test, grouped
by the category catalog's Schedule E line. No depreciable assets exist, so
Line 18 is pinned to ``0.00`` and excluded.
"""

from __future__ import annotations

import contextlib
import datetime as dt
import uuid
from decimal import Decimal

import boto3
from hypothesis import given, settings
from hypothesis import strategies as st
from moto import mock_aws

from logstead.adapters.s3_files import S3FileAdapter
from logstead.models.property import PropertyInput
from logstead.models.transaction import Transaction, TransactionInput
from logstead.repository.dynamo_repo import DynamoRepository
from logstead.services.category import CATEGORY_CATALOG
from logstead.services.depreciation import DepreciationService
from logstead.services.itemized import ITEMIZED_CATEGORIES
from logstead.services.property import PropertyService
from logstead.services.report import DEPRECIATION_LINE, ReportingService
from logstead.services.transaction import TransactionService, transaction_to_item

TABLE_NAME = "Logstead"
BUCKET = "logstead-files-test"
REGION = "us-east-1"
USER = "user-abc"
TAX_YEAR = 2024

_CATEGORY_BY_ID = {c.id: c for c in CATEGORY_CATALOG}
_ALL_IDS = tuple(c.id for c in CATEGORY_CATALOG)
_NON_ITEMIZED_EXPENSE_IDS = tuple(
    c.id
    for c in CATEGORY_CATALOG
    if c.kind == "expense" and c.id not in ITEMIZED_CATEGORIES
)


@contextlib.contextmanager
def _moto_service():
    """Isolated moto DynamoDB (base + GSI1 + GSI2) and S3; yields services."""
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
        files = S3FileAdapter(s3, BUCKET)
        properties = PropertyService(repo, USER)
        transactions = TransactionService(repo, files)
        depreciation = DepreciationService(repo)
        report = ReportingService(transactions, depreciation, properties)
        yield report, properties, transactions, repo


_dates = st.dates(
    min_value=dt.date(TAX_YEAR, 1, 1), max_value=dt.date(TAX_YEAR, 12, 31)
)
_amounts = st.decimals(
    min_value=Decimal("0.01"),
    max_value=Decimal("100000.00"),
    places=2,
    allow_nan=False,
    allow_infinity=False,
)
_descriptions = st.text(min_size=1, max_size=20).filter(lambda s: s.strip())


@st.composite
def _row_specs(draw):
    """A non-empty list of (mode, category_id, date, amount, description, imported).

    ``mode`` is ``service`` (created via TransactionService, unmarked),
    ``marked`` (itemized=True stored in a non-itemized expense category) or
    ``legacy`` (stored item with no ``itemized`` attribute).
    """
    n = draw(st.integers(min_value=1, max_value=12))
    specs = []
    for _ in range(n):
        mode = draw(st.sampled_from(("service", "marked", "legacy")))
        if mode == "marked":
            category_id = draw(st.sampled_from(_NON_ITEMIZED_EXPENSE_IDS))
        else:
            # Favor repairs so unmarked rows in the itemized category are hit.
            category_id = draw(
                st.one_of(st.just("repairs"), st.sampled_from(_ALL_IDS))
            )
        category = _CATEGORY_BY_ID[category_id]
        description = (
            draw(_descriptions)
            if category.requires_description
            else draw(st.one_of(st.none(), _descriptions))
        )
        specs.append(
            (
                mode,
                category_id,
                draw(_dates),
                draw(_amounts),
                description,
                draw(st.booleans()),
            )
        )
    return specs


# Feature: itemized-expenses, Property 4: Rows outside the itemized rule sum as before
@settings(deadline=None, max_examples=120)
@given(specs=_row_specs())
def test_rows_outside_itemized_rule_sum_as_before(specs) -> None:
    """Each line total equals the plain sum of its rows.

    **Validates: Requirements 4.1, 4.5, 6.6, 11.7, 12.2**
    """
    with _moto_service() as (report, properties, transactions, repo):
        created = properties.create(
            PropertyInput(
                name="Unchanged Sum Subject",
                address_text="1 Plain Sum Way",
                property_type="single_family",
            )
        )
        assert created.is_ok, created.error
        pid = created.value.id

        expected: dict[int, Decimal] = {}
        for mode, category_id, day, amount, description, imported in specs:
            category = _CATEGORY_BY_ID[category_id]
            date_str = day.isoformat()
            if mode == "service":
                result = transactions.create(
                    TransactionInput(
                        property_id=pid,
                        date=date_str,
                        amount=amount,
                        type=category.kind,
                        category_id=category_id,
                        description=description,
                        imported=imported,
                    )
                )
                assert result.is_ok, result.error
            else:
                txn = Transaction(
                    id=str(uuid.uuid4()),
                    property_id=pid,
                    date=date_str,
                    amount=amount,
                    type=category.kind,
                    category_id=category_id,
                    schedule_e_line=category.schedule_e_line,
                    description=description.strip() if description else None,
                    created_at="2024-01-01T00:00:00Z",
                    updated_at="2024-01-01T00:00:00Z",
                    imported=imported,
                    itemized=(mode == "marked"),
                )
                item = transaction_to_item(txn, day)
                if mode == "legacy":
                    item.pop("itemized", None)
                    assert "itemized" not in item
                else:
                    assert item["itemized"] is True
                repo.put_item(item)
            expected[category.schedule_e_line] = (
                expected.get(category.schedule_e_line, Decimal("0.00")) + amount
            )

        result = report.report_for(pid, TAX_YEAR)
        assert result.is_ok, result.error
        rpt = result.value

        for report_line in rpt.lines:
            if report_line.line == DEPRECIATION_LINE:
                assert report_line.total == Decimal("0.00")
                continue
            want = expected.get(report_line.line, Decimal("0.00"))
            assert report_line.total == want, (
                f"line {report_line.line}: report {report_line.total} != "
                f"plain sum {want}"
            )
