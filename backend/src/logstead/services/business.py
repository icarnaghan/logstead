"""Business Service: user-scoped business-entity CRUD (Requirements 1, 2, 3, 4).

This service owns the application rules for the ``Business`` aggregate — a legal
business entity (such as an LLC) under which a user holds rental property. It is
constructed with a :class:`DynamoRepository` and the authenticated
:class:`UserContext` (or a raw user id) and scopes **every** operation to that
user, since businesses are keyed under ``USER#<userId>`` for the list view and
their ownership is enforced on the ``BUSINESS#<id> / META`` mirror's ``userId``
(Requirement 13.1).

Responsibilities (this module — entity CRUD only)
-------------------------------------------------
* ``create`` — validate that ``legal_name`` is non-blank (Requirement 1.4,
  returning a field-identifying ``validation`` ``Result`` on failure) and that
  ``entity_type`` is in :data:`~logstead.models.business.ENTITY_TYPES`
  (Requirement 1.5); default ``tax_year_end`` to
  :data:`~logstead.models.business.DEFAULT_TAX_YEAR_END` when omitted
  (Requirement 1.3); store ``ein`` verbatim (Requirement 1.6); stamp an id +
  timestamps, and atomically write **two** rows via
  :meth:`DynamoRepository.transact_write` (Requirement 13.1):

    - the user-scoped list row ``USER#<userId> / BUSINESS#<businessId>`` (so a
      user's businesses list with a single ``begins_with "BUSINESS#"`` query),
      and
    - the mirrored child-partition anchor ``BUSINESS#<businessId> / META`` (so a
      business is looked up by id, and its documents co-locate under one
      partition).

* ``list`` — query the user's ``BUSINESS#`` list rows; empty list when none
  (Requirements 2.1, 2.3).
* ``get`` — fetch the ``BUSINESS#<id> / META`` row; ``not_found`` if it is
  missing or owned by a different user (Requirements 3.1-3.3).
* ``update`` — re-validate ``legal_name``/``entity_type``, store ``ein``
  verbatim, preserve ``id``/``created_at``, refresh ``updated_at``, and rewrite
  both rows atomically; ``not_found`` when the business is missing or owned by
  another user (Requirement 4).
* ``delete`` — a **guarded** delete with a document cascade (Requirement 5):
  resolve the owned business (``not_found`` otherwise), compute
  ``linked_properties``; if any property is linked, return a ``conflict`` and
  mutate nothing (Requirement 5.2). It fails safe — if ``linked_properties``
  itself fails (e.g. the ``property_service`` collaborator was not wired) that
  failure is propagated and nothing is deleted. With zero links it lists the
  business's documents, best-effort deletes each S3 object, then atomically
  removes every document metadata row and the business's two rows (Requirements
  5.1, 5.4).
* ``owns`` — a boolean owned-meta check for :class:`PropertyService` to call
  when linking a property to a business.

This feature introduces no money fields on a business, so the
two-decimal-string money convention (Requirement 13.2) does not apply here.

Document operations (``request_document_upload``/``list_documents``/
``delete_document``, Requirements 6-8) are implemented here and mirror
:class:`~logstead.services.photo.PhotoService` exactly, except the content-type
allow-list (:data:`ALLOWED_DOCUMENT_TYPES`) is broader — it includes PDF, since
formation paperwork is typically scans and PDFs.

``linked_properties`` (Requirement 10) is implemented here too: it resolves the
owned business and then uses the injected :class:`PropertyService` to list the
user's properties and filter them by ``business_id`` (the design's filtered
property-list mechanism, option b — no extra GSI). It is the single source of
truth for "which properties are linked to this business", powering both the
business→properties view and the guarded ``delete``. Because the delete-guard
depends on it, ``linked_properties`` **requires**
the ``property_service`` collaborator: when it is ``None`` the method returns an
``unavailable`` failure rather than a silently-wrong empty list.

Mutual dependency / wiring (resolved by the router, task 7): ``BusinessService``
needs a :class:`PropertyService` (for ``linked_properties``) and
``PropertyService`` needs a ``BusinessService`` (for ``set_business``'s ownership
check). Both are **optional injected collaborators** that are only *used*, never
*constructed*, inside the other — so there is no import cycle. The router wires
them per request by constructing both and setting the collaborator references
after construction, e.g.::

    biz = BusinessService(repo, user, files, property_service=None)
    prop = PropertyService(repo, user, business_service=biz)
    biz._property_service = prop  # or re-construct biz with property_service=prop

(or, equivalently, construct ``prop`` first with ``business_service=None`` and
set ``prop._business_service = biz`` after ``biz`` is built with
``property_service=prop``). Either order resolves the cycle because neither
service touches the other at import time or in its constructor. The constructor
accepts the ``files`` and ``property_service`` collaborators that ``delete``
(and the document/link methods) use.

Item shapes follow the design's single-table conventions (design.md "Data
Models"); keys are built exclusively through :mod:`logstead.repository.keys`.
"""

from __future__ import annotations

import uuid
from dataclasses import dataclass
from datetime import datetime, timezone
from typing import TYPE_CHECKING, Any

from logstead.adapters import s3_files
from logstead.models.business import (
    DEFAULT_TAX_YEAR_END,
    ENTITY_TYPES,
    Business,
    BusinessDocument,
    BusinessInput,
)
from logstead.models.result import Result
from logstead.models.user import UserContext
from logstead.repository import keys
from logstead.services.auth import user_id_of

if TYPE_CHECKING:
    from logstead.adapters.s3_files import S3FileAdapter
    from logstead.repository.dynamo_repo import DynamoRepository
    from logstead.services.property import PropertyService


__all__ = [
    "ALLOWED_DOCUMENT_TYPES",
    "BusinessService",
    "BusinessDocumentWithUrl",
    "LinkedPropertyRef",
    "PresignedDocumentUpload",
    "business_to_rows",
]


# --- Business-document content-type allow-list (Requirement 6) ---------------
#
# Business documents accept a BROADER set than the image-only photo allow-list
# because formation paperwork is typically PDFs and scans (design.md "Document
# content-type allow-list" — a deliberately specified policy, not reused from
# PhotoService). PDF is accepted in addition to the common image types. The
# comparison is case-insensitive (see _normalize_content_type).
ALLOWED_DOCUMENT_TYPES: frozenset[str] = frozenset(
    {
        "application/pdf",
        "image/jpeg",
        "image/png",
        "image/webp",
        "image/heic",
        "image/heif",
    }
)


def _accepted_document_types_message() -> str:
    """A human-readable, stable listing of the accepted document content types."""
    return ", ".join(sorted(ALLOWED_DOCUMENT_TYPES))


def _normalize_content_type(content_type: str | None) -> str:
    """Lowercase and trim a declared content type for allow-list comparison.

    A missing/blank content type normalizes to the empty string, which is never
    in the allow-list, so it is rejected like any other unaccepted type.
    """
    return (content_type or "").strip().lower()


@dataclass(frozen=True)
class PresignedDocumentUpload:
    """The result of a successful :meth:`BusinessService.request_document_upload`.

    Mirrors :class:`~logstead.services.photo.PresignedUpload`, carrying what the
    caller needs to complete a direct-to-S3 upload and render the new document.
    The field names match the frontend wire shape ``{upload_url, document}``.

    Attributes:
        upload_url: A pre-signed S3 **PUT** URL the browser uploads the bytes to.
            The URL is bound to ``document.content_type``.
        document: The persisted :class:`BusinessDocument` metadata (id, s3_key,
            content_type, original_filename, uploaded_at).
    """

    upload_url: str
    document: BusinessDocument


@dataclass(frozen=True)
class BusinessDocumentWithUrl:
    """A stored business document paired with a pre-signed GET URL (Req 7.2).

    The field names match the frontend wire shape ``{document, download_url}``.
    """

    document: BusinessDocument
    download_url: str


@dataclass(frozen=True)
class LinkedPropertyRef:
    """A lightweight reference to a property linked to a business (Req 10.2, 10.3).

    Carries both the property ``id`` and its human-readable ``name`` so the
    business→properties view and the ``GET /businesses/{id}`` response can list
    linked properties by name and never surface a raw identifier where a name
    exists (Requirement 10.3). The field names match the frontend wire shape
    ``{id, name}`` (``LinkedPropertyRef`` in ``api/businesses.ts``). The property
    name comes from the :class:`~logstead.models.property.Property` ``name``
    field (its display name).
    """

    id: str
    name: str


def _now_iso() -> str:
    """Current UTC time as an ISO-8601 string (used for created/updated stamps)."""
    return datetime.now(timezone.utc).isoformat()


def _blank(value: str | None) -> bool:
    """True when a required text field is missing or whitespace-only."""
    return value is None or value.strip() == ""


# --- Module-level item builders (importable, id/timestamp-preserving) --------
#
# These pure functions render a business to its two single-table item shapes
# (list row + META mirror). They depend only on their arguments (never on
# service instance state), so the item shape has a single source of truth and a
# future restore path could build identical items from a document-supplied id,
# timestamps, and ``user_id``. Optional attributes that are ``None`` are carried
# through verbatim; the repository drops them so the stored item stays sparse.

def business_to_rows(business: Business) -> list[dict[str, Any]]:
    """Render a business as its two single-table rows (list row + META mirror).

    Both rows carry identical camelCase attributes so the user-view list and the
    id-addressed META mirror stay consistent. Ids, timestamps, and ``user_id``
    are taken verbatim from ``business`` so a restore can preserve the original
    values. Optional attributes left ``None`` are omitted on write (sparse) by
    the repository.
    """
    common = {
        "id": business.id,
        "userId": business.user_id,
        "legalName": business.legal_name,
        "entityType": business.entity_type,
        "ein": business.ein,
        "formationState": business.formation_state,
        "formationDate": business.formation_date,
        "businessAddress": business.business_address,
        "taxYearEnd": business.tax_year_end,
        "note": business.note,
        "createdAt": business.created_at,
        "updatedAt": business.updated_at,
    }
    list_row = {
        "PK": keys.user_pk(business.user_id),
        "SK": keys.business_user_sk(business.id),
        **common,
    }
    meta_row = {
        "PK": keys.business_scoped_pk(business.id),
        "SK": keys.business_meta_sk(),
        **common,
    }
    return [list_row, meta_row]


def _from_item(item: dict[str, Any]) -> Business:
    """Reconstruct a :class:`Business` from a stored META/list item.

    Optional attributes absent from the stored (sparse) item come back as
    ``None``; ``tax_year_end`` is always present on a created business but falls
    back to the default if a legacy row somehow lacks it.
    """
    return Business(
        id=str(item["id"]),
        user_id=str(item["userId"]),
        legal_name=str(item["legalName"]),
        entity_type=str(item["entityType"]),
        ein=(str(item["ein"]) if item.get("ein") is not None else None),
        formation_state=(
            str(item["formationState"])
            if item.get("formationState") is not None
            else None
        ),
        formation_date=(
            str(item["formationDate"])
            if item.get("formationDate") is not None
            else None
        ),
        business_address=(
            str(item["businessAddress"])
            if item.get("businessAddress") is not None
            else None
        ),
        tax_year_end=(
            str(item["taxYearEnd"])
            if item.get("taxYearEnd") is not None
            else DEFAULT_TAX_YEAR_END
        ),
        note=(str(item["note"]) if item.get("note") is not None else None),
        created_at=(
            str(item["createdAt"]) if item.get("createdAt") is not None else None
        ),
        updated_at=(
            str(item["updatedAt"]) if item.get("updatedAt") is not None else None
        ),
    )


# --- BusinessDocument serialization boundary ---------------------------------
#
# A document is a single row co-located under the business partition (PK
# BUSINESS#<id>, SK DOC#<docId>), mirroring PHOTO# under a property. The stored
# item uses the design's camelCase attribute names (design.md "BusinessDocument":
# businessId, s3Key, contentType, originalFilename, uploadedAt). ``id`` is stored
# so reads reconstruct the document without re-parsing the key.

def _document_to_item(document: BusinessDocument) -> dict[str, Any]:
    """Render a :class:`BusinessDocument` as its DynamoDB item."""
    return {
        "PK": keys.business_scoped_pk(document.business_id),
        "SK": keys.business_document_sk(document.id),
        "id": document.id,
        "businessId": document.business_id,
        "s3Key": document.s3_key,
        "contentType": document.content_type,
        "originalFilename": document.original_filename,
        "uploadedAt": document.uploaded_at,
    }


def _document_from_item(item: dict[str, Any]) -> BusinessDocument:
    """Reconstruct a :class:`BusinessDocument` from a stored item."""
    return BusinessDocument(
        id=str(item["id"]),
        business_id=str(item["businessId"]),
        s3_key=str(item["s3Key"]),
        content_type=str(item["contentType"]),
        original_filename=str(item["originalFilename"]),
        uploaded_at=(
            str(item["uploadedAt"]) if item.get("uploadedAt") is not None else None
        ),
    )


class BusinessService:
    """Business-entity CRUD scoped to one user (Requirements 1, 2, 3, 4).

    Args:
        repo: The single-table DynamoDB repository.
        user: The authenticated user (a :class:`UserContext`) or a raw user id
            string. All operations are scoped to this user.
        files: The S3 file adapter, injected for the document operations added
            in a later task; unused by the entity-CRUD surface.
        property_service: The property service, injected for the property-link
            and ``linked_properties`` operations added in a later task; unused
            by the entity-CRUD surface.
    """

    def __init__(
        self,
        repo: "DynamoRepository",
        user: UserContext | str,
        files: "S3FileAdapter | None" = None,
        property_service: "PropertyService | None" = None,
    ) -> None:
        self._repo = repo
        self._user_id = user_id_of(user) if isinstance(user, UserContext) else user
        self._files = files
        self._property_service = property_service

    # --- Serialization boundary ---------------------------------------------

    def _to_rows(self, business: Business) -> list[dict[str, Any]]:
        """Render a business as its two single-table rows (thin wrapper).

        Delegates to the module-level :func:`business_to_rows` so the item shapes
        have a single source of truth shared with any future restore write path.
        """
        return business_to_rows(business)

    def _owned_meta(self, business_id: str) -> dict[str, Any] | None:
        """Return the business's META item iff it exists and this user owns it.

        Ownership is enforced here so ``get``/``update`` (and the later
        document/delete operations) never act on a business belonging to another
        user, even though the child partition is keyed by business id alone
        (Requirements 3.2, 3.3, 4.4, 13.1).
        """
        item = self._repo.get_item(
            keys.business_scoped_pk(business_id), keys.business_meta_sk()
        )
        if item is None:
            return None
        if str(item.get("userId")) != self._user_id:
            return None
        return item

    # --- Create (Requirement 1) ----------------------------------------------

    def create(self, data: BusinessInput) -> Result[Business]:
        """Create a business for the authenticated user (Requirement 1).

        Validates ``legal_name`` as non-blank (Requirement 1.4) and
        ``entity_type`` against :data:`ENTITY_TYPES` (Requirement 1.5), returning
        a ``validation`` failure that identifies the offending field on error.
        ``tax_year_end`` defaults to :data:`DEFAULT_TAX_YEAR_END` when omitted or
        blank (Requirement 1.3); ``ein`` is stored exactly as entered
        (Requirement 1.6). On success both the user list row and the
        ``BUSINESS#..META`` mirror are written atomically (Requirements 2.2,
        13.1).
        """
        if _blank(data.legal_name):
            return Result.failure(
                "validation", "Legal name is required.", field="legal_name"
            )
        if data.entity_type not in ENTITY_TYPES:
            return Result.failure(
                "validation",
                "Entity type is required and must be a supported type.",
                field="entity_type",
            )

        now = _now_iso()
        business = Business(
            id=str(uuid.uuid4()),
            user_id=self._user_id,
            legal_name=data.legal_name.strip(),
            entity_type=data.entity_type,
            ein=data.ein,
            formation_state=data.formation_state,
            formation_date=data.formation_date,
            business_address=data.business_address,
            tax_year_end=(
                data.tax_year_end
                if not _blank(data.tax_year_end)
                else DEFAULT_TAX_YEAR_END
            ),
            note=data.note,
            created_at=now,
            updated_at=now,
        )
        self._repo.transact_write(
            [{"put": row} for row in self._to_rows(business)]
        )
        return Result.success(business)

    # --- Read (Requirements 2, 3) --------------------------------------------

    def list(self) -> list[Business]:
        """List the authenticated user's businesses (Requirements 2.1, 2.3).

        Queries the user's ``BUSINESS#`` list rows and returns an empty list when
        the user owns none. Only the current user's partition is read, so a
        business owned by a different ``sub`` is never returned (Requirement
        2.2).
        """
        items = self._repo.query(
            keys.user_pk(self._user_id),
            sk_begins_with=keys.business_list_prefix(),
        )
        return [_from_item(item) for item in items]

    def get(self, business_id: str) -> Result[Business]:
        """Fetch a single owned business, or ``not_found`` (Requirement 3).

        Returns ``not_found`` (field ``business_id``) when the business does not
        exist for this user or is owned by a different ``sub`` (Requirements
        3.1-3.3).
        """
        item = self._owned_meta(business_id)
        if item is None:
            return Result.failure(
                "not_found", "Business not found.", field="business_id"
            )
        return Result.success(_from_item(item))

    # --- Update (Requirement 4) ----------------------------------------------

    def update(self, business_id: str, data: BusinessInput) -> Result[Business]:
        """Update an owned business's fields (Requirement 4).

        Confirms ownership first, returning ``not_found`` (field ``business_id``)
        when the business is missing or owned by another user (Requirement 4.4).
        Re-validates ``legal_name`` (Requirement 4.2) and ``entity_type``
        (Requirement 4.3), and stores ``ein`` verbatim (Requirement 4.5).
        Preserves the original ``id``/``created_at``, refreshes ``updated_at``,
        and rewrites both rows atomically so the list row and META mirror stay
        consistent.
        """
        existing = self._owned_meta(business_id)
        if existing is None:
            return Result.failure(
                "not_found", "Business not found.", field="business_id"
            )

        if _blank(data.legal_name):
            return Result.failure(
                "validation", "Legal name is required.", field="legal_name"
            )
        if data.entity_type not in ENTITY_TYPES:
            return Result.failure(
                "validation",
                "Entity type is required and must be a supported type.",
                field="entity_type",
            )

        business = Business(
            id=business_id,
            user_id=self._user_id,
            legal_name=data.legal_name.strip(),
            entity_type=data.entity_type,
            ein=data.ein,
            formation_state=data.formation_state,
            formation_date=data.formation_date,
            business_address=data.business_address,
            tax_year_end=(
                data.tax_year_end
                if not _blank(data.tax_year_end)
                else DEFAULT_TAX_YEAR_END
            ),
            note=data.note,
            created_at=(
                str(existing["createdAt"])
                if existing.get("createdAt") is not None
                else None
            ),
            updated_at=_now_iso(),
        )
        self._repo.transact_write(
            [{"put": row} for row in self._to_rows(business)]
        )
        return Result.success(business)

    # --- Delete (Requirement 5): guarded + document cascade ------------------

    def delete(self, business_id: str) -> Result[None]:
        """Delete an owned business, guarded by linked properties (Requirement 5).

        Resolves the owned business first, returning ``not_found`` (field
        ``business_id``) when it is missing or owned by another user
        (Requirement 5.3).

        The delete is **guarded** by the property↔business link, mirroring
        :meth:`PropertyService.delete`: it computes the linked set via
        :meth:`linked_properties` (the single source of truth, design.md
        Architecture → filtered property-list). That call is trusted as the
        authority on whether any property is linked, so if it returns a failure
        (for example ``unavailable`` because the ``property_service`` collaborator
        was not wired) this method **fails safe** by propagating that failure and
        mutating nothing — it never falls back to a possibly-wrong "no links"
        assumption. When one or more properties are linked, it returns a
        ``conflict`` instructing the user to reassign or unlink those properties
        first and mutates nothing (Requirement 5.2).

        When zero properties are linked it performs the cascade (Requirements
        5.1, 5.4): it lists the business's document rows, best-effort deletes
        each S3 object (a single S3 failure is swallowed so it never aborts the
        cascade — the DynamoDB rows are still removed; if no S3 adapter is wired,
        object deletion is skipped), then atomically removes every document
        metadata row together with the business's two rows (the ``USER#<user> /
        BUSINESS#<id>`` list row and the ``BUSINESS#<id> / META`` mirror) via a
        single :meth:`transact_write` so DynamoDB is left consistent.
        """
        if self._owned_meta(business_id) is None:
            return Result.failure(
                "not_found", "Business not found.", field="business_id"
            )

        # Delete-guard: linked_properties is the authority on the linked set.
        # A failure (e.g. the collaborator is unwired -> ``unavailable``) is
        # propagated so we fail safe and never delete on a wrong "no links"
        # assumption (Requirement 5.2).
        linked = self.linked_properties(business_id)
        if not linked.is_ok:
            return linked
        if linked.value:
            return Result.failure(
                "conflict",
                "This business still owns one or more properties. Reassign or "
                "unlink those properties before deleting the business.",
            )

        scoped_pk = keys.business_scoped_pk(business_id)

        # Gather the business's documents; best-effort delete each S3 object so a
        # single S3 failure never aborts the DynamoDB cascade (Requirement 5.4).
        documents = self._repo.query(
            scoped_pk, sk_begins_with=keys.business_document_list_prefix()
        )
        deletes: list[dict[str, object]] = []
        for item in documents:
            document = _document_from_item(item)
            if self._files is not None:
                try:
                    self._files.delete_object(document.s3_key)
                except Exception:  # noqa: BLE001 - best-effort cleanup only
                    # Swallow a single object-delete failure: the metadata row
                    # is still removed below so the cascade completes. If no S3
                    # adapter is wired, object deletion is skipped entirely.
                    pass
            deletes.append(
                {
                    "delete": {
                        "pk": scoped_pk,
                        "sk": keys.business_document_sk(document.id),
                    }
                }
            )

        # Remove the two business rows together with the document metadata rows
        # in one atomic transaction (Requirements 5.1, 5.4).
        deletes.append(
            {
                "delete": {
                    "pk": keys.user_pk(self._user_id),
                    "sk": keys.business_user_sk(business_id),
                }
            }
        )
        deletes.append(
            {
                "delete": {
                    "pk": scoped_pk,
                    "sk": keys.business_meta_sk(),
                }
            }
        )
        self._repo.transact_write(deletes)
        return Result.success(None)

    # --- Documents (Requirements 6, 7, 8) ------------------------------------
    #
    # These mirror PhotoService exactly, except the allow-list is broader (it
    # includes PDF — see ALLOWED_DOCUMENT_TYPES). The binary bytes flow
    # browser↔S3 directly via pre-signed URLs; DynamoDB stores only the
    # BusinessDocument metadata row, co-located under the business partition so
    # a document is always scoped to its (owned) business (Requirement 6.4).
    # ``self._files`` is the injected S3 adapter; the router passes it for these
    # routes (and returns 503 upstream when no bucket is configured), so these
    # methods assume it is present.

    def request_document_upload(
        self, business_id: str, filename: str, content_type: str
    ) -> Result[PresignedDocumentUpload]:
        """Authorize a document upload and record its metadata (Requirement 6).

        Resolves the owned business first, returning ``not_found`` (field
        ``business_id``) when it is missing or owned by another user
        (Requirement 6.3). Then validates ``content_type`` against
        :data:`ALLOWED_DOCUMENT_TYPES` — an unaccepted type is rejected with a
        ``validation`` failure identifying the ``content_type`` field and naming
        the accepted types, *before* any S3 URL is issued or metadata written
        (mirroring :meth:`PhotoService.request_upload`). For an accepted type,
        this builds the document's S3 key (namespaced by document id so distinct
        uploads never collide), persists a :class:`BusinessDocument` metadata row
        under the business partition (Requirements 6.1, 6.2, 6.4), and returns a
        pre-signed PUT URL bound to that key and content type together with the
        stored metadata.
        """
        if self._owned_meta(business_id) is None:
            return Result.failure(
                "not_found", "Business not found.", field="business_id"
            )

        normalized = _normalize_content_type(content_type)
        if normalized not in ALLOWED_DOCUMENT_TYPES:
            return Result.failure(
                "validation",
                "Unsupported document type. Accepted types: "
                f"{_accepted_document_types_message()}.",
                field="content_type",
            )

        document_id = str(uuid.uuid4())
        filename = s3_files.sanitize_filename(filename)
        # Namespace the S3 key by document id so distinct uploads never collide
        # even when the original filenames match:
        # business-docs/<businessId>/<docId>/<name>.
        s3_key = s3_files.business_doc_key(
            business_id, f"{document_id}/{filename}"
        )
        document = BusinessDocument(
            id=document_id,
            business_id=business_id,
            s3_key=s3_key,
            content_type=normalized,
            original_filename=filename,
            uploaded_at=_now_iso(),
        )

        self._repo.put_item(_document_to_item(document))
        upload_url = self._files.presigned_put_url(s3_key, normalized)
        return Result.success(
            PresignedDocumentUpload(upload_url=upload_url, document=document)
        )

    def list_documents(
        self, business_id: str
    ) -> Result[list[BusinessDocumentWithUrl]]:
        """List a business's documents, each with a download URL (Requirement 7).

        Resolves the owned business first, returning ``not_found`` (field
        ``business_id``) when it is missing or owned by another user
        (Requirement 7.4). Queries the business partition for ``DOC#`` items and
        pairs each :class:`BusinessDocument` with a pre-signed **GET** URL so the
        browser can download it directly from S3 (Requirement 7.2). Returns an
        empty list when the business has no documents (Requirement 7.3). Because
        the partition is the business's own, a document of one entity is never
        returned for another (Requirements 7.1, 6.4).
        """
        if self._owned_meta(business_id) is None:
            return Result.failure(
                "not_found", "Business not found.", field="business_id"
            )

        items = self._repo.query(
            keys.business_scoped_pk(business_id),
            sk_begins_with=keys.business_document_list_prefix(),
        )
        documents: list[BusinessDocumentWithUrl] = []
        for item in items:
            document = _document_from_item(item)
            # PUT URLs cannot cap size: drop any oversized upload on read.
            if self._files.purge_if_oversized(
                document.s3_key, s3_files.MAX_DOCUMENT_BYTES
            ):
                self._repo.delete_item(
                    keys.business_scoped_pk(business_id), str(item["SK"])
                )
                continue
            documents.append(
                BusinessDocumentWithUrl(
                    document=document,
                    download_url=self._files.presigned_get_url(document.s3_key),
                )
            )
        return Result.success(documents)

    def delete_document(
        self, business_id: str, document_id: str
    ) -> Result[None]:
        """Delete a document's S3 object and metadata row (Requirement 8).

        Resolves the owned business first, returning ``not_found`` (field
        ``business_id``) when it is missing or owned by another user. Looks up
        the document metadata row to resolve the S3 key; a missing document
        yields a ``not_found`` failure (field ``document_id``) so a document id
        absent for the given business is reported as not found (Requirement 8.2).
        When present, this removes **both** the S3 object and the metadata row so
        the document is fully removed (Requirement 8.1). The S3 delete happens
        first (it is idempotent), then the metadata row is removed.
        """
        if self._owned_meta(business_id) is None:
            return Result.failure(
                "not_found", "Business not found.", field="business_id"
            )

        pk = keys.business_scoped_pk(business_id)
        sk = keys.business_document_sk(document_id)
        item = self._repo.get_item(pk, sk)
        if item is None:
            return Result.failure(
                "not_found", "Document not found.", field="document_id"
            )

        document = _document_from_item(item)
        self._files.delete_object(document.s3_key)
        self._repo.delete_item(pk, sk)
        return Result.success(None)

    # --- Ownership check (used by PropertyService.set_business, later) -------

    def owns(self, business_id: str) -> bool:
        """Return ``True`` iff an owned META row exists for this user.

        Used by :class:`PropertyService` when setting a property's business link
        so it can confirm the target business exists and belongs to the user
        before writing the link (Requirement 9.5).
        """
        return self._owned_meta(business_id) is not None

    # --- Both-sides viewing: linked properties (Requirement 10) --------------

    def linked_properties(
        self, business_id: str
    ) -> Result[list[LinkedPropertyRef]]:
        """List the properties linked to an owned business (Requirement 10.2).

        Resolves the owned business first, returning ``not_found`` (field
        ``business_id``) when it is missing or owned by another user
        (Requirements 3.2, 3.3, 5.3). Then uses the design's filtered
        property-list mechanism (design.md Architecture → "Business↔properties
        mechanism (filtered property-list, option b)"): it lists **this user's
        own** properties via the injected :class:`PropertyService` (a cheap
        ``begins_with "PROP#"`` query on the user partition) and keeps those
        whose ``business_id`` equals ``business_id``. No second GSI is used. Each
        kept property is returned as a :class:`LinkedPropertyRef` carrying its id
        **and** human-readable name, so the business→properties view and the
        ``GET /businesses/{id}`` response can show names, never raw ids
        (Requirement 10.3).

        This method is the single source of truth for "which properties are
        linked to this business"; it powers both the business→properties view
        (task 7's ``GET /businesses/{id}``) and the guarded delete (task 6).

        Collaborator requirement: ``linked_properties`` **requires** the injected
        :class:`PropertyService`. Returning an empty list when it is absent would
        be unsafe — the delete-guard relies on this method to detect links, so a
        spurious empty result could let a business with linked properties be
        deleted. When ``self._property_service`` is ``None`` the collaborator was
        not wired, which is a programming/wiring error; this returns an
        ``unavailable`` failure rather than a silently-wrong empty list. The
        router (task 7) wires ``property_service`` into ``BusinessService`` per
        request, so this path is not hit in normal operation.
        """
        if self._owned_meta(business_id) is None:
            return Result.failure(
                "not_found", "Business not found.", field="business_id"
            )

        if self._property_service is None:
            # Wiring error: without the collaborator we cannot determine the
            # linked set. Refuse rather than return a misleading empty list that
            # the delete-guard would read as "no links" (see docstring).
            return Result.failure(
                "unavailable",
                "Linked-property lookup is not available in this context.",
            )

        refs = [
            LinkedPropertyRef(id=prop.id, name=prop.name)
            for prop in self._property_service.list()
            if prop.business_id == business_id
        ]
        return Result.success(refs)
