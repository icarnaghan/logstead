"""Task 13.6: fuller import-lifecycle happy path (Requirements 6.3, 6.12).

Where ``test_expense_import_smoke.py`` (task 13.2) drives the lifecycle with a
hand-built list of ``ParsedLineItem`` and a *stub* parser, this module runs the
**real** :func:`logstead.adapters.pdf_parse.parse_expense_summary` over crafted
expense-summary text (via an injected ``extract_text`` extractor, so no PDF
stack is needed) all the way through ``ExpenseImportService`` against a moto
DynamoDB and a stub transaction creator.

The point is a fuller end-to-end pass than the smoke test:

* a representative multi-row summary parses into drafts with the correct
  date/amount/description and best-effort category mapping (Requirements 6.3,
  6.4), staged with **exact** missing-field flags and **no** transactions
  created (Requirements 6.6, 6.9);
* an incomplete draft is completed via ``update_draft`` (Requirements 6.7, 6.9);
* ``confirm`` then converts every complete draft into a real transaction and
  marks the session confirmed (Requirements 6.10, 6.11);
* a summary that extracts to only header/footer noise yields a parse failure
  with a manual-entry message and stages no drafts (Requirement 6.12).

Money is asserted as ``Decimal`` throughout (Requirement 13.3).
"""

from __future__ import annotations

from decimal import Decimal

import boto3
import pytest
from moto import mock_aws

from logstead.adapters.pdf_parse import parse_expense_summary
from logstead.models.result import Result
from logstead.models.transaction import TransactionInput
from logstead.repository import keys
from logstead.repository.dynamo_repo import DynamoRepository
from logstead.services.expense_import import ExpenseImportService

TABLE_NAME = "Logstead"
REGION = "us-east-1"
PROPERTY_ID = "prop-lifecycle"
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
    """Records each TransactionInput and enforces the minimal Requirement 5
    rules confirmation relies on (amount > 0). Success value exposes ``id``."""

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


def _real_parser_over(text: str, *, page_count: int = 1):
    """A parser callable backed by the REAL adapter, fed crafted extractor text.

    Returns ``bytes -> Result[list[ParsedLineItem]]`` — the exact seam
    ``ExpenseImportService`` expects — but routes through
    ``parse_expense_summary`` with an injected ``extract_text`` so the whole
    date/amount/description extraction path runs for real without a PDF stack.
    """

    def extract(_pdf_bytes: bytes) -> tuple[str, int]:
        return text, page_count

    return lambda pdf_bytes: parse_expense_summary(
        pdf_bytes, extract_text=extract
    )


def _drafts_by_desc(service: ExpenseImportService, session_id: str) -> dict:
    return {d.description: d for d in service.list_drafts(session_id)}


# A representative property-manager expense summary. Rows mix date formats and
# amount notations, include an incomplete row (no amount) and a row whose
# description maps to no known category keyword. Header and footer noise here is
# rule/separator lines (and blanks), which the parser skips because they carry
# no alphanumeric text — leaving exactly the five real line items. (Header text
# that carries words would itself be kept as a description-only draft by the
# tolerant heuristic; that behaviour is exercised in
# ``test_word_header_rows_become_incomplete_drafts`` below.)
REPRESENTATIVE_SUMMARY = (
    "============================================\n"
    "01/15/2024  Landscaping service        $  150.00\n"
    "02/03/2024  Plumbing repair - kitchen   1,250.75\n"
    "2024-03-20  Property management fee    $   95.50\n"
    "04/10/2024  Annual fire inspection\n"            # incomplete: no amount
    "05/22/2024  Miscellaneous charge       $   42.00\n"  # unmappable -> no category
    "--------------------------------------------\n"
)


def _create_representative_session(repo, creator):
    service = ExpenseImportService(
        repo,
        parser=_real_parser_over(REPRESENTATIVE_SUMMARY),
        transaction_creator=creator,
    )
    result = service.create_session(
        PROPERTY_ID,
        TAX_YEAR,
        pdf_bytes=PDF_BYTES,
        pdf_s3_key="imports/summary.pdf",
        content_type="application/pdf",
    )
    return service, result


# --- create_session over the real parser (6.1, 6.3, 6.4, 6.6, 6.9) ----------


def test_real_parse_stages_drafts_with_correct_fields_and_no_transactions(repo):
    creator = StubTransactionCreator()
    service, result = _create_representative_session(repo, creator)

    assert result.is_ok
    session = result.value
    assert session.status == "review"
    assert session.property_id == PROPERTY_ID
    assert session.tax_year == TAX_YEAR
    assert session.pdf_s3_key == "imports/summary.pdf"

    drafts = _drafts_by_desc(service, session.id)

    # Five real line items extracted from the summary; header/caption/footer
    # noise was skipped (Requirement 6.3).
    assert len(drafts) == 5

    # Dates normalized to ISO, amounts are Decimals, mixed notations parsed.
    landscaping = drafts["Landscaping service"]
    assert landscaping.date == "2024-01-15"
    assert landscaping.amount == Decimal("150.00")
    assert isinstance(landscaping.amount, Decimal)
    # Keyword heuristic mapped it to cleaning-and-maintenance (Requirement 6.4).
    assert landscaping.category_id == "cleaning-and-maintenance"
    assert landscaping.missing_fields == []

    plumbing = drafts["Plumbing repair - kitchen"]
    assert plumbing.amount == Decimal("1250.75")  # thousands separator parsed
    assert plumbing.category_id == "repairs"
    assert plumbing.missing_fields == []

    mgmt = drafts["Property management fee"]
    assert mgmt.date == "2024-03-20"
    assert mgmt.amount == Decimal("95.50")
    assert mgmt.category_id == "management-fees"
    assert mgmt.missing_fields == []

    # Incomplete row: no amount was on the line, so amount is unset and the
    # draft is flagged for exactly that (plus category, which did not map).
    inspection = drafts["Annual fire inspection"]
    assert inspection.date == "2024-04-10"
    assert inspection.amount is None
    assert set(inspection.missing_fields) == {"amount", "category"}

    # Unmappable description: fields present but no category matched -> flagged
    # for exactly "category" (Requirement 6.9).
    misc = drafts["Miscellaneous charge"]
    assert misc.amount == Decimal("42.00")
    assert misc.category_id is None
    assert misc.missing_fields == ["category"]

    # Every staged draft is an expense; none carries an income category (6.4).
    assert all(d.type == "expense" for d in drafts.values())

    # Invariant (6.6): staging only — the creator was never called and no real
    # transaction exists under the property partition.
    assert creator.calls == []
    txns = repo.query(
        keys.property_scoped_pk(PROPERTY_ID),
        sk_begins_with=keys.transaction_list_prefix(),
    )
    assert txns == []


def test_word_header_rows_become_incomplete_drafts(repo):
    # The parser is deliberately tolerant (Requirement 6.3): a header/caption
    # row that carries words — not just a rule — is extracted as a
    # description-only line item rather than silently dropped. It surfaces as a
    # draft flagged missing date/amount/category so the user drops or edits it
    # during review. This documents that behaviour end-to-end.
    summary_with_word_header = (
        "2024 Annual Expense Summary\n"          # word header -> description-only
        "Date        Description        Amount\n"  # caption row -> description-only
        "01/15/2024  Landscaping service $150.00\n"  # a real, complete line item
    )
    creator = StubTransactionCreator()
    service = ExpenseImportService(
        repo,
        parser=_real_parser_over(summary_with_word_header),
        transaction_creator=creator,
    )
    session = service.create_session(
        PROPERTY_ID,
        TAX_YEAR,
        pdf_bytes=PDF_BYTES,
        content_type="application/pdf",
    ).value

    drafts = _drafts_by_desc(service, session.id)
    assert set(drafts) == {
        "2024 Annual Expense Summary",
        "Date Description Amount",
        "Landscaping service",
    }
    # The two word-header rows are description-only, so they are flagged missing
    # date, amount, and category (Requirement 6.9)...
    header = drafts["2024 Annual Expense Summary"]
    assert header.date is None and header.amount is None
    assert set(header.missing_fields) == {"date", "amount", "category"}
    # ...and the real line item is complete and mapped.
    real = drafts["Landscaping service"]
    assert real.amount == Decimal("150.00")
    assert real.category_id == "cleaning-and-maintenance"
    assert real.missing_fields == []

    # On confirm the two incomplete header rows are retained (never converted,
    # never dropped) and only the real line item converts (Requirement 6.11).
    outcome = service.confirm(session.id).value
    assert outcome.converted_count == 1
    assert outcome.remaining_incomplete == 2


# --- full lifecycle: complete the incomplete draft, then confirm all --------


def test_lifecycle_complete_incomplete_draft_then_confirm_converts_all(repo):
    creator = StubTransactionCreator()
    service, result = _create_representative_session(repo, creator)
    session = result.value

    drafts = _drafts_by_desc(service, session.id)

    # Complete the incomplete inspection draft: supply amount + category (6.7).
    inspection = drafts["Annual fire inspection"]
    updated = service.update_draft(
        session.id,
        inspection.id,
        {"amount": "225.00", "category_id": "repairs"},
    )
    assert updated.is_ok
    assert updated.value.amount == Decimal("225.00")
    assert updated.value.missing_fields == []  # flag recomputed and cleared

    # Assign a category to the previously unmappable misc charge too (6.7).
    misc = drafts["Miscellaneous charge"]
    assert service.update_draft(
        session.id, misc.id, {"category_id": "supplies"}
    ).value.missing_fields == []

    # Re-read from the store confirms edits persisted before confirm.
    reread = _drafts_by_desc(service, session.id)
    assert all(d.missing_fields == [] for d in reread.values())

    # Confirm: every draft is now complete, so all five convert and none is
    # rejected; the session is marked confirmed (Requirements 6.10, 6.11).
    outcome = service.confirm(session.id)
    assert outcome.is_ok
    assert outcome.value.converted_count == 5
    assert outcome.value.remaining_incomplete == 0
    assert len(creator.calls) == 5

    # Each created transaction input carried the property, an ISO date, a
    # positive Decimal amount, and a category (Requirement 6.10).
    for call in creator.calls:
        assert call.property_id == PROPERTY_ID
        assert call.type == "expense"
        assert isinstance(call.amount, Decimal) and call.amount > Decimal("0")
        assert call.category_id is not None

    # Converted drafts are removed; the session is confirmed and persisted.
    assert service.list_drafts(session.id) == []
    assert service.get_session(session.id).value.status == "confirmed"


# --- partial confirm: incomplete draft left untouched retains the session ----


def test_lifecycle_partial_confirm_retains_incomplete_draft(repo):
    creator = StubTransactionCreator()
    service, result = _create_representative_session(repo, creator)
    session = result.value

    # Do NOT complete the inspection draft. Assign a category to the misc charge
    # so only the one row with a missing amount stays incomplete.
    drafts = _drafts_by_desc(service, session.id)
    service.update_draft(
        session.id, drafts["Miscellaneous charge"].id, {"category_id": "supplies"}
    )

    outcome = service.confirm(session.id).value

    # Four complete drafts convert; the amount-less inspection row is retained
    # (never converted, never dropped) and reported as rejected (6.11).
    assert outcome.converted_count == 4
    assert outcome.remaining_incomplete == 1
    assert len(creator.calls) == 4

    remaining = service.list_drafts(session.id)
    assert len(remaining) == 1
    assert remaining[0].description == "Annual fire inspection"
    assert "amount" in remaining[0].missing_fields

    # A draft was left behind, so the session stays in review for follow-up.
    assert outcome.session.status == "review"
    assert service.get_session(session.id).value.status == "review"


# --- parse failure over the real parser stages no drafts (6.12) -------------


def test_noise_only_summary_fails_parse_and_stages_no_drafts(repo):
    # A summary that extracts to content-free rule/separator rows only yields
    # zero line items -> parse failure; the failed session is persisted and NO
    # drafts are written (Requirement 6.12).
    noise_only = (
        "==============================================\n"
        "----------------------------------------------\n"
        "   \n"
        "|||||||||||||\n"
    )
    creator = StubTransactionCreator()
    service = ExpenseImportService(
        repo,
        parser=_real_parser_over(noise_only),
        transaction_creator=creator,
    )

    result = service.create_session(
        PROPERTY_ID,
        TAX_YEAR,
        pdf_bytes=PDF_BYTES,
        pdf_s3_key="imports/empty.pdf",
        content_type="application/pdf",
    )

    assert not result.is_ok
    assert result.error.kind == "unavailable"
    assert "manually" in result.error.message.lower()

    # The failed session is persisted (auditability) with no drafts, and no
    # transaction was ever created.
    sessions = repo.query(
        keys.property_scoped_pk(PROPERTY_ID),
        index_name="GSI1",
        sk_begins_with=keys.IMPORT_PREFIX,
    )
    assert len(sessions) == 1
    assert sessions[0]["status"] == "failed"
    assert (
        repo.query(
            keys.import_pk(sessions[0]["id"]),
            sk_begins_with=keys.draft_list_prefix(),
        )
        == []
    )
    assert creator.calls == []
