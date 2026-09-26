# Feature: logstead, Property 11: Draft missing-fields flag is exact
"""Property test for task 13.4 — the draft missing-fields flag is exact.

Property 11 (design.md): *For any* draft transaction, the flagged missing-fields
set equals exactly the subset of required fields (date, amount, category) that
are unset.

Validates: Requirements 6.9

Strategy
--------
We generate a random list of :class:`ParsedLineItem` with each of ``date`` /
``amount`` / ``description`` independently present or absent (descriptions drawn
from a mix of category-mappable keywords, plain text, and ``None`` so the
service's keyword heuristic assigns a category to *some* drafts and not others).
The items are fed through a **stub parser** into
:meth:`ExpenseImportService.create_session`, which stages one draft per line item
and flags each with its missing required fields.

Because the service may *auto-assign* a category from the description
(Requirement 6.4), we do not assume whether "category" is present — instead we
recompute the expected missing set FROM THE DRAFT'S OWN persisted values:

    expected = {"date"        if date is blank/None}
             ∪ {"amount"      if amount is None}
             ∪ {"category"    if no category assigned}
             ∪ {"description" if the assigned category requires_description
                               and description is blank}

and assert ``set(draft.missing_fields)`` equals it exactly.

We then drive at least some drafts through :meth:`update_draft` (setting and
clearing fields, including assigning/clearing the description-requiring "other"
category) and re-assert that the recomputed, persisted flag is still exact —
against the draft's own values after the edit.

A fresh moto-backed DynamoDB table (with GSI1) is created per example so no
state leaks between iterations.
"""

from __future__ import annotations

import datetime
from decimal import Decimal

import boto3
from hypothesis import HealthCheck, given, settings
from hypothesis import strategies as st
from moto import mock_aws

from logstead.adapters.pdf_parse import ParsedLineItem
from logstead.models.result import Result
from logstead.models.transaction import TransactionInput
from logstead.repository.dynamo_repo import DynamoRepository
from logstead.services.category import CATEGORY_CATALOG
from logstead.services.expense_import import ExpenseImportService

TABLE_NAME = "Logstead"
REGION = "us-east-1"
PROPERTY_ID = "prop-1"
TAX_YEAR = 2024
PDF_BYTES = b"%PDF-1.4 fake body"  # magic bytes so the PDF-required check passes

# The set of category ids that require a description (Line 19 / "other").
_REQUIRES_DESCRIPTION = {c.id for c in CATEGORY_CATALOG if c.requires_description}
# Assignable category ids for use in update_draft edits.
_ASSIGNABLE_IDS = [c.id for c in CATEGORY_CATALOG]


class StubTransactionCreator:
    """A no-op creator; confirmation is not exercised by this property."""

    def __call__(self, data: TransactionInput) -> Result:
        return Result.success(type("Txn", (), {"id": "txn-1"})())


def _make_table() -> DynamoRepository:
    """Create a fresh single-table DynamoDB (with GSI1) and return the repo."""
    ddb = boto3.client("dynamodb", region_name=REGION)
    ddb.create_table(
        TableName=TABLE_NAME,
        AttributeDefinitions=[
            {"AttributeName": "PK", "AttributeType": "S"},
            {"AttributeName": "SK", "AttributeType": "S"},
            {"AttributeName": "GSI1PK", "AttributeType": "S"},
            {"AttributeName": "GSI1SK", "AttributeType": "S"},
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
        ],
        BillingMode="PAY_PER_REQUEST",
    )
    return DynamoRepository(ddb, TABLE_NAME)


def _is_blank(value) -> bool:
    """True when a text field is missing or whitespace-only."""
    return value is None or str(value).strip() == ""


def _expected_missing(date, amount, description, category_id) -> set[str]:
    """Compute the exact expected missing-fields set from a draft's own values.

    Required fields are date, amount, and category (Requirement 6.9); description
    is required only when the assigned category requires it (Line 19 / "other",
    Requirement 7.4).
    """
    expected: set[str] = set()
    if _is_blank(date):
        expected.add("date")
    if amount is None:
        expected.add("amount")
    if _is_blank(category_id):
        expected.add("category")
    elif category_id in _REQUIRES_DESCRIPTION and _is_blank(description):
        expected.add("description")
    return expected


# --- Strategies --------------------------------------------------------------

# Two-decimal, strictly positive amounts (or absent).
_amounts = st.one_of(
    st.none(),
    st.integers(min_value=1, max_value=1_000_000).map(
        lambda cents: Decimal(cents) / Decimal(100)
    ),
)

_dates = st.one_of(
    st.none(),
    st.dates(
        min_value=datetime.date(2000, 1, 1),
        max_value=datetime.date(2100, 12, 31),
    ).map(lambda d: d.isoformat()),
)

# Descriptions: absent, whitespace-only (still "blank"), arbitrary text, or
# keyword text that the service maps to a category — so drafts land in a mix of
# category-present and category-absent states, and some end up on "other".
_descriptions = st.one_of(
    st.none(),
    st.just("   "),  # whitespace-only counts as blank
    st.text(max_size=40),
    st.sampled_from(
        [
            "Plumbing repair",
            "Landscaping service",
            "Insurance premium",
            "Property management fee",
            "Advertising listing fee",
            "misc fee",
            "???",
        ]
    ),
)

_line_items = st.builds(
    ParsedLineItem, date=_dates, amount=_amounts, description=_descriptions
)

_line_item_lists = st.lists(_line_items, min_size=1, max_size=6)


@settings(
    deadline=None,
    max_examples=150,
    suppress_health_check=[HealthCheck.function_scoped_fixture],
)
@given(items=_line_item_lists, edit_seed=st.integers(min_value=0, max_value=6))
def test_missing_fields_flag_is_exact(items, edit_seed):
    """set(draft.missing_fields) equals exactly the unset required fields."""
    with mock_aws():
        repo = _make_table()
        service = ExpenseImportService(
            repo,
            parser=lambda _pdf: Result.success(list(items)),
            transaction_creator=StubTransactionCreator(),
        )

        result = service.create_session(
            PROPERTY_ID,
            TAX_YEAR,
            pdf_bytes=PDF_BYTES,
            pdf_s3_key="imports/x.pdf",
            content_type="application/pdf",
        )
        assert result.is_ok
        session = result.value

        drafts = service.list_drafts(session.id)
        assert len(drafts) == len(items)

        # --- Invariant after create_session: flag is exact -------------------
        # Compute the expected set from each draft's OWN persisted values so the
        # assertion is robust to the service's keyword auto-categorization.
        for draft in drafts:
            expected = _expected_missing(
                draft.date, draft.amount, draft.description, draft.category_id
            )
            assert set(draft.missing_fields) == expected, (
                f"stored flag {draft.missing_fields!r} != expected {expected!r} "
                f"for draft(date={draft.date!r}, amount={draft.amount!r}, "
                f"description={draft.description!r}, category={draft.category_id!r})"
            )

        # --- Drive some drafts through update_draft, re-assert exactness -----
        # Deterministically (per example) pick a subset of drafts and a mix of
        # edits: set/clear category (including "other" which needs a
        # description), set/clear date/amount/description. After each edit the
        # persisted flag must still be exact w.r.t. the draft's new values.
        edits = [
            {"category_id": "other", "description": None},   # requires desc -> flags it
            {"category_id": "other", "description": "misc"},  # desc present -> clears it
            {"category_id": None},                            # clear -> "category" missing
            {"category_id": "repairs", "date": None},         # clear date
            {"amount": None},                                 # clear amount
            {"date": "2024-06-01", "amount": "12.34"},        # fill date + amount
            {"category_id": "insurance", "description": None},  # non-req cat, no desc flag
        ]

        for offset, draft in enumerate(drafts):
            # Skip roughly half the drafts based on the per-example seed so we
            # exercise both edited and unedited drafts.
            if (offset + edit_seed) % 2 == 0:
                continue
            edit = edits[(offset + edit_seed) % len(edits)]
            updated = service.update_draft(session.id, draft.id, edit)
            assert updated.is_ok
            d = updated.value
            expected = _expected_missing(d.date, d.amount, d.description, d.category_id)
            assert set(d.missing_fields) == expected, (
                f"after edit {edit!r}: flag {d.missing_fields!r} != {expected!r}"
            )

            # And the recomputed flag was persisted: re-read from the store.
            reread = {x.id: x for x in service.list_drafts(session.id)}[d.id]
            reread_expected = _expected_missing(
                reread.date, reread.amount, reread.description, reread.category_id
            )
            assert set(reread.missing_fields) == reread_expected
