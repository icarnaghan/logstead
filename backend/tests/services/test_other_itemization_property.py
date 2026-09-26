"""Property-based test: Line 19 "Other" expenses are itemized and reconcile.

Design Property 23 (Requirement 10.5): *for any* set of Other-category
transactions in a report, each appears in the Line 19 itemization with its
description and amount, and the itemized amounts sum to the Line 19 total.

``ReportingService.report_for`` (``services/report.py``) walks a property's
in-year transactions. Each transaction assigned the Other category (id
``"other"``, Schedule E ``OTHER_LINE == 19``, ``requires_description``)
contributes one :class:`OtherItem` (``description`` + ``amount``) to
``report.other_items`` and also accumulates onto ``report.line(19)``. This test
drives that behaviour universally.

Each example generates a random set of transactions for one freshly created
property within a single tax year: **several** Other-category transactions --
each with a non-blank description and a positive two-decimal amount -- plus some
non-Other transactions (income and other expense lines) as noise. It then calls
``report_for`` and asserts:

* (a) ``report.other_items`` has exactly one entry per created Other-category
  transaction (the counts match);
* (b) the multiset of ``(description, amount)`` across ``other_items`` equals
  the multiset of ``(description, amount)`` of the created Other transactions --
  descriptions can repeat, so a multiset (not a set) comparison is used;
* (c) the sum of the ``other_items`` amounts equals ``report.line(19).total``
  exactly, as a ``Decimal``.

Line 18 (Depreciation) is fed from schedules rather than transactions and is
irrelevant to itemization, so no depreciable assets are provisioned. Each
Hypothesis example provisions its own moto-backed single-table DynamoDB (base +
GSI1 for the property meta mirror + GSI2 for the tax-year partition the report
reads through) plus an S3 bucket needed to construct the ``S3FileAdapter``,
mirroring the fixture pattern in ``test_report.py``. Per-example provisioning is
not instantaneous, so the deadline is disabled; the example count is held at
>= 100.
"""

from __future__ import annotations

import contextlib
import datetime as dt
from collections import Counter
from decimal import Decimal

import boto3
from hypothesis import given, settings
from hypothesis import strategies as st
from moto import mock_aws

from logstead.adapters.s3_files import S3FileAdapter
from logstead.models.property import PropertyInput
from logstead.models.transaction import TransactionInput
from logstead.repository.dynamo_repo import DynamoRepository
from logstead.services.category import CATEGORY_CATALOG
from logstead.services.depreciation import DepreciationService
from logstead.services.property import PropertyService
from logstead.services.report import OTHER_LINE, ReportingService
from logstead.services.transaction import TransactionService

TABLE_NAME = "Logstead"
BUCKET = "logstead-files-test"
REGION = "us-east-1"
USER = "user-abc"
TAX_YEAR = 2024
OTHER_CATEGORY_ID = "other"

# Non-Other assignable categories, split by kind so a transaction's ``type`` can
# be derived from its category and creation always succeeds. None of these
# require a description.
_CATEGORY_BY_ID = {c.id: c for c in CATEGORY_CATALOG}
_NON_OTHER_IDS = tuple(
    c.id
    for c in CATEGORY_CATALOG
    if c.id != OTHER_CATEGORY_ID and not c.requires_description
)


@contextlib.contextmanager
def _moto_service():
    """Provision an isolated moto DynamoDB (base + GSI1 + GSI2) and S3 bucket.

    Yields the composed ``(ReportingService, PropertyService, TransactionService)``
    bound to freshly created resources so each Hypothesis example runs against a
    clean store. GSI1 is required by ``PropertyService.create`` (property meta
    mirror); GSI2 is the tax-year partition the report reads transactions
    through.
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
        files = S3FileAdapter(s3, BUCKET)
        properties = PropertyService(repo, USER)
        transactions = TransactionService(repo, files)
        depreciation = DepreciationService(repo)
        report = ReportingService(transactions, depreciation, properties)
        yield report, properties, transactions


# --- Strategies --------------------------------------------------------------
#
# Every transaction falls within the single target tax year, so all are in scope
# for ``report_for(pid, TAX_YEAR)``.
_dates_in_year = st.dates(
    min_value=dt.date(TAX_YEAR, 1, 1), max_value=dt.date(TAX_YEAR, 12, 31)
).map(lambda d: d.isoformat())

# Positive two-decimal amounts, so the amount>0 rule always holds. Capped so a
# handful of transactions never overflow two-decimal money semantics.
_amounts = st.decimals(
    min_value=Decimal("0.01"),
    max_value=Decimal("100000.00"),
    places=2,
    allow_nan=False,
    allow_infinity=False,
)

# Non-blank Other-expense descriptions. Descriptions may repeat across items, so
# downstream comparison is a multiset. ``strip()`` keeps them genuinely
# non-blank to satisfy the Other-requires-description rule (Requirement 7.5).
_descriptions = st.text(min_size=1, max_size=25).filter(lambda s: s.strip())


@st.composite
def _scenario(draw):
    """Draw ``(other_specs, noise_specs)`` for one property in the tax year.

    ``other_specs`` is a **non-empty** list of ``(description, amount)`` for
    Other-category transactions -- several, so the itemization carries multiple
    (and sometimes duplicate) entries. ``noise_specs`` is a possibly-empty list
    of ``(category_id, amount)`` for non-Other transactions whose presence must
    not leak into the Line 19 itemization.
    """
    other_specs = draw(
        st.lists(
            st.tuples(_descriptions, _amounts),
            min_size=2,
            max_size=8,
        )
    )
    noise_specs = draw(
        st.lists(
            st.tuples(st.sampled_from(_NON_OTHER_IDS), _amounts),
            min_size=0,
            max_size=6,
        )
    )
    return other_specs, noise_specs


# Feature: logstead, Property 23: Other expenses are itemized and reconcile
@settings(deadline=None, max_examples=100)
@given(scenario=_scenario())
def test_other_expenses_are_itemized_and_reconcile(
    scenario: tuple[list[tuple[str, Decimal]], list[tuple[str, Decimal]]],
) -> None:
    """Each Other transaction is itemized once; items reconcile to Line 19.

    Validates: Requirements 10.5
    """
    other_specs, noise_specs = scenario

    with _moto_service() as (report, properties, transactions):
        created = properties.create(
            PropertyInput(
                name="Itemization Subject",
                address_text="1 Itemization Way",
                property_type="single_family",
            )
        )
        assert created.is_ok, created.error
        pid = created.value.id

        # Create the Other-category transactions, tracking the expected
        # (description, amount) multiset independently of the service. The
        # service trims descriptions on create (``_clean_description`` ->
        # ``str.strip()``), so the itemized description is the trimmed form; the
        # expectation mirrors that normalization. The generator already keeps
        # descriptions non-blank after stripping, so no entry collapses away.
        expected_items: Counter[tuple[str, Decimal]] = Counter()
        for description, amount in other_specs:
            result = transactions.create(
                TransactionInput(
                    property_id=pid,
                    date="2024-06-15",
                    amount=amount,
                    type="expense",
                    category_id=OTHER_CATEGORY_ID,
                    description=description,
                )
            )
            assert result.is_ok, result.error
            expected_items[(description.strip(), amount)] += 1

        # Non-Other noise: income and other expense lines that must not appear
        # in the Line 19 itemization.
        for category_id, amount in noise_specs:
            category = _CATEGORY_BY_ID[category_id]
            result = transactions.create(
                TransactionInput(
                    property_id=pid,
                    date="2024-03-10",
                    amount=amount,
                    type=category.kind,  # "income" | "expense"
                    category_id=category_id,
                    description=None,
                )
            )
            assert result.is_ok, result.error

        result = report.report_for(pid, TAX_YEAR)
        assert result.is_ok, result.error
        rpt = result.value

        # (a) One itemized entry per created Other-category transaction.
        assert len(rpt.other_items) == len(other_specs)

        # (b) The multiset of (description, amount) in other_items equals the
        #     created Other transactions' (description, amount). A multiset
        #     handles duplicate descriptions/amounts correctly.
        actual_items = Counter(
            (item.description, item.amount) for item in rpt.other_items
        )
        assert actual_items == expected_items

        # (c) The itemized amounts sum to the Line 19 total, exactly (Decimal).
        itemized_sum = sum(
            (item.amount for item in rpt.other_items), Decimal("0.00")
        )
        assert itemized_sum == rpt.line(OTHER_LINE).total
