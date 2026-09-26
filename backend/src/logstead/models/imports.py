"""Expense-import session and draft-transaction models (Requirement 6).

Drafts are staging items only — they never surface in Schedule E aggregation
until confirmed into a ``Transaction`` (Requirement 6.6). Draft fields are
optional because a parsed line item may be incomplete; the ``missing_fields``
list flags exactly the required fields (date, amount, category) that are
unset (Requirement 6.9).
"""

from __future__ import annotations

from dataclasses import dataclass, field
from decimal import Decimal
from typing import Literal

ImportStatus = Literal["parsing", "review", "confirmed", "failed"]


@dataclass
class ImportSession:
    """An expense-summary import associated with a property and tax year.

    Attributes:
        id: The import session identifier.
        property_id: The property the import is associated with.
        tax_year: The tax year selected for the import.
        pdf_s3_key: S3 key of the uploaded expense-summary PDF.
        status: Lifecycle status (parsing/review/confirmed/failed).
        created_at: ISO-8601 creation timestamp.
    """

    id: str
    property_id: str
    tax_year: int
    pdf_s3_key: str
    status: ImportStatus = "parsing"
    created_at: str | None = None


@dataclass
class DraftTransaction:
    """A parsed expense-summary line item awaiting review (Requirement 6).

    All content fields are optional because a parsed line item may be
    incomplete. ``missing_fields`` flags exactly the required fields that are
    unset (Requirement 6.9). Money fields are typed as ``decimal.Decimal``.
    """

    id: str
    import_session_id: str
    date: str | None = None
    amount: Decimal | None = None
    description: str | None = None
    type: str | None = None
    category_id: str | None = None
    missing_fields: list[str] = field(default_factory=list)
