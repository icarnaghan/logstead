"""Transaction Service: income/expense CRUD, ordering, tax-year filtering, and
receipts (Requirements 5, 7).

A transaction is a single dated income or expense record associated with a
property. The service owns all the business rules from Requirement 5 (validation,
listing order, tax-year filtering, receipts) and the category-to-Schedule-E-line
recording from Requirement 7:

* :meth:`create` — validate the input (Requirements 5.1, 5.2, 5.3), resolve the
  chosen category and **record its Schedule E line** on the transaction
  (Requirement 7.3), require a description for the Other category (Line 19;
  Requirement 7.4), and persist the transaction with both its base-table sort key
  (inverted-date, for date-descending listing) and its GSI2 tax-year keys.
* :meth:`list_for_property` — return a property's transactions newest-first via
  the inverted-date sort key (Requirement 5.4); optionally scoped to a tax year
  via the GSI2 partition (Requirement 5.5).
* :meth:`get` / :meth:`update` / :meth:`delete` — read one, edit (re-validating
  and moving the sort key when the date changes, since the date is embedded in
  the key), and delete (Requirements 5.6, 5.7). Deleting a transaction also
  removes its receipt documents (metadata + S3 objects).
* :meth:`attach_receipt` / :meth:`list_receipts` / :meth:`delete_receipt` —
  store a receipt file in S3 via a pre-signed PUT URL and track a
  :class:`~logstead.models.transaction.Document` metadata item under the
  transaction (Requirement 5.8).

Money handling follows the repository contract: ``amount`` is a two-decimal
``Decimal`` in code and a two-decimal string in DynamoDB (the ``amount``
attribute is a default money attribute, so the repository serializes it).

Both collaborators — the :class:`~logstead.repository.dynamo_repo.DynamoRepository`
and the :class:`~logstead.adapters.s3_files.S3FileAdapter` — are injected so
tests can back them with ``moto`` and no live AWS call is ever made.
"""

from __future__ import annotations

import uuid
from dataclasses import dataclass, replace
from datetime import date, datetime, timezone
from decimal import Decimal
from typing import TYPE_CHECKING, Any

from logstead.adapters import s3_files
from logstead.models.category import ScheduleECategory
from logstead.models.result import Result
from logstead.models.transaction import (
    Document,
    Transaction,
    TransactionInput,
    TransactionType,
)
from logstead.repository import keys
from logstead.services.category import CATEGORY_CATALOG

if TYPE_CHECKING:
    from logstead.adapters.s3_files import S3FileAdapter
    from logstead.repository.dynamo_repo import DynamoRepository


__all__ = [
    "ReceiptUpload",
    "ReceiptWithUrl",
    "TransactionService",
    "category_by_id",
    "transaction_to_item",
    "document_to_item",
]

# The document-row marker inside a transaction's sort key namespace. Receipt
# rows live under ``TXN#<invDate>#<txnId>#DOC#<docId>``; base-table transaction
# listing must skip them so a listing never returns receipt metadata as if it
# were a transaction (Requirement 5.4).
_DOC_SK_MARKER = f"#{keys.DOC_PREFIX}"  # "#DOC#"


# --- Category lookup ---------------------------------------------------------

# Index the fixed catalog by id once, so ``create``/``update`` can resolve the
# chosen category (and thus its Schedule E line / requires-description flag)
# without a DynamoDB read. The catalog is static reference data (Requirement 7).
_CATEGORY_BY_ID: dict[str, ScheduleECategory] = {c.id: c for c in CATEGORY_CATALOG}


def category_by_id(category_id: str) -> ScheduleECategory | None:
    """Look up a Schedule E category by id, or ``None`` if unknown."""
    return _CATEGORY_BY_ID.get(category_id)


@dataclass(frozen=True)
class ReceiptUpload:
    """The result of :meth:`TransactionService.attach_receipt`.

    Attributes:
        upload_url: A pre-signed S3 **PUT** URL bound to the receipt's key and
            content type.
        document: The persisted :class:`Document` metadata.
    """

    upload_url: str
    document: Document


@dataclass(frozen=True)
class ReceiptWithUrl:
    """A stored receipt document paired with a pre-signed GET URL (5.8)."""

    document: Document
    download_url: str


class TransactionService:
    """Application service for income/expense transactions (Requirements 5, 7).

    Args:
        repo: The single-table DynamoDB repository.
        files: The S3 file adapter for receipt pre-signed URLs and object delete.
    """

    def __init__(self, repo: "DynamoRepository", files: "S3FileAdapter") -> None:
        self._repo = repo
        self._files = files

    # --- Create (Requirements 5.1, 5.2, 5.3, 7.3, 7.4) -----------------------

    def create(self, data: TransactionInput) -> Result[Transaction]:
        """Create a transaction after validating input and recording its line.

        Validation order (each surfaces a field-identifying ``validation``
        failure; Requirement 5.3):

        1. ``property_id``, ``date``, ``amount``, ``type``, ``category_id`` must
           all be present.
        2. ``date`` must be a valid ISO ``YYYY-MM-DD`` string.
        3. ``amount`` must be greater than zero (Requirement 5.2).
        4. ``type`` must be ``income`` or ``expense``.
        5. ``category_id`` must resolve to a known category (``not_found``).
        6. If the category requires a description (Other / Line 19), a non-blank
           description is required (Requirement 7.4).

        On success the transaction records the category's Schedule E line
        (Requirement 7.3) and is stored with the inverted-date base-table sort
        key **and** the GSI2 tax-year keys so both date-descending listing and
        tax-year queries work.
        """
        validated = self._validate(data)
        if not validated.is_ok:
            # Propagate the typed error unchanged.
            return Result.failure(
                validated.error.kind,
                validated.error.message,
                validated.error.field,
            )
        parsed, category = validated.value

        now = _now_iso()
        txn = Transaction(
            id=str(uuid.uuid4()),
            property_id=data.property_id,  # type: ignore[arg-type]
            date=data.date,  # type: ignore[arg-type]
            amount=parsed_amount(data.amount),
            type=data.type,  # type: ignore[arg-type]
            category_id=data.category_id,  # type: ignore[arg-type]
            schedule_e_line=category.schedule_e_line,
            description=_clean_description(data.description),
            created_at=now,
            updated_at=now,
        )
        self._repo.put_item(transaction_to_item(txn, parsed))
        return Result.success(txn)

    # --- Read one ------------------------------------------------------------

    def get(self, property_id: str, transaction_id: str) -> Result[Transaction]:
        """Fetch a single transaction, or ``not_found`` if it does not exist.

        The base-table sort key embeds the (inverted) date, which the caller
        does not know a priori, so this scans the property's transaction rows and
        matches on id.
        """
        found = self._find(property_id, transaction_id)
        if found is None:
            return Result.failure(
                "not_found", "Transaction not found.", field="transaction_id"
            )
        _sk, txn = found
        return Result.success(txn)

    # --- List (Requirements 5.4, 5.5) ----------------------------------------

    def list_for_property(
        self, property_id: str, tax_year: int | None = None
    ) -> Result[list[Transaction]]:
        """List a property's transactions, newest-first (Requirement 5.4).

        When ``tax_year`` is given, only transactions whose date falls in that
        year are returned, via the GSI2 tax-year partition (Requirement 5.5). In
        both cases the inverted-date sort key yields date-descending order
        directly from DynamoDB. Receipt ``#DOC#`` rows are excluded so a listing
        contains only transactions.
        """
        if tax_year is None:
            items = self._repo.query(
                keys.property_scoped_pk(property_id),
                sk_begins_with=keys.transaction_list_prefix(),
            )
        else:
            items = self._repo.query(
                keys.gsi2_year_pk(property_id, tax_year),
                sk_begins_with=keys.gsi2_transaction_prefix(),
                index_name="GSI2",
            )
        txns = [
            _from_item(item)
            for item in items
            if _DOC_SK_MARKER not in str(item.get("SK", ""))
        ]
        return Result.success(txns)

    # --- Update (Requirement 5.6) --------------------------------------------

    def update(
        self, property_id: str, transaction_id: str, data: TransactionInput
    ) -> Result[Transaction]:
        """Edit a transaction's fields, re-validating the whole input.

        The new field values are validated exactly like :meth:`create`. Because
        the transaction's date is embedded in its sort key, a date change means
        the item must move partitions within the property: the old row is deleted
        and a new row is written under the new inverted-date key (a delete + put,
        done atomically via ``transact_write``). Its id, created_at, and any
        attached receipts are preserved; ``updated_at`` is refreshed.
        """
        found = self._find(property_id, transaction_id)
        if found is None:
            return Result.failure(
                "not_found", "Transaction not found.", field="transaction_id"
            )
        old_sk, existing = found

        validated = self._validate(data)
        if not validated.is_ok:
            return Result.failure(
                validated.error.kind,
                validated.error.message,
                validated.error.field,
            )
        new_parsed, category = validated.value

        updated = replace(
            existing,
            property_id=data.property_id,  # type: ignore[arg-type]
            date=data.date,  # type: ignore[arg-type]
            amount=parsed_amount(data.amount),
            type=data.type,  # type: ignore[arg-type]
            category_id=data.category_id,  # type: ignore[arg-type]
            schedule_e_line=category.schedule_e_line,
            description=_clean_description(data.description),
            updated_at=_now_iso(),
        )
        new_item = transaction_to_item(updated, new_parsed)
        new_sk = new_item["SK"]

        if new_sk == old_sk:
            # Date unchanged (same partition + sort key): a plain overwrite.
            self._repo.put_item(new_item)
        else:
            # Date changed: the sort key moved. Delete the old row and write the
            # new one atomically so a transaction is never lost or duplicated.
            self._repo.transact_write(
                [
                    {"delete": {"pk": keys.property_scoped_pk(property_id), "sk": old_sk}},
                    {"put": new_item},
                ]
            )
        return Result.success(updated)

    # --- Delete (Requirement 5.7) --------------------------------------------

    def delete(self, property_id: str, transaction_id: str) -> Result[None]:
        """Delete a transaction and all of its receipt documents.

        Removes the transaction's base-table row plus every receipt ``#DOC#``
        metadata row co-located under it, and deletes each receipt's S3 object.
        ``not_found`` if the transaction does not exist.
        """
        found = self._find(property_id, transaction_id)
        if found is None:
            return Result.failure(
                "not_found", "Transaction not found.", field="transaction_id"
            )
        txn_sk, txn = found
        pk = keys.property_scoped_pk(property_id)

        # Remove receipt objects from S3, then delete the txn row and all its
        # document rows atomically.
        receipts = self._receipt_items(property_id, txn)
        for item in receipts:
            self._files.delete_object(str(item["s3Key"]))

        actions: list[dict[str, Any]] = [{"delete": {"pk": pk, "sk": txn_sk}}]
        for item in receipts:
            actions.append({"delete": {"pk": pk, "sk": str(item["SK"])}})
        self._repo.transact_write(actions)
        return Result.success(None)

    # --- Receipts (Requirement 5.8) ------------------------------------------

    def attach_receipt(
        self,
        property_id: str,
        transaction_id: str,
        filename: str,
        content_type: str,
    ) -> Result[ReceiptUpload]:
        """Attach a receipt to a transaction via a pre-signed S3 PUT URL.

        Resolves the transaction (``not_found`` if unknown), builds a namespaced
        receipt S3 key, issues a pre-signed PUT URL bound to that key + content
        type, and persists a :class:`Document` metadata row co-located under the
        transaction (Requirement 5.8).
        """
        found = self._find(property_id, transaction_id)
        if found is None:
            return Result.failure(
                "not_found", "Transaction not found.", field="transaction_id"
            )
        _sk, txn = found

        clean_name = str(filename).strip()
        if not clean_name:
            return Result.failure(
                "validation", "A filename is required.", field="filename"
            )
        clean_type = str(content_type).strip()
        if not clean_type:
            return Result.failure(
                "validation", "A content type is required.", field="content_type"
            )

        doc_id = str(uuid.uuid4())
        # Namespace by doc id so distinct receipts never collide even with equal
        # filenames: receipts/<txnId>/<docId>/<name>.
        s3_key = s3_files.receipt_key(transaction_id, f"{doc_id}/{clean_name}")
        document = Document(
            id=doc_id,
            property_id=property_id,
            transaction_id=transaction_id,
            s3_key=s3_key,
            content_type=clean_type,
            original_filename=clean_name,
            uploaded_at=_now_iso(),
        )
        self._repo.put_item(document_to_item(document, txn.date))
        upload_url = self._files.presigned_put_url(s3_key, clean_type)
        return Result.success(
            ReceiptUpload(upload_url=upload_url, document=document)
        )

    def list_receipts(
        self, property_id: str, transaction_id: str
    ) -> Result[list[ReceiptWithUrl]]:
        """List a transaction's receipts, each with a pre-signed GET URL.

        ``not_found`` if the transaction does not exist; an empty list when it
        exists but has no receipts.
        """
        found = self._find(property_id, transaction_id)
        if found is None:
            return Result.failure(
                "not_found", "Transaction not found.", field="transaction_id"
            )
        _sk, txn = found
        receipts = [
            ReceiptWithUrl(
                document=_document_from_item(item),
                download_url=self._files.presigned_get_url(str(item["s3Key"])),
            )
            for item in self._receipt_items(property_id, txn)
        ]
        return Result.success(receipts)

    def delete_receipt(
        self, property_id: str, transaction_id: str, document_id: str
    ) -> Result[None]:
        """Delete one receipt: its S3 object and its metadata row.

        ``not_found`` if the transaction or the receipt does not exist.
        """
        found = self._find(property_id, transaction_id)
        if found is None:
            return Result.failure(
                "not_found", "Transaction not found.", field="transaction_id"
            )
        _sk, txn = found

        for item in self._receipt_items(property_id, txn):
            if str(item["id"]) == document_id:
                self._files.delete_object(str(item["s3Key"]))
                self._repo.delete_item(
                    keys.property_scoped_pk(property_id), str(item["SK"])
                )
                return Result.success(None)
        return Result.failure(
            "not_found", "Receipt not found.", field="document_id"
        )

    # --- Internals -----------------------------------------------------------

    def _validate(
        self, data: TransactionInput
    ) -> Result[tuple[date, ScheduleECategory]]:
        """Validate a transaction input; return the parsed date + category.

        Surfaces field-identifying validation failures (Requirements 5.2, 5.3,
        7.4) and a ``not_found`` for an unknown category id.
        """
        if not data.property_id:
            return Result.failure(
                "validation", "A property is required.", field="property_id"
            )
        if not data.date:
            return Result.failure(
                "validation", "A date is required.", field="date"
            )
        if data.amount is None:
            return Result.failure(
                "validation", "An amount is required.", field="amount"
            )
        if not data.category_id:
            return Result.failure(
                "validation", "A category is required.", field="category_id"
            )

        parsed_date = _parse_date(data.date)
        if parsed_date is None:
            return Result.failure(
                "validation",
                "Date must be a valid ISO date (YYYY-MM-DD).",
                field="date",
            )

        if parsed_amount(data.amount) <= Decimal("0.00"):
            return Result.failure(
                "validation",
                "Amount must be greater than zero.",
                field="amount",
            )

        if data.type not in ("income", "expense"):
            return Result.failure(
                "validation",
                "Type must be 'income' or 'expense'.",
                field="type",
            )

        category = category_by_id(data.category_id)
        if category is None:
            return Result.failure(
                "not_found",
                f"Unknown category: {data.category_id!r}.",
                field="category_id",
            )

        if category.requires_description and not _clean_description(data.description):
            return Result.failure(
                "validation",
                "A description is required for the Other category.",
                field="description",
            )

        return Result.success((parsed_date, category))

    def _find(
        self, property_id: str, transaction_id: str
    ) -> tuple[str, Transaction] | None:
        """Locate a transaction by id within a property; return (SK, Transaction).

        The date-embedded sort key is unknown to the caller, so this scans the
        property's transaction rows (skipping ``#DOC#`` rows) and matches on id.
        """
        items = self._repo.query(
            keys.property_scoped_pk(property_id),
            sk_begins_with=keys.transaction_list_prefix(),
        )
        for item in items:
            sk = str(item.get("SK", ""))
            if _DOC_SK_MARKER in sk:
                continue
            if str(item.get("id")) == transaction_id:
                return sk, _from_item(item)
        return None

    def _receipt_items(
        self, property_id: str, txn: Transaction
    ) -> list[dict[str, Any]]:
        """Return the raw ``#DOC#`` metadata items for a transaction."""
        d = _parse_date(txn.date)
        prefix = f"{keys.transaction_sk(d, txn.id)}#{keys.DOC_PREFIX}"
        return self._repo.query(
            keys.property_scoped_pk(property_id), sk_begins_with=prefix
        )


# --- Amount parsing ----------------------------------------------------------

def parsed_amount(amount: Decimal | None) -> Decimal:
    """Quantize an amount to two decimals for comparison/storage.

    ``None`` is treated as zero so validation (amount > 0) rejects it; callers
    only reach storage after validation has confirmed a positive amount.
    """
    if amount is None:
        return Decimal("0.00")
    from logstead.util.money import to_money

    return to_money(amount)


# --- Date parsing ------------------------------------------------------------

def _parse_date(value: str | None) -> date | None:
    """Parse an ISO ``YYYY-MM-DD`` string into a ``date``, or ``None``."""
    if not value:
        return None
    try:
        return date.fromisoformat(value)
    except (ValueError, TypeError):
        return None


def _clean_description(description: str | None) -> str | None:
    """Trim a description; blank/whitespace-only becomes ``None``."""
    if description is None:
        return None
    text = description.strip()
    return text or None


# --- Serialization boundary --------------------------------------------------
#
# Transaction items use the design's camelCase attribute names and carry the
# GSI2 tax-year keys so tax-year queries work. ``amount`` is a default money
# attribute (stored as a two-decimal string by the repository).

def transaction_to_item(txn: Transaction, txn_date: date) -> dict[str, Any]:
    """Render a :class:`Transaction` as its DynamoDB item (with GSI2 keys).

    A module-level pure function of the transaction plus its parsed date: it
    emits the base-table inverted-date sort key **and** the GSI2 tax-year keys.
    Ids and timestamps are taken verbatim from ``txn`` so a restore can preserve
    the original values rather than generating fresh ones.
    """
    return {
        "PK": keys.property_scoped_pk(txn.property_id),
        "SK": keys.transaction_sk(txn_date, txn.id),
        "GSI2PK": keys.gsi2_year_pk(txn.property_id, txn_date.year),
        "GSI2SK": keys.gsi2_transaction_sk(txn_date, txn.id),
        "id": txn.id,
        "propertyId": txn.property_id,
        "date": txn.date,
        "amount": txn.amount,
        "type": txn.type,
        "categoryId": txn.category_id,
        "scheduleELine": txn.schedule_e_line,
        "description": txn.description,
        "createdAt": txn.created_at,
        "updatedAt": txn.updated_at,
    }


def _from_item(item: dict[str, Any]) -> Transaction:
    """Reconstruct a :class:`Transaction` from a stored item."""
    return Transaction(
        id=str(item["id"]),
        property_id=str(item["propertyId"]),
        date=str(item["date"]),
        amount=item["amount"],  # already a Decimal (money attr)
        type=_as_type(item["type"]),
        category_id=str(item["categoryId"]),
        schedule_e_line=int(item["scheduleELine"]),
        description=(
            str(item["description"]) if item.get("description") is not None else None
        ),
        created_at=(
            str(item["createdAt"]) if item.get("createdAt") is not None else None
        ),
        updated_at=(
            str(item["updatedAt"]) if item.get("updatedAt") is not None else None
        ),
    )


def document_to_item(document: Document, txn_date_str: str) -> dict[str, Any]:
    """Render a receipt :class:`Document` as its DynamoDB item.

    Co-located under its transaction: ``SK=TXN#<invDate>#<txnId>#DOC#<docId>``.
    """
    d = _parse_date(txn_date_str)
    return {
        "PK": keys.property_scoped_pk(document.property_id),
        "SK": keys.document_sk(d, document.transaction_id, document.id),
        "id": document.id,
        "propertyId": document.property_id,
        "transactionId": document.transaction_id,
        "s3Key": document.s3_key,
        "contentType": document.content_type,
        "originalFilename": document.original_filename,
        "uploadedAt": document.uploaded_at,
    }


def _document_from_item(item: dict[str, Any]) -> Document:
    """Reconstruct a receipt :class:`Document` from a stored item."""
    return Document(
        id=str(item["id"]),
        property_id=str(item["propertyId"]),
        transaction_id=str(item["transactionId"]),
        s3_key=str(item["s3Key"]),
        content_type=str(item["contentType"]),
        original_filename=str(item["originalFilename"]),
        uploaded_at=(
            str(item["uploadedAt"]) if item.get("uploadedAt") is not None else None
        ),
    )


def _as_type(value: Any) -> TransactionType:
    """Narrow a stored type string to the ``TransactionType`` literal."""
    return "income" if str(value) == "income" else "expense"


def _now_iso() -> str:
    """Current UTC time as an ISO-8601 string."""
    return datetime.now(timezone.utc).isoformat()
