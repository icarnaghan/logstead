"""Transaction and receipt-document models (Requirement 5, 7, 13).

Money fields are typed as ``decimal.Decimal``. Dates are ISO-8601
``YYYY-MM-DD`` strings; the repository derives the inverted-date sort key.
"""

from __future__ import annotations

from dataclasses import dataclass
from decimal import Decimal
from typing import Literal

TransactionType = Literal["income", "expense"]


@dataclass
class TransactionInput:
    """Input to create or edit a transaction (Requirements 5.1, 5.2, 5.3, 7.4).

    The service layer validates: amount greater than zero; property, date,
    amount, and category present; description required for the Other category
    (Line 19).
    """

    property_id: str | None
    date: str | None
    amount: Decimal | None
    type: TransactionType | None
    category_id: str | None
    description: str | None = None


@dataclass
class Transaction:
    """A persisted income or expense transaction (Requirement 5).

    Attributes:
        id: The transaction identifier.
        property_id: The owning property.
        date: ISO-8601 ``YYYY-MM-DD`` transaction date.
        amount: Monetary amount as a ``Decimal`` (always greater than zero).
        type: Income or expense.
        category_id: The assigned Schedule E category id.
        schedule_e_line: The Schedule E line recorded from the category
            (Requirement 7.3).
        description: Free-text; required for the Other category (Line 19).
        created_at: ISO-8601 creation timestamp.
        updated_at: ISO-8601 last-update timestamp.
    """

    id: str
    property_id: str
    date: str
    amount: Decimal
    type: TransactionType
    category_id: str
    schedule_e_line: int
    description: str | None = None
    created_at: str | None = None
    updated_at: str | None = None


@dataclass
class Document:
    """Receipt document metadata attached to a transaction (Requirement 5.8).

    The binary lives in S3; only metadata and the S3 key are stored.
    """

    id: str
    property_id: str
    transaction_id: str
    s3_key: str
    content_type: str
    original_filename: str
    uploaded_at: str | None = None
