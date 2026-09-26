# Feature: logstead, Property 10: No transaction exists before draft confirmation
"""Property test for task 13.3 — no transaction exists before confirmation.

Property 10 (design.md): *For any* set of draft transactions parsed from an
expense summary, while the import session remains unconfirmed no ``Transaction``
is created for that import and the transaction store is unchanged.

Validates: Requirements 6.6

Strategy
--------
We generate a random list (0..k) of :class:`ParsedLineItem` with each of
``date`` / ``amount`` / ``description`` independently present or absent, feed
them through a **stub parser**, and run :meth:`ExpenseImportService.create_session`
(optionally applying a few random ``update_draft`` edits afterwards — the review
phase). A **stub transaction_creator** records every call and *would* create a
transaction. Before ``confirm()`` we assert:

  (a) the transaction_creator was NEVER called, and
  (b) there are NO real transaction rows under the property partition
      (query ``transaction_list_prefix`` on ``property_scoped_pk`` is empty).

Drafts may exist. As a positive control we then call ``confirm()`` and assert
that transactions (creator calls) only appear afterwards. A fresh moto-backed
DynamoDB table is created per example so state never leaks between iterations.
"""

from __future__ import annotations

from decimal import Decimal

import boto3
from hypothesis import HealthCheck, given, settings
from hypothesis import strategies as st
from moto import mock_aws

from logstead.adapters.pdf_parse import ParsedLineItem
from logstead.models.result import Result
from logstead.models.transaction import TransactionInput
from logstead.repository import keys
from logstead.repository.dynamo_repo import DynamoRepository
from logstead.services.expense_import import ExpenseImportService

TABLE_NAME = "Logstead"
REGION = "us-east-1"
PROPERTY_ID = "prop-1"
TAX_YEAR = 2024
PDF_BYTES = b"%PDF-1.4 fake body"  # magic bytes so the PDF-required check passes


class StubTransactionCreator:
    """Records every TransactionInput and *would* create a transaction.

    Enforces just enough of Requirement 5 (amount > 0) to behave like the real
    creator on confirm; the point of interest is that it is never *called* until
    ``confirm()`` runs.
    """

    def __init__(self) -> None:
        self.calls: list[TransactionInput] = []
        self._n = 0

    def __call__(self, data: TransactionInput) -> Result:
        self.calls.append(data)
        if data.amount is None or data.amount <= Decimal("0"):
            return Result.failure("validation", "Amount must be positive.", field="amount")
        self._n += 1
        return Result.success(type("Txn", (), {"id": f"txn-{self._n}"})())


def _make_table():
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


def _txn_rows(repo: DynamoRepository) -> list:
    """Any real transaction rows under the property partition."""
    return repo.query(
        keys.property_scoped_pk(PROPERTY_ID),
        sk_begins_with=keys.transaction_list_prefix(),
    )


# --- Strategies --------------------------------------------------------------

# Two-decimal, strictly positive amounts (or absent). Kept small/bounded so
# generation is fast and money stays realistic.
_amounts = st.one_of(
    st.none(),
    st.integers(min_value=1, max_value=1_000_000).map(
        lambda cents: Decimal(cents) / Decimal(100)
    ),
)

_dates = st.one_of(
    st.none(),
    st.dates(
        min_value=__import__("datetime").date(2000, 1, 1),
        max_value=__import__("datetime").date(2100, 12, 31),
    ).map(lambda d: d.isoformat()),
)

# Descriptions: absent, arbitrary text, or category-mappable keywords so drafts
# land in a mix of "complete" and "incomplete" states.
_descriptions = st.one_of(
    st.none(),
    st.text(max_size=40),
    st.sampled_from(
        ["Plumbing repair", "Landscaping service", "Insurance premium", "misc fee"]
    ),
)

_line_items = st.builds(
    ParsedLineItem, date=_dates, amount=_amounts, description=_descriptions
)

_line_item_lists = st.lists(_line_items, min_size=0, max_size=6)


@settings(
    deadline=None,
    max_examples=150,
    suppress_health_check=[HealthCheck.function_scoped_fixture],
)
@given(items=_line_item_lists, apply_edits=st.booleans())
def test_no_transaction_before_confirmation(items, apply_edits):
    """No Transaction exists (creator uncalled + store empty) until confirm()."""
    with mock_aws():
        repo = _make_table()
        creator = StubTransactionCreator()
        service = ExpenseImportService(
            repo,
            parser=lambda _pdf: Result.success(list(items)),
            transaction_creator=creator,
        )

        result = service.create_session(
            PROPERTY_ID,
            TAX_YEAR,
            pdf_bytes=PDF_BYTES,
            pdf_s3_key="imports/x.pdf",
            content_type="application/pdf",
        )
        # A non-empty parse always yields a review session; an empty parse still
        # succeeds here (the stub parser returns success), so create_session is ok.
        assert result.is_ok
        session = result.value

        drafts = service.list_drafts(session.id)
        assert len(drafts) == len(items)

        # The review phase: optionally edit some drafts (still pre-confirm).
        if apply_edits and drafts:
            for i, draft in enumerate(drafts):
                if i % 2 == 0:
                    service.update_draft(
                        session.id,
                        draft.id,
                        {"amount": "42.00", "category_id": "repairs"},
                    )

        # --- The invariant (Requirement 6.6), BEFORE confirm() --------------
        # (a) the transaction creator was never called during staging/review.
        assert creator.calls == []
        # (b) no real transaction rows exist under the property partition.
        assert _txn_rows(repo) == []
        # The session is not confirmed while we review.
        assert service.get_session(session.id).value.status != "confirmed"

        # --- Positive control: transactions only appear AFTER confirm() -----
        confirm_result = service.confirm(session.id)
        assert confirm_result.is_ok
        outcome = confirm_result.value

        # Any transaction creation happened here and only here: every converted
        # draft corresponds to a creator call made during confirm(), and the
        # number of created transactions never exceeds the calls made.
        assert outcome.converted_count == len(outcome.created_ids)
        assert outcome.converted_count <= len(creator.calls)
