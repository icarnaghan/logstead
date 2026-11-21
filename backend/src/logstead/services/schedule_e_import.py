"""Schedule E Import service: synthesize backing transactions from entered
line amounts (Requirements 1-11).

Logstead **derives** Schedule E reports on demand and never stores a report, so
"importing a Schedule E" means **synthesizing the backing transactions** that
reproduce the line totals the user enters. This service owns that synthesis for
one or more ``(Property, Tax_Year)`` pairs in a single multi-property pass (the
analog of a real IRS Schedule E Part I page with columns A/B/C).

The guiding principle (design "Overview"): a ``Summary_Transaction`` is an
**ordinary, marked transaction**. It is stored under the exact same
per-property / per-tax-year keys as a user-tracked transaction (via
:class:`~logstead.services.transaction.TransactionService`), carries the same
validated shape (amount > 0, a recorded ``schedule_e_line``, a Line 19
description), and is therefore consumed by the existing reporting path with
**zero change to report computation** — the only reporting change (elsewhere) is
surfacing the imported marker.

Responsibilities
----------------
* :meth:`import_schedule_e` — validate the **entire** submission all-or-nothing
  (no write unless every check passes; Req 9), then for each entry: resolve or
  inline-create the property (Req 2), delete the prior imported set for that
  ``(Property, Tax_Year)`` (replace-on-reimport; Req 8), and write one
  ``Summary_Transaction`` per non-zero line (Req 6). Depreciation / Line 18 is
  never accepted or written (Req 5).
* :meth:`remove_imported_set` — the explicit undo that removes only the imported
  rows for one ``(Property, Tax_Year)``, never touching user-tracked rows (Req 8
  companion).

Collaborators are constructed from the repo + user (mirroring the router's
per-request wiring): a user-scoped :class:`PropertyService` for ownership checks
and inline creation, and a :class:`TransactionService` for synthesis and for
listing a property's in-year rows. ``TransactionService`` needs an S3 adapter
only for receipts, which synthesis never uses; synthesized transactions never
have receipts.

Every operation is scoped to the authenticated user (Req 10): the service only
acts through a user-scoped ``PropertyService``, so a ``(Property, Tax_Year)``
not owned by the user resolves to ``not_found`` before any write.
"""

from __future__ import annotations

from datetime import date
from decimal import Decimal
from typing import TYPE_CHECKING

from logstead.adapters.s3_files import S3FileAdapter
from logstead.models.category import ScheduleECategory
from logstead.models.result import Result
from logstead.models.schedule_e_import import (
    EntryOutcome,
    ImportOutcome,
    ImportSubmission,
    PropertyEntryInput,
    RemoveOutcome,
)
from logstead.models.transaction import Transaction, TransactionInput
from logstead.models.user import UserContext
from logstead.repository import keys
from logstead.services.auth import user_id_of
from logstead.services.category import CATEGORY_CATALOG
from logstead.services.property import PropertyService
from logstead.services.transaction import TransactionService
from logstead.util.money import to_money

if TYPE_CHECKING:
    from logstead.repository.dynamo_repo import DynamoRepository


__all__ = ["ImportService"]


# --- Line → category index (built once from the catalog) ---------------------
#
# The catalog is the single source of truth for which Schedule E line maps to
# which assignable category (and thus income/expense kind + requires-description).
# Line 18 (Depreciation) is intentionally absent from the catalog, so it can be
# neither mapped nor synthesized (Req 5.1); a defensive validation check rejects
# any ``schedule_e_line == 18`` in the payload.
_CATEGORY_BY_LINE: dict[int, ScheduleECategory] = {
    c.schedule_e_line: c for c in CATEGORY_CATALOG
}

# The set of Schedule E lines a submission may carry: income 3-4, expense 5-17,
# and Line 19 Other. Exactly the lines present in the catalog (18 excluded).
_ALLOWED_LINES: frozenset[int] = frozenset(_CATEGORY_BY_LINE)

# Default description applied to a Line 19 (Other) synthesized transaction when
# the entry provides none, so the Line 19 requires-description rule is satisfied
# (Req 6.6).
_DEFAULT_LINE_19_DESCRIPTION = "Imported Schedule E Other"

_ZERO = Decimal("0.00")

# DynamoDB TransactWriteItems caps a single transaction at 100 actions.
_TRANSACT_LIMIT = 100


# --- Human-readable line names (for validation messages) ---------------------


def _line_label(line: int) -> str:
    """A short human-readable name for a Schedule E line, for error messages."""
    category = _CATEGORY_BY_LINE.get(line)
    if category is not None:
        return f"Line {line} ({category.label})"
    return f"Line {line}"


class ImportService:
    """Synthesize/replace imported Schedule E transactions, scoped to one user.

    Args:
        repo: The single-table DynamoDB repository (used directly only for the
            set-delete during replace-on-reimport / remove).
        user: The authenticated user (:class:`UserContext`) or raw user id. All
            work is scoped to this user via the collaborators below.
        files: Optional S3 adapter for the ``TransactionService`` collaborator.
            Synthesis never touches S3 (no receipts), so when omitted a thin
            no-bucket adapter is constructed; the router passes the real adapter
            exactly like the other transaction routes.
    """

    def __init__(
        self,
        repo: "DynamoRepository",
        user: UserContext | str,
        files: S3FileAdapter | None = None,
    ) -> None:
        self._repo = repo
        self._user_id = user_id_of(user) if isinstance(user, UserContext) else user
        self._properties = PropertyService(repo, user)
        # The S3 adapter is only used by TransactionService for receipts, which
        # synthesis never creates. When no adapter is injected we still need a
        # non-empty bucket name for the adapter's constructor; it is never used.
        adapter = files if files is not None else S3FileAdapter(None, "unused")
        self._transactions = TransactionService(repo, adapter)

    # --- Primary entry point -------------------------------------------------

    def import_schedule_e(
        self, submission: ImportSubmission
    ) -> Result[ImportOutcome]:
        """Validate and apply a multi-property Schedule E import (Req 1, 3-11).

        Validation is all-or-nothing (Req 9): the whole submission is validated
        first and **no** create/delete/modify happens unless every check passes.
        After validation, each entry's ``(Property, Tax_Year)`` is replaced
        atomically — the prior imported set is deleted and the new summary rows
        written — and a per-entry outcome is returned (Req 1.5).
        """
        validation = self._validate(submission)
        if not validation.is_ok:
            return Result.failure(
                validation.error.kind,
                validation.error.message,
                validation.error.field,
            )

        tax_year = submission.tax_year  # type: ignore[assignment]  # validated present
        assert tax_year is not None

        outcomes: list[EntryOutcome] = []
        for entry in submission.entries:
            outcome = self._apply_entry(entry, int(tax_year))
            if not outcome.is_ok:
                # Property resolution (ownership) failures surface here. Earlier
                # entries may already be written; v1 does not attempt a
                # cross-entry rollback (validation runs first, so this is an
                # ownership/infra fault — see design "Atomicity").
                return Result.failure(
                    outcome.error.kind,
                    outcome.error.message,
                    outcome.error.field,
                )
            outcomes.append(outcome.value)

        return Result.success(ImportOutcome(tax_year=int(tax_year), entries=outcomes))

    # --- Undo (remove one imported set) --------------------------------------

    def remove_imported_set(
        self, property_id: str, tax_year: int
    ) -> Result[RemoveOutcome]:
        """Remove the imported set for one ``(Property, Tax_Year)`` (Req 8 undo).

        Confirms ownership (``not_found`` when missing/not owned; Req 10.1/10.3),
        selects **only** imported rows for that property + year, deletes exactly
        those (batched by <= 100), and reports the deleted count. User-tracked
        rows are never selected or deleted (Req 8.4).
        """
        if not self._properties.get(property_id).is_ok:
            return Result.failure(
                "not_found", "Property not found.", field="property_id"
            )

        imported_prior = self._imported_rows(property_id, int(tax_year))
        self._delete_rows(property_id, imported_prior)
        return Result.success(
            RemoveOutcome(
                property_id=property_id,
                tax_year=int(tax_year),
                deleted_count=len(imported_prior),
            )
        )

    # --- Write phase: one entry ----------------------------------------------

    def _apply_entry(
        self, entry: PropertyEntryInput, tax_year: int
    ) -> Result[EntryOutcome]:
        """Resolve the entry's property, replace its imported set, write new rows.

        Order is **delete-then-write per ``(Property, Tax_Year)`` pair**: the
        prior imported rows are removed and the new summary rows written as a
        single atomic unit when the combined action count fits in one DynamoDB
        transaction; otherwise the deletes and writes are batched (still
        delete-then-write) so a line dropped to zero never leaves a residual
        imported row (Req 8.6).
        """
        created_inline = False
        if entry.new_property is not None:
            # Deferred inline creation: validation already proved the fields are
            # present, so this is expected to succeed (Req 2.2). A fresh UUID id
            # makes two inline creates inherently distinct.
            created = self._properties.create(entry.new_property)
            if not created.is_ok:
                return Result.failure(
                    created.error.kind,
                    created.error.message,
                    created.error.field,
                )
            property_id = created.value.id
            created_inline = True
        else:
            # Existing property: confirm ownership (not_found otherwise; Req 2.3).
            property_id = entry.property_id  # type: ignore[assignment]
            if not self._properties.get(property_id).is_ok:
                return Result.failure(
                    "not_found", "Property not found.", field="property_id"
                )

        # Select the prior imported rows for this pair (never user-tracked rows),
        # then delete them BEFORE writing the new set so the ordering is
        # delete-then-write and a line dropped to zero leaves no residual
        # imported row (Req 8.6). Deletes are batched by <= 100 actions.
        imported_prior = self._imported_rows(property_id, tax_year)
        self._delete_rows(property_id, imported_prior)

        # Write one summary transaction per non-zero line for this entry.
        new_txns = self._synthesize_entry(entry, property_id, tax_year)

        return Result.success(
            EntryOutcome(
                property_id=property_id,
                created_transaction_ids=[t.id for t in new_txns],
                deleted_prior_count=len(imported_prior),
                created_inline_property=created_inline,
            )
        )

    # --- Synthesis (pure mapping from entry → transactions) ------------------

    def _synthesize_entry(
        self, entry: PropertyEntryInput, property_id: str, tax_year: int
    ) -> list[Transaction]:
        """Build one ``Summary_Transaction`` per non-zero line of the entry.

        Each line's amount is composed through ``TransactionService.create``
        (reusing amount>0 validation, category→line recording, the Line 19
        description rule, and correct base-table + GSI2 key emission). Lines
        whose amount is zero/blank are skipped (Req 6.2); Line 18 never reaches
        here (validation rejects it).
        """
        txn_date = _year_end(tax_year)
        created: list[Transaction] = []
        for line in entry.lines:
            amount = _parse_amount(line.amount)
            if amount <= _ZERO:
                continue
            category = _CATEGORY_BY_LINE[line.schedule_e_line]
            description = line.description
            if category.requires_description:
                # Line 19 (Other): use the provided text or the default so the
                # requires-description rule is satisfied (Req 6.5, 6.6).
                description = _clean(line.description) or _DEFAULT_LINE_19_DESCRIPTION
            result = self._transactions.create(
                TransactionInput(
                    property_id=property_id,
                    date=txn_date,
                    amount=amount,
                    type=category.kind,
                    category_id=category.id,
                    description=description,
                    imported=True,
                )
            )
            # Validation already guaranteed a positive two-decimal amount and a
            # valid category, so create succeeds; propagate any unexpected error
            # defensively rather than silently dropping a row.
            if result.is_ok:
                created.append(result.value)
        return created

    # --- Helpers -------------------------------------------------------------

    def _imported_rows(
        self, property_id: str, tax_year: int
    ) -> list[tuple[str, Transaction]]:
        """Return ``(SK, Transaction)`` for the imported rows of a pair.

        Uses the GSI2 tax-year partition (already scoped to property + year),
        then filters to rows carrying the imported marker so user-tracked rows
        are never selected (Req 8.2, 8.4).
        """
        listed = self._transactions.list_for_property(property_id, tax_year)
        if not listed.is_ok:
            return []
        rows: list[tuple[str, Transaction]] = []
        for txn in listed.value:
            if not txn.imported:
                continue
            d = date.fromisoformat(txn.date)
            rows.append((keys.transaction_sk(d, txn.id), txn))
        return rows

    def _delete_rows(
        self, property_id: str, rows: list[tuple[str, Transaction]]
    ) -> None:
        """Delete the given rows by ``(pk, sk)``, batched by <= 100 (Req 8.4)."""
        if not rows:
            return
        pk = keys.property_scoped_pk(property_id)
        actions = [{"delete": {"pk": pk, "sk": sk}} for sk, _ in rows]
        for chunk in _chunks(actions, _TRANSACT_LIMIT):
            self._repo.transact_write(chunk)

    # --- All-or-nothing validation (runs fully before any write) -------------

    def _validate(self, submission: ImportSubmission) -> Result[None]:
        """Validate the whole submission; no mutation happens here (Req 9.5).

        Surfaces the first failing check as a typed ``Result`` whose ``field``
        is the structured dotted path the SPA parses (``tax_year``, ``entries``,
        ``entries[i]``, ``entries[i].lines[<line>]``,
        ``entries[i].new_property.<field>``). Every check is performed before any
        write; ownership of each existing-property entry is confirmed here (a
        missing/not-owned property rejects the whole submission as ``not_found``
        before any write; Req 9.5, 10.3), while inline-create is deferred to the
        write phase so a late failure never leaves an orphan property.
        """
        # 1. Tax year present and a valid four-digit calendar year (Req 1.7, 3.2).
        tax_year = submission.tax_year
        if tax_year is None:
            return Result.failure(
                "validation", "A tax year is required.", field="tax_year"
            )
        if not isinstance(tax_year, int) or isinstance(tax_year, bool):
            return Result.failure(
                "validation",
                "Tax year must be a four-digit calendar year.",
                field="tax_year",
            )
        if not (1000 <= tax_year <= 9999):
            return Result.failure(
                "validation",
                "Tax year must be a four-digit calendar year (1000-9999).",
                field="tax_year",
            )

        # 2. At least one entry (Req 1.6).
        if not submission.entries:
            return Result.failure(
                "validation",
                "At least one property column is required.",
                field="entries",
            )

        # 3. Per entry.
        seen_property_ids: set[str] = set()
        for index, entry in enumerate(submission.entries):
            column = index + 1  # 1-based for human messages
            entry_field = f"entries[{index}]"

            # 3a. Property mapping: exactly one of property_id / new_property.
            has_existing = bool(entry.property_id)
            has_inline = entry.new_property is not None
            if has_existing == has_inline:
                return Result.failure(
                    "validation",
                    f"Property column {column} must map to exactly one property "
                    "(either an existing property or a new one).",
                    field=entry_field,
                )

            if has_existing:
                # Duplicate resolved-property mapping across entries (Req 2.5).
                if entry.property_id in seen_property_ids:
                    return Result.failure(
                        "validation",
                        f"Property column {column} maps to the same property as "
                        "another column; each column must map to a distinct "
                        "property for the tax year.",
                        field=entry_field,
                    )
                seen_property_ids.add(entry.property_id)  # type: ignore[arg-type]
                # Ownership check during validation (Req 9.5, 10.3): a property
                # that is missing or owned by another user rejects the ENTIRE
                # submission before any write, so all-or-nothing holds even when
                # an owned entry precedes a not-owned one in the same pass.
                if not self._properties.get(entry.property_id).is_ok:  # type: ignore[arg-type]
                    return Result.failure(
                        "not_found", "Property not found.", field=entry_field
                    )
            else:
                # Inline new_property: required fields present (name + address).
                # Creation itself is deferred to the write phase (Req 2.2, 2.4).
                new_property = entry.new_property
                if _blank(new_property.name):
                    return Result.failure(
                        "validation",
                        f"Property column {column}: a name is required for the "
                        "new property.",
                        field=f"{entry_field}.new_property.name",
                    )
                if _blank(new_property.address_text):
                    return Result.failure(
                        "validation",
                        f"Property column {column}: an address is required for "
                        "the new property.",
                        field=f"{entry_field}.new_property.address_text",
                    )

            # 3b. Line amounts.
            any_non_zero = False
            for line in entry.lines:
                line_number = line.schedule_e_line
                # Reject Line 18 and any line outside the modeled set (Req 5.1).
                if line_number not in _ALLOWED_LINES:
                    return Result.failure(
                        "validation",
                        f"Property column {column}: Line {line_number} is not an "
                        "importable Schedule E line.",
                        field=f"{entry_field}.lines[{line_number}]",
                    )
                # Blank/absent amount is treated as zero, not an error (Req 4.2).
                if _is_blank_amount(line.amount):
                    continue
                try:
                    amount = to_money(line.amount)  # type: ignore[arg-type]
                except (TypeError, ValueError):
                    return Result.failure(
                        "validation",
                        f"Property column {column}, {_line_label(line_number)}: "
                        "amount must be a valid monetary value.",
                        field=f"{entry_field}.lines[{line_number}]",
                    )
                if amount < _ZERO:
                    return Result.failure(
                        "validation",
                        f"Property column {column}, {_line_label(line_number)}: "
                        "amount must not be negative.",
                        field=f"{entry_field}.lines[{line_number}]",
                    )
                if amount > _ZERO:
                    any_non_zero = True

            # 3c. At least one non-zero line per entry (Req 9.4).
            if not any_non_zero:
                return Result.failure(
                    "validation",
                    f"Property column {column} requires at least one non-zero "
                    "line amount.",
                    field=entry_field,
                )

        return Result.success(None)


# --- Module-level pure helpers -----------------------------------------------


def _year_end(tax_year: int) -> str:
    """December 31 of the tax year as an ISO ``YYYY-12-31`` string.

    Dating every synthesized row at year-end places them unambiguously in the
    tax year's GSI2 partition (so ``list_for_property(property_id, tax_year)``
    returns them) and sorts them newest-first within the year (Req 3.3).
    """
    return f"{tax_year:04d}-12-31"


def _parse_amount(value: object) -> Decimal:
    """Parse an entered amount to two-decimal money; blank/invalid → ``0.00``.

    Reached only in the write phase after validation has already confirmed every
    provided amount is a non-negative two-decimal value, so a blank line maps to
    zero (and is skipped) and no exception escapes.
    """
    if _is_blank_amount(value):
        return _ZERO
    try:
        return to_money(value)  # type: ignore[arg-type]
    except (TypeError, ValueError):
        return _ZERO


def _is_blank_amount(value: object) -> bool:
    """True when a line amount is absent/blank (treated as zero; Req 4.2)."""
    if value is None:
        return True
    if isinstance(value, str) and value.strip() == "":
        return True
    return False


def _clean(text: str | None) -> str | None:
    """Trim a description; blank/whitespace-only becomes ``None``."""
    if text is None:
        return None
    stripped = text.strip()
    return stripped or None


def _blank(value: str | None) -> bool:
    """True when a required text field is missing or whitespace-only."""
    return value is None or value.strip() == ""


def _chunks(items: list, size: int) -> list:
    """Split ``items`` into consecutive lists of at most ``size`` elements."""
    return [items[i : i + size] for i in range(0, len(items), size)]
