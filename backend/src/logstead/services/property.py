"""Property Service: CRUD, usage days, and guarded deletion (Requirements 2, 12).

This service owns the application rules for the ``Property`` aggregate. It is
constructed with a :class:`DynamoRepository` and the authenticated
:class:`UserContext` (or a raw user id) and scopes **every** operation to that
user, since properties are keyed under ``USER#<userId>`` (Requirement 1.6).

Responsibilities
----------------
* ``create`` — validate that ``name`` and ``address_text`` are non-blank
  (Requirement 2.2, returning a field-identifying validation ``Result`` on
  failure), stamp an id + timestamps, and atomically write **two** rows via
  :meth:`DynamoRepository.transact_write` (Requirement 13.1):

    - the user-scoped list row ``USER#<userId> / PROP#<propertyId>`` (so a
      user's properties list with a single ``begins_with "PROP#"`` query), and
    - the mirrored child-partition anchor ``PROPERTY#<propertyId> / META`` (so a
      property's child items — details, usage, photos, transactions, assets —
      co-locate under one partition).

  Both rows also carry the GSI1 keys (``USER#<userId>`` / ``PROP#<propertyId>``)
  for reverse lookups. Creation never depends on RentCast enrichment
  (Requirement 3.7) — this service does not touch any enrichment adapter.

* ``list`` — query the user's ``PROP#`` list rows (Requirement 2.3).
* ``get`` — fetch the ``PROPERTY#<id> / META`` row; ``not_found`` if it is
  missing or owned by a different user (ownership check).
* ``update`` — validate and persist the mutable fields (name, address,
  property type) plus a fresh ``updated_at`` (Requirement 2.4). Ownership is
  confirmed first.
* ``delete`` — **guarded**: if the property has any transactions
  (``TXN#`` prefix) or any depreciable assets (``ASSET#`` prefix), reject with a
  ``conflict`` result stating associated records must be removed first
  (Requirement 2.7); otherwise remove the property's two rows plus its details
  and any usage rows (Requirement 2.6).

* ``set_usage_days`` / ``get_usage_days`` — store and read a
  :class:`PropertyUsageYear` per (property, tax year); non-negative integer days
  are required. These feed the Schedule E report header (Requirements 2.8, 10.2).

Item shapes follow the design's single-table conventions (design.md "Data
Models"); keys are built exclusively through :mod:`logstead.repository.keys`.
"""

from __future__ import annotations

import uuid
from datetime import datetime, timezone
from typing import TYPE_CHECKING

from logstead.models.property import (
    Property,
    PropertyDetails,
    PropertyInput,
    PropertyUsageYear,
)
from logstead.models.property_details_json import (
    details_from_json,
    details_to_json,
)
from logstead.models.result import Result
from logstead.models.user import UserContext
from logstead.repository import keys
from logstead.services.auth import user_id_of

if TYPE_CHECKING:
    from logstead.repository.dynamo_repo import DynamoRepository


__all__ = ["PropertyService"]


def _now_iso() -> str:
    """Current UTC time as an ISO-8601 string (used for created/updated stamps)."""
    return datetime.now(timezone.utc).isoformat()


def _blank(value: str | None) -> bool:
    """True when a required text field is missing or whitespace-only."""
    return value is None or value.strip() == ""


class PropertyService:
    """Property CRUD, usage days, and guarded deletion, scoped to one user.

    Args:
        repo: The single-table DynamoDB repository.
        user: The authenticated user (a :class:`UserContext`) or a raw user id
            string. All operations are scoped to this user.
    """

    def __init__(self, repo: "DynamoRepository", user: UserContext | str) -> None:
        self._repo = repo
        self._user_id = user_id_of(user) if isinstance(user, UserContext) else user

    # --- Serialization boundary ---------------------------------------------

    def _to_rows(self, prop: Property) -> list[dict[str, object]]:
        """Render a property as its two single-table rows (list row + META mirror).

        Both rows carry identical GSI1 keys so a user's properties are reachable
        via the reverse index as well as the base-table ``USER#`` partition.
        """
        gsi1_pk, gsi1_sk = keys.gsi1_property_keys(prop.user_id, prop.id)
        common = {
            "id": prop.id,
            "userId": prop.user_id,
            "name": prop.name,
            "addressText": prop.address_text,
            "propertyType": prop.property_type,
            "createdAt": prop.created_at,
            "updatedAt": prop.updated_at,
            "GSI1PK": gsi1_pk,
            "GSI1SK": gsi1_sk,
        }
        list_row = {
            "PK": keys.user_pk(prop.user_id),
            "SK": keys.property_user_sk(prop.id),
            **common,
        }
        meta_row = {
            "PK": keys.property_scoped_pk(prop.id),
            "SK": keys.property_meta_sk(),
            **common,
        }
        return [list_row, meta_row]

    @staticmethod
    def _from_item(item: dict[str, object]) -> Property:
        """Reconstruct a :class:`Property` from a stored META/list item."""
        return Property(
            id=str(item["id"]),
            user_id=str(item["userId"]),
            name=str(item["name"]),
            address_text=str(item["addressText"]),
            property_type=(
                str(item["propertyType"])
                if item.get("propertyType") is not None
                else None
            ),
            created_at=(
                str(item["createdAt"]) if item.get("createdAt") is not None else None
            ),
            updated_at=(
                str(item["updatedAt"]) if item.get("updatedAt") is not None else None
            ),
        )

    def _details_row(
        self, property_id: str, details: PropertyDetails
    ) -> dict[str, object]:
        """Render the ``PROPERTY#<id> / DETAILS`` row for a details object.

        The whole sparse details tree is serialized into a single ``detailsJson``
        string (money as two-decimal strings, lat/long full precision), so the
        provider-driven field set needs no rigid table schema. ``userId`` is
        carried so ``get_details`` can enforce the same ownership scope as the
        META mirror.
        """
        return {
            "PK": keys.property_scoped_pk(property_id),
            "SK": keys.property_details_sk(),
            "userId": self._user_id,
            "propertyId": property_id,
            "detailsJson": details_to_json(details),
        }

    def _owned_meta(self, property_id: str) -> dict[str, object] | None:
        """Return the property's META item iff it exists and this user owns it.

        Ownership is enforced here so ``get``/``update``/``delete`` never act on
        a property belonging to another user, even though the child partition is
        keyed by property id alone (Requirement 1.6).
        """
        item = self._repo.get_item(
            keys.property_scoped_pk(property_id), keys.property_meta_sk()
        )
        if item is None:
            return None
        if str(item.get("userId")) != self._user_id:
            return None
        return item

    # --- Create --------------------------------------------------------------

    def create(self, data: PropertyInput) -> Result[Property]:
        """Create a property for the authenticated user (Requirements 2.1, 2.2).

        Validates that ``name`` and ``address_text`` are non-blank, returning a
        ``validation`` failure that identifies the offending field on error. On
        success, both the user list row and the ``PROPERTY#..META`` mirror are
        written atomically (Requirement 13.1). Creation does not depend on any
        enrichment provider (Requirement 3.7).
        """
        if _blank(data.name):
            return Result.failure("validation", "Name is required.", field="name")
        if _blank(data.address_text):
            return Result.failure(
                "validation", "Address is required.", field="address_text"
            )

        now = _now_iso()
        prop = Property(
            id=str(uuid.uuid4()),
            user_id=self._user_id,
            name=data.name.strip(),
            address_text=data.address_text.strip(),
            property_type=data.property_type,
            created_at=now,
            updated_at=now,
        )
        puts: list[dict[str, object]] = [{"put": row} for row in self._to_rows(prop)]
        if data.details is not None:
            # Persist the RentCast-driven details as a third row, atomically with
            # the list/META rows, so enrichment captured at creation survives
            # (the DETAILS row was previously only ever deleted, never written).
            puts.append({"put": self._details_row(prop.id, data.details)})
        self._repo.transact_write(puts)
        return Result.success(prop)

    # --- Read ----------------------------------------------------------------

    def list(self) -> list[Property]:
        """List the authenticated user's properties (Requirement 2.3)."""
        items = self._repo.query(
            keys.user_pk(self._user_id),
            sk_begins_with=keys.property_list_prefix(),
        )
        return [self._from_item(item) for item in items]

    def get(self, property_id: str) -> Result[Property]:
        """Fetch a single owned property, or ``not_found`` (Requirement 2.9).

        When a stored :class:`PropertyDetails` row exists for the property it is
        parsed back and attached to the returned :class:`Property` as ``details``
        so callers can prefill/display the enriched fields; otherwise ``details``
        stays ``None``.
        """
        item = self._owned_meta(property_id)
        if item is None:
            return Result.failure("not_found", "Property not found.")
        prop = self._from_item(item)
        details = self._read_details(property_id)
        if details is not None:
            prop.details = details
        return Result.success(prop)

    def get_details(self, property_id: str) -> Result[PropertyDetails]:
        """Fetch the stored :class:`PropertyDetails` for an owned property.

        Returns ``not_found`` when the property is missing/not owned or when no
        DETAILS row has been persisted for it (details are optional; 3.7, 2.9).
        """
        if self._owned_meta(property_id) is None:
            return Result.failure("not_found", "Property not found.")
        details = self._read_details(property_id)
        if details is None:
            return Result.failure("not_found", "No details recorded for this property.")
        return Result.success(details)

    def _read_details(self, property_id: str) -> PropertyDetails | None:
        """Read + parse the DETAILS row, or ``None`` when absent/blank.

        Ownership is assumed to have been checked by the caller via
        :meth:`_owned_meta`; the DETAILS row's own ``userId`` is re-checked as a
        defense-in-depth guard against a mismatched write.
        """
        item = self._repo.get_item(
            keys.property_scoped_pk(property_id), keys.property_details_sk()
        )
        if item is None:
            return None
        if str(item.get("userId")) != self._user_id:
            return None
        raw = item.get("detailsJson")
        if not raw:
            return None
        return details_from_json(str(raw))

    # --- Notes ---------------------------------------------------------------

    def get_note(self, property_id: str) -> Result[str]:
        """Return the property's free-text note (empty string when none set).

        Confirms ownership first. A property with no note yet resolves to an
        empty string rather than not_found so the UI can render an empty editor.
        """
        if self._owned_meta(property_id) is None:
            return Result.failure("not_found", "Property not found.")
        item = self._repo.get_item(
            keys.property_scoped_pk(property_id), keys.property_note_sk()
        )
        if item is None or str(item.get("userId")) != self._user_id:
            return Result.success("")
        return Result.success(str(item.get("text", "")))

    def set_note(self, property_id: str, text: str) -> Result[str]:
        """Create or replace the property's single free-text note.

        Confirms ownership, then upserts the ``PROPERTY#<id> / NOTE`` item with
        the trimmed text (empty string allowed).
        """
        if self._owned_meta(property_id) is None:
            return Result.failure("not_found", "Property not found.")
        clean = (text or "").strip()
        self._repo.put_item(
            {
                "PK": keys.property_scoped_pk(property_id),
                "SK": keys.property_note_sk(),
                "propertyId": property_id,
                "userId": self._user_id,
                "text": clean,
                "updatedAt": _now_iso(),
            }
        )
        return Result.success(clean)

    # --- Update --------------------------------------------------------------

    def update(self, property_id: str, data: PropertyInput) -> Result[Property]:
        """Update an owned property's mutable fields (Requirement 2.4).

        Validates ``name``/``address_text`` exactly as :meth:`create`. Confirms
        ownership before writing. Refreshes ``updated_at`` and preserves the
        original ``created_at``. Both rows are rewritten atomically so the list
        row and META mirror stay consistent.
        """
        existing = self._owned_meta(property_id)
        if existing is None:
            return Result.failure("not_found", "Property not found.")

        if _blank(data.name):
            return Result.failure("validation", "Name is required.", field="name")
        if _blank(data.address_text):
            return Result.failure(
                "validation", "Address is required.", field="address_text"
            )

        prop = Property(
            id=property_id,
            user_id=self._user_id,
            name=data.name.strip(),
            address_text=data.address_text.strip(),
            property_type=data.property_type,
            created_at=(
                str(existing["createdAt"])
                if existing.get("createdAt") is not None
                else None
            ),
            updated_at=_now_iso(),
        )
        self._repo.transact_write(
            [{"put": row} for row in self._to_rows(prop)]
        )
        return Result.success(prop)

    # --- Delete (guarded) ----------------------------------------------------

    def delete(self, property_id: str) -> Result[None]:
        """Delete an owned property, guarded by associations (Requirements 2.6, 2.7).

        Rejects with a ``conflict`` result if the property has any transactions
        or depreciable assets, so associated records must be removed first
        (Requirement 2.7). Otherwise removes the property's list row and META
        mirror, plus its details item and any usage-year rows (Requirement 2.6).
        """
        if self._owned_meta(property_id) is None:
            return Result.failure("not_found", "Property not found.")

        scoped_pk = keys.property_scoped_pk(property_id)

        transactions = self._repo.query(
            scoped_pk, sk_begins_with=keys.transaction_list_prefix()
        )
        assets = self._repo.query(
            scoped_pk, sk_begins_with=keys.asset_list_prefix()
        )
        if transactions or assets:
            return Result.failure(
                "conflict",
                "Property has associated records; remove its transactions and "
                "depreciable assets before deleting it.",
            )

        # Safe to delete: gather the property's rows plus any details/note/usage rows.
        deletes: list[dict[str, object]] = [
            {"delete": {"pk": keys.user_pk(self._user_id),
                        "sk": keys.property_user_sk(property_id)}},
            {"delete": {"pk": scoped_pk, "sk": keys.property_meta_sk()}},
            {"delete": {"pk": scoped_pk, "sk": keys.property_details_sk()}},
            {"delete": {"pk": scoped_pk, "sk": keys.property_note_sk()}},
        ]
        for usage in self._repo.query(scoped_pk, sk_begins_with=keys.USAGE_PREFIX):
            deletes.append(
                {"delete": {"pk": scoped_pk, "sk": str(usage["SK"])}}
            )
        self._repo.transact_write(deletes)
        return Result.success(None)

    # --- Usage days ----------------------------------------------------------

    def set_usage_days(
        self,
        property_id: str,
        tax_year: int,
        fair_rental_days: int,
        personal_use_days: int,
    ) -> Result[PropertyUsageYear]:
        """Store fair-rental/personal-use days for a property + year (Req 2.8).

        Validates that both day counts are non-negative integers. Confirms
        ownership before writing. The stored :class:`PropertyUsageYear` is later
        surfaced in the Schedule E report header (Requirement 10.2).
        """
        if self._owned_meta(property_id) is None:
            return Result.failure("not_found", "Property not found.")

        for field_name, value in (
            ("fair_rental_days", fair_rental_days),
            ("personal_use_days", personal_use_days),
        ):
            if isinstance(value, bool) or not isinstance(value, int):
                return Result.failure(
                    "validation",
                    f"{field_name} must be an integer.",
                    field=field_name,
                )
            if value < 0:
                return Result.failure(
                    "validation",
                    f"{field_name} must not be negative.",
                    field=field_name,
                )

        usage = PropertyUsageYear(
            property_id=property_id,
            tax_year=tax_year,
            fair_rental_days=fair_rental_days,
            personal_use_days=personal_use_days,
        )
        self._repo.put_item(
            {
                "PK": keys.property_scoped_pk(property_id),
                "SK": keys.usage_sk(tax_year),
                "propertyId": property_id,
                "taxYear": tax_year,
                "fairRentalDays": fair_rental_days,
                "personalUseDays": personal_use_days,
            }
        )
        return Result.success(usage)

    def get_usage_days(
        self, property_id: str, tax_year: int
    ) -> Result[PropertyUsageYear]:
        """Read stored usage days for a property + year (Requirements 2.8, 10.2).

        Returns ``not_found`` if the property is missing/not owned or if no
        usage-year record exists for the requested tax year.
        """
        if self._owned_meta(property_id) is None:
            return Result.failure("not_found", "Property not found.")

        item = self._repo.get_item(
            keys.property_scoped_pk(property_id), keys.usage_sk(tax_year)
        )
        if item is None:
            return Result.failure(
                "not_found", "No usage days recorded for that tax year."
            )
        return Result.success(
            PropertyUsageYear(
                property_id=property_id,
                tax_year=int(item["taxYear"]),  # type: ignore[arg-type]
                fair_rental_days=int(item["fairRentalDays"]),  # type: ignore[arg-type]
                personal_use_days=int(item["personalUseDays"]),  # type: ignore[arg-type]
            )
        )
