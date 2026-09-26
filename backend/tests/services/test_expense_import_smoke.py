"""Task 13.2 verification: ExpenseImportService draft lifecycle.

A moto-backed smoke check confirming the import session + draft lifecycle works
end to end against a single-table DynamoDB, using a **stubbed transaction
creator** (so it does not depend on task 10.1's exact API) and a **stub parser**
(so it needs no PDF stack). It exercises the four behaviours the task calls out:

* ``create_session`` from representative parsed line items stages an
  ``ImportSession`` (status ``review``) plus one draft per line item and creates
  **no** transactions (Requirements 6.1, 6.3, 6.6);
* missing-field flagging is exact among {date, amount, category} plus a
  category-required description (Requirement 6.9);
* ``update_draft`` recomputes the missing-fields flag (Requirements 6.7, 6.9);
* ``confirm`` partitions drafts — complete drafts are converted, incomplete
  drafts are retained (Requirements 6.10, 6.11).

The Property 10/11/12 property-based tests (13.3-13.5) and the broader PDF-parse
unit tests (13.6) are separate tasks and are intentionally not implemented here.
"""

from __future__ import annotations

from decimal import Decimal

import boto3
import pytest
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


@pytest.fixture
def repo():
    with mock_aws():
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
        yield DynamoRepository(ddb, TABLE_NAME)


class StubTransactionCreator:
    """Records every TransactionInput and enforces just the Requirement 5 rules
    we need to prove partitioning: amount > 0 and required fields present.

    Success value is a tiny object exposing ``id`` (what the service extracts).
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


def _stub_parser(items):
    """Build a parser callable that returns the given line items as success."""
    return lambda _pdf_bytes: Result.success(list(items))


def _draft_rows(repo: DynamoRepository, session_id: str) -> list:
    return repo.query(keys.import_pk(session_id), sk_begins_with=keys.draft_list_prefix())


def _txn_rows(repo: DynamoRepository) -> list:
    """Any real transactions anywhere under the property partition."""
    return repo.query(
        keys.property_scoped_pk(PROPERTY_ID),
        sk_begins_with=keys.transaction_list_prefix(),
    )


# --- create_session: staging, no transactions (6.1, 6.3, 6.6) ---------------


def test_create_session_stages_drafts_and_creates_no_transactions(repo):
    creator = StubTransactionCreator()
    items = [
        ParsedLineItem(date="2024-03-01", amount=Decimal("120.00"),
                       description="Landscaping service"),
        ParsedLineItem(date="2024-04-15", amount=Decimal("300.00"),
                       description="Plumbing repair"),
    ]
    service = ExpenseImportService(
        repo, parser=_stub_parser(items), transaction_creator=creator
    )

    result = service.create_session(
        PROPERTY_ID, TAX_YEAR, pdf_bytes=PDF_BYTES, pdf_s3_key="imports/x.pdf",
        content_type="application/pdf",
    )

    assert result.is_ok
    session = result.value
    assert session.status == "review"
    assert session.property_id == PROPERTY_ID
    assert session.tax_year == TAX_YEAR

    drafts = service.list_drafts(session.id)
    assert len(drafts) == 2
    # Keyword heuristics mapped the descriptions to expense categories (6.4).
    by_desc = {d.description: d for d in drafts}
    assert by_desc["Landscaping service"].category_id == "cleaning-and-maintenance"
    assert by_desc["Plumbing repair"].category_id == "repairs"
    for d in drafts:
        assert d.type == "expense"

    # Invariant (6.6): staging only — no Transaction created and creator untouched.
    assert creator.calls == []
    assert _txn_rows(repo) == []


def test_non_pdf_upload_is_rejected_with_pdf_required(repo):
    service = ExpenseImportService(
        repo, parser=_stub_parser([]), transaction_creator=StubTransactionCreator()
    )
    result = service.create_session(
        PROPERTY_ID, TAX_YEAR, pdf_bytes=b"not a pdf", content_type="text/plain"
    )
    assert not result.is_ok
    assert result.error.kind == "validation"
    assert result.error.field == "file"
    assert "PDF" in result.error.message


def test_parse_failure_persists_failed_session_with_no_drafts(repo):
    def failing_parser(_pdf):
        return Result.failure("unavailable", "No transactions could be extracted.")

    service = ExpenseImportService(
        repo, parser=failing_parser, transaction_creator=StubTransactionCreator()
    )
    result = service.create_session(
        PROPERTY_ID, TAX_YEAR, pdf_bytes=PDF_BYTES, content_type="application/pdf"
    )
    assert not result.is_ok
    assert result.error.kind == "unavailable"
    # No drafts written anywhere; the failed session is persisted.
    sessions = repo.query(keys.property_scoped_pk(PROPERTY_ID), index_name="GSI1",
                          sk_begins_with=keys.IMPORT_PREFIX)
    assert len(sessions) == 1
    assert sessions[0]["status"] == "failed"
    assert _draft_rows(repo, sessions[0]["id"]) == []


# --- missing-field flagging is exact (6.9) ----------------------------------


def test_missing_fields_flagged_exactly(repo):
    items = [
        # Complete except category unknown -> only "category" missing.
        ParsedLineItem(date="2024-03-01", amount=Decimal("50.00"),
                       description="mystery charge"),
        # No date, no amount, no category-mappable text -> all three missing.
        ParsedLineItem(date=None, amount=None, description="???"),
    ]
    service = ExpenseImportService(
        repo, parser=_stub_parser(items), transaction_creator=StubTransactionCreator()
    )
    session = service.create_session(
        PROPERTY_ID, TAX_YEAR, pdf_bytes=PDF_BYTES, content_type="application/pdf"
    ).value

    drafts = {d.description: d for d in service.list_drafts(session.id)}
    assert drafts["mystery charge"].missing_fields == ["category"]
    assert drafts["???"].missing_fields == ["date", "amount", "category"]


def test_other_category_requires_description(repo):
    items = [ParsedLineItem(date="2024-03-01", amount=Decimal("50.00"), description="fee")]
    service = ExpenseImportService(
        repo, parser=_stub_parser(items), transaction_creator=StubTransactionCreator()
    )
    session = service.create_session(
        PROPERTY_ID, TAX_YEAR, pdf_bytes=PDF_BYTES, content_type="application/pdf"
    ).value
    draft = service.list_drafts(session.id)[0]

    # Assign Other (Line 19) and clear the description -> description flagged.
    updated = service.update_draft(
        session.id, draft.id, {"category_id": "other", "description": None}
    )
    assert updated.is_ok
    assert "description" in updated.value.missing_fields
    # Provide a description -> flag clears.
    cleared = service.update_draft(session.id, draft.id, {"description": "misc fee"})
    assert cleared.value.missing_fields == []


# --- update_draft recomputes the flag (6.7, 6.9) ----------------------------


def test_update_draft_recomputes_missing_fields(repo):
    items = [ParsedLineItem(date=None, amount=None, description="???")]
    service = ExpenseImportService(
        repo, parser=_stub_parser(items), transaction_creator=StubTransactionCreator()
    )
    session = service.create_session(
        PROPERTY_ID, TAX_YEAR, pdf_bytes=PDF_BYTES, content_type="application/pdf"
    ).value
    draft = service.list_drafts(session.id)[0]
    assert set(draft.missing_fields) == {"date", "amount", "category"}

    # Fill everything in -> flag clears; amount coerces from string to Decimal.
    result = service.update_draft(
        session.id, draft.id,
        {"date": "2024-05-01", "amount": "75.5", "category_id": "repairs"},
    )
    assert result.is_ok
    assert result.value.missing_fields == []
    assert result.value.amount == Decimal("75.50")

    # Re-read from the store confirms the recomputed flag was persisted.
    reread = {d.id: d for d in service.list_drafts(session.id)}[draft.id]
    assert reread.missing_fields == []
    assert reread.amount == Decimal("75.50")


def test_remove_draft_drops_it(repo):
    items = [
        ParsedLineItem(date="2024-01-01", amount=Decimal("10.00"), description="repair a"),
        ParsedLineItem(date="2024-01-02", amount=Decimal("20.00"), description="repair b"),
    ]
    service = ExpenseImportService(
        repo, parser=_stub_parser(items), transaction_creator=StubTransactionCreator()
    )
    session = service.create_session(
        PROPERTY_ID, TAX_YEAR, pdf_bytes=PDF_BYTES, content_type="application/pdf"
    ).value
    drafts = service.list_drafts(session.id)
    assert service.remove_draft(session.id, drafts[0].id).is_ok
    remaining = service.list_drafts(session.id)
    assert len(remaining) == 1
    assert remaining[0].id == drafts[1].id


# --- confirm partitioning: complete converted, incomplete retained (6.10, 6.11) ---


def test_confirm_partitions_complete_and_incomplete(repo):
    creator = StubTransactionCreator()
    items = [
        # Complete -> should convert.
        ParsedLineItem(date="2024-03-01", amount=Decimal("120.00"),
                       description="Landscaping service"),
        # Incomplete (no amount, unmappable) -> should be retained, not converted.
        ParsedLineItem(date="2024-04-01", amount=None, description="???"),
    ]
    service = ExpenseImportService(
        repo, parser=_stub_parser(items), transaction_creator=creator
    )
    session = service.create_session(
        PROPERTY_ID, TAX_YEAR, pdf_bytes=PDF_BYTES, content_type="application/pdf"
    ).value

    result = service.confirm(session.id)
    assert result.is_ok
    outcome = result.value

    # Exactly one converted (the complete draft), one rejected (the incomplete).
    assert outcome.converted_count == 1
    assert outcome.remaining_incomplete == 1
    assert len(creator.calls) == 1  # only the complete draft reached the creator
    created_txn = creator.calls[0]
    assert created_txn.property_id == PROPERTY_ID
    assert created_txn.amount == Decimal("120.00")
    assert created_txn.category_id == "cleaning-and-maintenance"

    # The incomplete draft is RETAINED (not silently dropped); the converted one
    # is removed so it cannot be converted twice.
    remaining = service.list_drafts(session.id)
    assert len(remaining) == 1
    assert remaining[0].description == "???"

    # Because a draft remains incomplete, the session stays in review.
    assert outcome.session.status == "review"
    assert service.get_session(session.id).value.status == "review"


def test_confirm_all_complete_marks_session_confirmed(repo):
    creator = StubTransactionCreator()
    items = [
        ParsedLineItem(date="2024-03-01", amount=Decimal("120.00"), description="repair a"),
        ParsedLineItem(date="2024-04-01", amount=Decimal("55.00"), description="repair b"),
    ]
    service = ExpenseImportService(
        repo, parser=_stub_parser(items), transaction_creator=creator
    )
    session = service.create_session(
        PROPERTY_ID, TAX_YEAR, pdf_bytes=PDF_BYTES, content_type="application/pdf"
    ).value

    result = service.confirm(session.id)
    assert result.is_ok
    assert result.value.converted_count == 2
    assert result.value.remaining_incomplete == 0
    assert service.list_drafts(session.id) == []
    assert service.get_session(session.id).value.status == "confirmed"


def test_confirm_rejects_complete_draft_failing_transaction_rules(repo):
    """A draft with all required fields present but amount <= 0 passes our
    completeness check yet fails Requirement 5 in the creator: it must be
    reported as rejected (with the field) and retained, not dropped (6.11)."""
    creator = StubTransactionCreator()
    # Amount is present (not missing) but non-positive.
    items = [ParsedLineItem(date="2024-03-01", amount=Decimal("0.00"), description="repair")]
    service = ExpenseImportService(
        repo, parser=_stub_parser(items), transaction_creator=creator
    )
    session = service.create_session(
        PROPERTY_ID, TAX_YEAR, pdf_bytes=PDF_BYTES, content_type="application/pdf"
    ).value
    draft = service.list_drafts(session.id)[0]
    assert draft.missing_fields == []  # complete by field-presence

    result = service.confirm(session.id)
    assert result.is_ok
    outcome = result.value
    assert outcome.converted_count == 0
    assert outcome.remaining_incomplete == 1
    assert outcome.rejected[0].field == "amount"
    # Retained, not dropped; session stays in review.
    assert len(service.list_drafts(session.id)) == 1
    assert service.get_session(session.id).value.status == "review"
