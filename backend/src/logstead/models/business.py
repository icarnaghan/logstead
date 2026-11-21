"""Business entity domain models.

Covers the ``Business`` entity (a legal business, such as an LLC, under which a
user holds rental property), its create/edit input shape, and per-entity
document metadata (the binary lives in S3, mirroring :class:`PropertyPhoto`).

This feature introduces no money fields on a business, so the
two-decimal-string money convention does not apply here.
"""

from __future__ import annotations

from dataclasses import dataclass

ENTITY_TYPES = frozenset({
    "llc",
    "sole_proprietorship",
    "partnership",
    "s_corporation",
    "c_corporation",
    "individual_other",
})
"""Fixed, stable set of supported business entity types (Requirement 1.5)."""

DEFAULT_TAX_YEAR_END = "12-31"
"""Default ``tax_year_end`` (MM-DD) applied when omitted on create (Req 1.3)."""


@dataclass
class BusinessInput:
    """Input to create or edit a business entity (Requirements 1.1, 1.2).

    ``legal_name`` is validated as non-blank and ``entity_type`` is validated
    against :data:`ENTITY_TYPES` by the service layer. The remaining fields are
    optional: ``ein`` is stored verbatim with no format enforcement (Req 1.6),
    ``formation_state`` is a two-letter US code (e.g. ``"CA"``),
    ``formation_date`` an ISO ``YYYY-MM-DD`` string, and ``tax_year_end`` an
    ``MM-DD`` string that defaults to :data:`DEFAULT_TAX_YEAR_END` on create.
    """

    legal_name: str
    entity_type: str
    ein: str | None = None
    formation_state: str | None = None
    formation_date: str | None = None
    business_address: str | None = None
    tax_year_end: str | None = None
    note: str | None = None


@dataclass
class Business:
    """A business entity owned by the Authenticated_User (Requirement 1).

    Attributes:
        id: The business identifier.
        user_id: The owning user's Cognito ``sub``.
        legal_name: The entity's legal name.
        entity_type: One of :data:`ENTITY_TYPES`, stored verbatim.
        ein: Optional EIN, stored exactly as entered.
        formation_state: Optional two-letter US state code (e.g. ``"CA"``).
        formation_date: Optional ISO ``YYYY-MM-DD`` formation date.
        business_address: Optional free-text business address.
        tax_year_end: ``MM-DD`` string; defaults to ``"12-31"``.
        note: Optional free-text note.
        created_at: ISO-8601 creation timestamp.
        updated_at: ISO-8601 last-update timestamp.
    """

    id: str
    user_id: str
    legal_name: str
    entity_type: str
    ein: str | None = None
    formation_state: str | None = None
    formation_date: str | None = None
    business_address: str | None = None
    tax_year_end: str = "12-31"
    note: str | None = None
    created_at: str | None = None
    updated_at: str | None = None


@dataclass
class BusinessDocument:
    """Metadata for a business document; the binary lives in S3 (Requirement 6).

    Mirrors :class:`PropertyPhoto`: a metadata row co-located under the
    business partition, with the bytes stored in S3 under the document's key.
    """

    id: str
    business_id: str
    s3_key: str
    content_type: str
    original_filename: str
    uploaded_at: str | None = None
