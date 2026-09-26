"""Property 12: Confirmation partitions drafts into created and rejected.

Task 13.5. Property-based test (Hypothesis) validating that
``ExpenseImportService.confirm`` partitions an import session's drafts into
EXACTLY the complete drafts (converted into real transactions) and the
incomplete drafts (retained as drafts and reported in ``rejected``) — with
nothing silently dropped and nothing converted twice.

Validates: Requirements 6.10, 6.11.

Design source of the property text (design.md, Property 12):
    "For any set of reviewed drafts, confirming creates exactly one Transaction
    (associated with the selected property) for each draft satisfying the
    Requirement 5 validation rules, and rejects each remaining draft with a
    message identifying the failing field; the count of created transactions
    equals the count of valid drafts."

Approach
--------
* Generate a random list of ``ParsedLineItem`` mixing complete and incomplete
  line items (each independently gets/omits a date, an amount, and a
  category-mappable description).
* Create the session (drafts are staged; keyword heuristics may auto-assign a
  category, so completeness is NOT known from the source items alone).
* Optionally ``update_draft`` some drafts to force them into definitely-complete
  or definitely-incomplete states so both partitions are exercised.
* Compute the expected "complete" set from each draft's OWN persisted values
  (robust to auto-categorization) using the same rule the service uses: a draft
  is complete iff date, amount, and category are present, plus a description
  when the assigned category requires one (Other/Line 19).
* Confirm and assert the four partitioning invariants below.
"""

from __future__ import annotations

from decimal import Decimal

import boto3
import pytest
from hypothesis import given, settings
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

# Catalog lookups mirror the service's own completeness rule.
_CATALOG_BY_ID = {c.id: c for c in CATEGORY_CATALOG}
_ASSIGNABLE_EXPENSE_IDS = [c.id for c in CATEGORY_CATALOG if c.kind == "expense"]
# A description that the keyword heuristics map to a real expense category.
_MAPPABLE_DESCRIPTION = "Plumbing repair"  # -> "repairs"


def _make_table():
    """Create the single-table DynamoDB with GSI1 and return a repository."""
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


class RecordingTransactionCreator:
    """Stub creator that succeeds for valid inputs and records every call.

    Enforces just the Requirement 5 rules needed to reason about partitioning:
    a positive amount with the required fields present. Its success value
    exposes ``id`` (what the service extracts) and it retains each
    ``TransactionInput`` so the test can check the created transactions
    correspond exactly to the complete drafts.
    """

    def __init__(self) -> None:
        self.calls: list[TransactionInput] = []
        self._n = 0

    def __call__(self, data: TransactionInput) -> Result:
        self.calls.append(data)
        if data.amount is None or data.amount <= Decimal("0"):
            return Result.failure(
                "validation", "Amount must be positive.", field="amount"
            )
        self._n += 1
        return Result.success(type("Txn", (), {"id": f"txn-{self._n}"})())


def _stub_parser(items):
    return lambda _pdf_bytes: Result.success(list(items))


def _is_complete(draft) -> bool:
    """Completeness by a draft's OWN persisted values (service's rule).

    Complete iff date, amount, and category are present, plus a description when
    the assigned category requires one (Other/Line 19). Robust to whatever
    category auto-categorization assigned.
    """
    if not (draft.date and str(draft.date).strip()):
        return False
    if draft.amount is None:
        return False
    if not (draft.category_id and str(draft.category_id).strip()):
        return False
    category = _CATALOG_BY_ID.get(str(draft.category_id))
    if category is not None and category.requires_description:
        if not (draft.description and str(draft.description).strip()):
            return False
    return True


# --- Strategies --------------------------------------------------------------

_amounts = st.decimals(
    min_value=Decimal("0.01"),
    max_value=Decimal("99999.99"),
    places=2,
    allow_nan=False,
    allow_infinity=False,
)
_dates = st.dates()


@st.composite
def _line_items(draw):
    """A random mix of complete-ish and incomplete-ish parsed line items.

    Each item independently gets or omits a date, an amount, and a
    category-mappable description. The actual complete/incomplete partition is
    later computed from persisted draft values, so this strategy only needs to
    produce enough variety for both partitions to appear across examples.
    """
    n = draw(st.integers(min_value=1, max_value=6))
    items = []
    for _ in range(n):
        has_date = draw(st.booleans())
        has_amount = draw(st.booleans())
        mappable = draw(st.booleans())
        date = draw(_dates).isoformat() if has_date else None
        amount = draw(_amounts) if has_amount else None
        # A mappable description auto-assigns a category; otherwise leave it
        # unmappable (which also means the draft will miss "category").
        description = _MAPPABLE_DESCRIPTION if mappable else draw(
            st.sampled_from(["???", "mystery charge", "misc", ""])
        )
        items.append(
            ParsedLineItem(date=date, amount=amount, description=description or None)
        )
    return items


# A per-draft forcing instruction so both partitions are reliably populated:
# leave the draft as-is, force it complete, or force it incomplete.
_force = st.sampled_from(["leave", "complete", "incomplete"])


# --- The property ------------------------------------------------------------


# Feature: logstead, Property 12: Confirmation partitions drafts into created and rejected
@settings(deadline=None, max_examples=150)
@given(items=_line_items(), forcing=st.lists(_force, min_size=6, max_size=6))
def test_confirmation_partitions_complete_and_incomplete(items, forcing):
    with mock_aws():
        repo = _make_table()
        creator = RecordingTransactionCreator()
        service = ExpenseImportService(
            repo, parser=_stub_parser(items), transaction_creator=creator
        )

        session = service.create_session(
            PROPERTY_ID,
            TAX_YEAR,
            pdf_bytes=PDF_BYTES,
            pdf_s3_key="imports/x.pdf",
            content_type="application/pdf",
        ).value

        # Force some drafts into definitely-complete / definitely-incomplete
        # states so both partitions are populated across examples.
        drafts_before = service.list_drafts(session.id)
        for draft, force in zip(drafts_before, forcing):
            if force == "complete":
                service.update_draft(
                    session.id,
                    draft.id,
                    {
                        "date": "2024-06-15",
                        "amount": "125.00",
                        "category_id": "repairs",
                        "description": "forced complete",
                    },
                )
            elif force == "incomplete":
                # Clear the amount to guarantee an incomplete draft.
                service.update_draft(session.id, draft.id, {"amount": None})

        # Compute the expected partition from each draft's OWN persisted values
        # (robust to auto-categorization).
        persisted = service.list_drafts(session.id)
        expected_complete = {d.id for d in persisted if _is_complete(d)}
        expected_incomplete = {d.id for d in persisted if not _is_complete(d)}
        all_ids = {d.id for d in persisted}

        # Sanity: the two expected partitions cover every draft with no overlap.
        assert expected_complete | expected_incomplete == all_ids
        assert not (expected_complete & expected_incomplete)

        outcome = service.confirm(session.id).value

        # (a) converted_count == number of complete drafts, and the creator was
        #     invoked exactly that many times (only complete drafts reach it).
        assert outcome.converted_count == len(expected_complete)
        assert len(creator.calls) == len(expected_complete)

        # (b) The created transactions correspond exactly to the complete drafts:
        #     one per complete draft, each carrying that draft's persisted
        #     values and the selected property.
        complete_by_key = {
            (d.date, d.amount, d.category_id, d.description)
            for d in persisted
            if d.id in expected_complete
        }
        created_by_key = set()
        for call in creator.calls:
            assert call.property_id == PROPERTY_ID
            created_by_key.add(
                (call.date, call.amount, call.category_id, call.description)
            )
        assert created_by_key == complete_by_key

        # (c) Every incomplete draft REMAINS a draft (still listed) and appears
        #     in outcome.rejected — none dropped, none converted (Req 6.11).
        remaining_ids = {d.id for d in service.list_drafts(session.id)}
        assert remaining_ids == expected_incomplete
        rejected_ids = {r.draft_id for r in outcome.rejected}
        assert rejected_ids == expected_incomplete

        # (d) Converted + remaining accounts for all drafts (nothing lost).
        assert outcome.converted_count + len(remaining_ids) == len(all_ids)
        assert outcome.converted_count + outcome.remaining_incomplete == len(all_ids)

        # Session status reflects the partition: confirmed iff nothing remained.
        expected_status = "confirmed" if not expected_incomplete else "review"
        assert outcome.session.status == expected_status
