"""Backup document validation (Requirements 3, 4, 5, 13).

This module hosts :func:`validate_document`, the **pure, side-effect-free**
validation pass a restore runs *before* touching the store. It reads and writes
nothing: it takes the raw parsed JSON body and returns a
:class:`Result[BackupDocument]` — a fully-parsed, typed document on success, or
the first ``validation`` failure it finds (identifying the offending
entity/field/value/version) on failure.

The :class:`BackupService` (export/restore/clear) lives alongside the validator
here. ``restore`` runs this pure validator first, so it can guarantee "no
read/write happens until validation passes."

Validation order (first failure wins), matching design "Validation model":

1. **JSON object shape** — the body is a dict with a ``properties`` list.
2. **Schema version** — ``schema_version`` present and equal to
   :data:`SCHEMA_VERSION`.
3. **Per-entity required fields** — property ``id``/``name``/``address_text``;
   transaction ``id``/``property_id``/``date``/``amount``/``type``/``category_id``;
   asset ``id``/``property_id``/``description``/``cost_basis``/
   ``placed_in_service_date``.
4. **Money format** — transaction ``amount``, asset ``cost_basis``, and every
   money field inside the details subtree parse via
   :func:`logstead.util.money.to_money` (exact ``Decimal``, never float);
   ``recovery_period_years`` parses as a plain ``Decimal``; details
   coordinates parse as full-precision ``Decimal``.
5. **Category integrity** — every transaction ``category_id`` is a member of
   ``CATEGORY_CATALOG``; any bad category rejects the whole document.
6. **Cross-reference** — each child ``property_id`` matches a property present
   in the document.
"""

from __future__ import annotations

from collections.abc import Iterable
from datetime import datetime, timezone
from decimal import Decimal, InvalidOperation
from typing import TYPE_CHECKING, Any

from logstead.models.backup import (
    SCHEMA_VERSION,
    BackupAsset,
    BackupDocument,
    BackupProperty,
    BackupTransaction,
    BackupUsageYear,
    ClearSummary,
    RestoreSummary,
)
from logstead.models.depreciation import (
    DEFAULT_RECOVERY_PERIOD_YEARS,
    DepreciableAsset,
)
from logstead.models.property import Property, PropertyDetails
from logstead.models.property_details_json import details_from_dict, details_to_dict
from logstead.models.result import Result
from logstead.models.transaction import Transaction
from logstead.models.user import UserContext
from logstead.repository import keys
from logstead.services.auth import user_id_of
from logstead.services.depreciation import (
    DepreciationService,
    asset_to_item,
    compute_schedule_rows,
    schedule_row_to_item,
)
from logstead.services.property import (
    PropertyService,
    property_details_row,
    property_note_row,
    property_to_rows,
    property_usage_row,
)
from logstead.services.transaction import (
    TransactionService,
    category_by_id,
    transaction_to_item,
)
from logstead.util.money import to_money

_DATE_FMT = "%Y-%m-%d"

if TYPE_CHECKING:
    from logstead.adapters.s3_files import S3FileAdapter
    from logstead.repository.dynamo_repo import DynamoRepository

__all__ = ["BackupService", "validate_document"]


# --- Small validation helpers ------------------------------------------------


def _missing(value: Any) -> bool:
    """Return ``True`` when a required field is absent.

    A field is "missing" when it is ``None`` or an empty/whitespace-only string.
    Numbers (including ``0``) and other typed values count as present.
    """
    if value is None:
        return True
    if isinstance(value, str) and not value.strip():
        return True
    return False


def _entity_label(entity_type: str, entity: dict[str, Any]) -> str:
    """A human-readable entity label naming the type and id when available."""
    raw_id = entity.get("id")
    if isinstance(raw_id, str) and raw_id.strip():
        return f"{entity_type} {raw_id!r}"
    return entity_type


def _parse_money(
    raw: Any, *, field_name: str, location: str
) -> Result[Decimal]:
    """Parse a money value via ``to_money`` (exact two-decimal, never float).

    Returns a ``validation`` failure naming the offending value and location on
    a non-string/non-parseable/non-finite value; ``to_money`` rejects floats.
    """
    if not isinstance(raw, str):
        return Result.failure(
            "validation",
            f"{location}: {field_name} must be a two-decimal string, "
            f"got {raw!r}",
            field=field_name,
        )
    try:
        return Result.success(to_money(raw))
    except (ValueError, TypeError):
        return Result.failure(
            "validation",
            f"{location}: {field_name} is not a valid money amount: {raw!r}",
            field=field_name,
        )


def _parse_plain_decimal(
    raw: Any, *, field_name: str, location: str
) -> Result[Decimal]:
    """Parse a non-money decimal (e.g. ``recovery_period_years``) exactly."""
    if isinstance(raw, bool) or not isinstance(raw, (str, int, Decimal)):
        return Result.failure(
            "validation",
            f"{location}: {field_name} must be a decimal string, got {raw!r}",
            field=field_name,
        )
    try:
        dec = Decimal(str(raw))
    except (InvalidOperation, ValueError):
        return Result.failure(
            "validation",
            f"{location}: {field_name} is not a valid decimal: {raw!r}",
            field=field_name,
        )
    if not dec.is_finite():
        return Result.failure(
            "validation",
            f"{location}: {field_name} must be finite, got {raw!r}",
            field=field_name,
        )
    return Result.success(dec)


# Money fields that may appear inside the details subtree, by nesting location.
# Coordinates (latitude/longitude) are validated as full-precision decimals.
def _validate_details(
    raw: Any, *, location: str
) -> Result[PropertyDetails]:
    """Validate every money and coordinate value inside a details subtree.

    ``details`` is optional; a ``None`` subtree yields ``None`` details. Money
    fields must parse via ``to_money``; coordinates as full-precision decimals.
    On success returns the parsed :class:`PropertyDetails` (via
    ``details_from_dict``); on the first bad value a ``validation`` failure.
    """
    if raw is None:
        return Result.success(None)  # type: ignore[arg-type]
    if not isinstance(raw, dict):
        return Result.failure(
            "validation",
            f"{location}: details must be a JSON object when present",
            field="details",
        )

    # Top-level money + coordinate scalars.
    checks: list[tuple[str, str, bool]] = [
        # (key, field_name, is_money)
        ("last_sale_price", "details.last_sale_price", True),
        ("latitude", "details.latitude", False),
        ("longitude", "details.longitude", False),
    ]
    for key, field_name, is_money in checks:
        if key in raw and raw[key] is not None and raw[key] != "":
            parser = _parse_money if is_money else _parse_plain_decimal
            result = parser(raw[key], field_name=field_name, location=location)
            if not result.is_ok:
                return Result.failure(
                    "validation", result.error.message, field=field_name
                )

    # HOA fee.
    hoa = raw.get("hoa")
    if isinstance(hoa, dict) and hoa.get("fee") not in (None, ""):
        result = _parse_money(hoa["fee"], field_name="details.hoa.fee",
                              location=location)
        if not result.is_ok:
            return Result.failure(
                "validation", result.error.message, field="details.hoa.fee"
            )

    # Year-keyed money lists: tax_assessments, property_taxes, sale_history.
    money_lists: list[tuple[str, tuple[str, ...]]] = [
        ("tax_assessments", ("value", "land", "improvements")),
        ("property_taxes", ("total",)),
        ("sale_history", ("price",)),
    ]
    for list_key, money_fields in money_lists:
        entries = raw.get(list_key)
        if not isinstance(entries, list):
            continue
        for entry in entries:
            if not isinstance(entry, dict):
                continue
            for money_field in money_fields:
                val = entry.get(money_field)
                if val in (None, ""):
                    continue
                field_name = f"details.{list_key}.{money_field}"
                result = _parse_money(val, field_name=field_name,
                                      location=location)
                if not result.is_ok:
                    return Result.failure(
                        "validation", result.error.message, field=field_name
                    )

    return Result.success(details_from_dict(raw))


# --- Public validator --------------------------------------------------------


def validate_document(raw: Any) -> Result[BackupDocument]:
    """Validate a raw backup document without any read or write.

    Returns a fully-parsed :class:`BackupDocument` on success, or the first
    ``validation`` failure (naming the offending entity/field/value/version) on
    failure. This function performs NO store access; a caller can rely on that
    to guarantee an invalid document never mutates data (Requirements 3.1, 3.2,
    3.4, 4.1, 4.2, 4.3, 5.1, 5.2, 5.3, 13.2).
    """
    # 1. JSON object shape (Requirement 3.1).
    if not isinstance(raw, dict) or not isinstance(raw.get("properties"), list):
        return Result.failure(
            "validation",
            "backup document must be a JSON object with a properties array",
        )

    # 2. Schema version present + supported (Requirements 5.1, 5.2, 5.3).
    if _missing(raw.get("schema_version")):
        return Result.failure(
            "validation",
            "backup document is missing its schema_version",
            field="schema_version",
        )
    version = raw["schema_version"]
    if version != SCHEMA_VERSION:
        return Result.failure(
            "validation",
            f"unsupported schema_version {version!r}; "
            f"expected {SCHEMA_VERSION!r}",
            field="schema_version",
        )

    raw_properties: list[Any] = raw["properties"]
    property_ids: set[str] = set()
    parsed_properties: list[BackupProperty] = []

    # First pass over properties: required fields + collect ids for the
    # cross-reference check.
    for raw_prop in raw_properties:
        if not isinstance(raw_prop, dict):
            return Result.failure(
                "validation", "each property must be a JSON object"
            )
        for field_name in ("id", "name", "address_text"):
            if _missing(raw_prop.get(field_name)):
                return Result.failure(
                    "validation",
                    f"{_entity_label('property', raw_prop)} is missing "
                    f"required field {field_name!r}",
                    field=field_name,
                )
        property_ids.add(str(raw_prop["id"]))

    # Second pass: per-property children (required fields, money, category,
    # cross-reference), building the fully-parsed document.
    for raw_prop in raw_properties:
        prop_id = str(raw_prop["id"])

        # Details subtree (money + coordinates).
        details_result = _validate_details(
            raw_prop.get("details"),
            location=f"property {prop_id!r}",
        )
        if not details_result.is_ok:
            return Result.failure(
                "validation",
                details_result.error.message,
                field=details_result.error.field,
            )
        details = details_result.value

        # Usage years.
        parsed_usage: list[BackupUsageYear] = []
        for raw_usage in raw_prop.get("usage") or []:
            if not isinstance(raw_usage, dict):
                return Result.failure(
                    "validation",
                    f"property {prop_id!r}: each usage entry must be a "
                    "JSON object",
                )
            ref = raw_usage.get("property_id")
            if ref is not None and str(ref) not in property_ids:
                return Result.failure(
                    "validation",
                    f"usage year references unknown property_id {ref!r}",
                    field="property_id",
                )
            parsed_usage.append(
                BackupUsageYear(
                    tax_year=int(raw_usage["tax_year"]),
                    fair_rental_days=int(raw_usage.get("fair_rental_days", 0)),
                    personal_use_days=int(raw_usage.get("personal_use_days", 0)),
                )
            )

        # Transactions: required fields -> money -> category -> cross-ref.
        parsed_txns: list[BackupTransaction] = []
        for raw_txn in raw_prop.get("transactions") or []:
            if not isinstance(raw_txn, dict):
                return Result.failure(
                    "validation",
                    f"property {prop_id!r}: each transaction must be a "
                    "JSON object",
                )
            for field_name in (
                "id", "property_id", "date", "amount", "type", "category_id"
            ):
                if _missing(raw_txn.get(field_name)):
                    return Result.failure(
                        "validation",
                        f"{_entity_label('transaction', raw_txn)} is missing "
                        f"required field {field_name!r}",
                        field=field_name,
                    )

            amount_result = _parse_money(
                raw_txn["amount"],
                field_name="amount",
                location=f"transaction {raw_txn['id']!r}",
            )
            if not amount_result.is_ok:
                return Result.failure(
                    "validation", amount_result.error.message, field="amount"
                )

            category_id = str(raw_txn["category_id"])
            if category_by_id(category_id) is None:
                return Result.failure(
                    "validation",
                    f"{_entity_label('transaction', raw_txn)} references "
                    f"unknown category_id {category_id!r}",
                    field="category_id",
                )

            ref = str(raw_txn["property_id"])
            if ref not in property_ids:
                return Result.failure(
                    "validation",
                    f"{_entity_label('transaction', raw_txn)} references "
                    f"unknown property_id {ref!r}",
                    field="property_id",
                )

            schedule_e_line = raw_txn.get("schedule_e_line")
            parsed_txns.append(
                BackupTransaction(
                    id=str(raw_txn["id"]),
                    property_id=ref,
                    date=str(raw_txn["date"]),
                    amount=amount_result.value,
                    type=str(raw_txn["type"]),
                    category_id=category_id,
                    schedule_e_line=(
                        int(schedule_e_line)
                        if schedule_e_line is not None
                        else None
                    ),
                    description=raw_txn.get("description"),
                    created_at=raw_txn.get("created_at"),
                    updated_at=raw_txn.get("updated_at"),
                )
            )

        # Assets: required fields -> cost_basis money -> recovery decimal ->
        # cross-ref.
        parsed_assets: list[BackupAsset] = []
        for raw_asset in raw_prop.get("assets") or []:
            if not isinstance(raw_asset, dict):
                return Result.failure(
                    "validation",
                    f"property {prop_id!r}: each asset must be a JSON object",
                )
            for field_name in (
                "id",
                "property_id",
                "description",
                "cost_basis",
                "placed_in_service_date",
            ):
                if _missing(raw_asset.get(field_name)):
                    return Result.failure(
                        "validation",
                        f"{_entity_label('asset', raw_asset)} is missing "
                        f"required field {field_name!r}",
                        field=field_name,
                    )

            cost_result = _parse_money(
                raw_asset["cost_basis"],
                field_name="cost_basis",
                location=f"asset {raw_asset['id']!r}",
            )
            if not cost_result.is_ok:
                return Result.failure(
                    "validation", cost_result.error.message, field="cost_basis"
                )

            recovery_raw = raw_asset.get("recovery_period_years")
            if _missing(recovery_raw):
                # Not a required field; default to the residential-rental
                # recovery period so the parsed asset carries an exact Decimal.
                recovery = DEFAULT_RECOVERY_PERIOD_YEARS
            else:
                recovery_result = _parse_plain_decimal(
                    recovery_raw,
                    field_name="recovery_period_years",
                    location=f"asset {raw_asset['id']!r}",
                )
                if not recovery_result.is_ok:
                    return Result.failure(
                        "validation",
                        recovery_result.error.message,
                        field="recovery_period_years",
                    )
                recovery = recovery_result.value

            ref = str(raw_asset["property_id"])
            if ref not in property_ids:
                return Result.failure(
                    "validation",
                    f"{_entity_label('asset', raw_asset)} references "
                    f"unknown property_id {ref!r}",
                    field="property_id",
                )

            parsed_assets.append(
                BackupAsset(
                    id=str(raw_asset["id"]),
                    property_id=ref,
                    description=str(raw_asset["description"]),
                    cost_basis=cost_result.value,
                    placed_in_service_date=str(
                        raw_asset["placed_in_service_date"]
                    ),
                    recovery_period_years=recovery,
                    created_at=raw_asset.get("created_at"),
                    updated_at=raw_asset.get("updated_at"),
                )
            )

        note = raw_prop.get("note")
        parsed_properties.append(
            BackupProperty(
                id=prop_id,
                name=str(raw_prop["name"]),
                address_text=str(raw_prop["address_text"]),
                property_type=raw_prop.get("property_type"),
                created_at=raw_prop.get("created_at"),
                updated_at=raw_prop.get("updated_at"),
                details=details,
                note=str(note) if note is not None else None,
                usage=parsed_usage,
                transactions=parsed_txns,
                assets=parsed_assets,
            )
        )

    return Result.success(
        BackupDocument(
            schema_version=str(version),
            exported_at=str(raw.get("exported_at") or ""),
            properties=parsed_properties,
        )
    )


# --- BackupService: export/restore/clear (Requirements 1, 2, 7, 8, 11, 13) ---


class BackupService:
    """Export, restore, and clear a single user's Schedule E data.

    Constructed per request from the shared wiring (mirroring the other
    services): the generic :class:`DynamoRepository`, the :class:`S3FileAdapter`
    (needed by clear and by restore's clear-first phase), and the authenticated
    user. Every read and write is scoped to that user's Cognito ``sub``
    (Requirement 11): the export read path derives its property set from the
    user's owned-property list, so a property owned by another user is never
    read or mutated (Requirement 11.3).

    ``__init__``, :meth:`export`, :meth:`restore`, and :meth:`clear` are all
    implemented here.

    Details representation on export (design "Data Models -> Backup_Document"):
    the exported ``details`` subtree is exactly the sparse, JSON-safe dict that
    :func:`details_to_dict` produces (money as two-decimal strings, coordinates
    as full-precision decimal strings, ``None``/empty values omitted). The
    router's ``_to_jsonable`` passes a plain dict straight through, so the
    serialized document matches the documented sparse shape byte-for-byte and
    re-parses cleanly through :func:`validate_document` /
    :func:`details_from_dict` on restore. We therefore set
    ``BackupProperty.details`` to that dict for export rather than to the parsed
    :class:`PropertyDetails` object: rendering the dataclass field-by-field
    would emit ``null`` for every unset field (and an empty ``features`` object),
    which is neither sparse nor a clean round-trip. The frozen dataclass is a
    plain data carrier (no runtime type enforcement), so carrying the dict here
    is safe and keeps ``details_to_dict`` the single source of truth for the
    on-wire shape.
    """

    def __init__(
        self,
        repo: "DynamoRepository",
        files: "S3FileAdapter",
        user: UserContext | str,
    ) -> None:
        self._repo = repo
        self._files = files
        self._user_id = user_id_of(user) if isinstance(user, UserContext) else user
        # Reuse the per-entity services for the read path — they already return
        # typed model objects and enforce the same user scope.
        self._properties = PropertyService(repo, self._user_id)
        self._transactions = TransactionService(repo, files)
        self._depreciation = DepreciationService(repo)

    # --- Export (Requirements 1, 11, 13) ------------------------------------

    def export(self) -> BackupDocument:
        """Read + serialize everything the authenticated user owns.

        Drives off the user's owned-property list and, for each property, reads
        its fields + details, note, usage years, transactions, and assets,
        assembling a versioned :class:`BackupDocument`. Money stays ``Decimal``
        on the dataclasses (the router renders it as two-decimal strings;
        Requirement 13.1); the details subtree is the sparse ``details_to_dict``
        output. Photos, receipts, import sessions, PDF drafts, depreciation
        schedule rows, and the category catalog are never read into the document
        (Requirements 1.8, 1.9, 1.10).
        """
        properties: list[BackupProperty] = []
        for listed in self._properties.list():
            properties.append(self._export_property(listed.id))

        return BackupDocument(
            schema_version=SCHEMA_VERSION,
            exported_at=datetime.now(timezone.utc).isoformat(),
            properties=properties,
        )

    def _export_property(self, property_id: str) -> BackupProperty:
        """Assemble one :class:`BackupProperty` from its stored children."""
        # Property fields + attached details (get() attaches the DETAILS row).
        prop_result = self._properties.get(property_id)
        prop = prop_result.value

        # Details -> sparse JSON-safe dict (see class docstring for why a dict).
        details_dict = (
            details_to_dict(prop.details) if prop.details is not None else None
        )

        # Note (empty string when none set); omit an empty note from the export.
        note_result = self._properties.get_note(property_id)
        note = note_result.value if note_result.is_ok else ""
        note = note or None

        usage = self._list_usage(property_id)

        txn_result = self._transactions.list_for_property(property_id)
        transactions = [
            BackupTransaction(
                id=txn.id,
                property_id=txn.property_id,
                date=txn.date,
                amount=txn.amount,
                type=txn.type,
                category_id=txn.category_id,
                schedule_e_line=txn.schedule_e_line,
                description=txn.description,
                created_at=txn.created_at,
                updated_at=txn.updated_at,
            )
            for txn in (txn_result.value if txn_result.is_ok else [])
        ]

        assets = [
            BackupAsset(
                id=asset.id,
                property_id=asset.property_id,
                description=asset.description,
                cost_basis=asset.cost_basis,
                placed_in_service_date=asset.placed_in_service_date,
                recovery_period_years=asset.recovery_period_years,
                created_at=asset.created_at,
                updated_at=asset.updated_at,
            )
            for asset in self._depreciation.list_assets(property_id)
        ]

        return BackupProperty(
            id=prop.id,
            name=prop.name,
            address_text=prop.address_text,
            property_type=prop.property_type,
            created_at=prop.created_at,
            updated_at=prop.updated_at,
            details=details_dict,  # type: ignore[arg-type]  # sparse dict for export
            note=note,
            usage=usage,
            transactions=transactions,
            assets=assets,
        )

    def _list_usage(self, property_id: str) -> list[BackupUsageYear]:
        """List all of a property's usage-year rows (Requirement 1.5).

        There is no list-all-usage service method (``get_usage_days`` is
        per-year), so this issues the raw ``USAGE#`` prefix query directly and
        maps each row to a :class:`BackupUsageYear`. Encapsulated here to keep
        the change scoped to this feature rather than widening the property
        service surface.
        """
        rows = self._repo.query(
            keys.property_scoped_pk(property_id),
            sk_begins_with=keys.USAGE_PREFIX,
        )
        return [
            BackupUsageYear(
                tax_year=int(row["taxYear"]),
                fair_rental_days=int(row["fairRentalDays"]),
                personal_use_days=int(row["personalUseDays"]),
            )
            for row in rows
        ]

    # --- Restore (Requirements 2, 3, 4, 5, 11, 12, 13) ----------------------

    def restore(self, raw_document: Any) -> Result[RestoreSummary]:
        """Validate, clear, then rebuild the user's data from a backup document.

        The write path preserves every ``id`` and ``created_at``/``updated_at``
        verbatim (Requirements 2.2, 2.3) and every ``property_id``
        cross-reference (Requirement 2.4), so a restored dataset is
        indistinguishable from a hand-entered one. It writes item dicts
        **directly** through the generic repository using the shared, importable
        item builders — never through a service ``create()`` (which would mint a
        fresh uuid and fresh timestamps).

        Sequencing (design "Validation model" + "Batching and the consistency
        story"):

        1. **Validate fully first** (Requirements 3.3, 3.1, 3.2, 3.4, 4.x, 5.x).
           :func:`validate_document` reads and writes nothing, so an invalid
           document returns its ``validation`` ``Result`` here with **no read
           and no write** — nothing is mutated.
        2. **Clear** all existing data (Requirement 2.1). An empty-properties
           document therefore clears and returns an empty
           :class:`RestoreSummary` (Requirement 2.6).
        3. **Write in batches** grouped by ``money_attrs`` set, each an atomic
           ``transact_write`` of ≤ :data:`_TRANSACT_MAX` actions (Requirement
           12.3). Depreciation schedule rows are always **recomputed** from the
           restored asset via :func:`compute_schedule_rows` — never read from the
           document (Requirement 2.5 / Property 4). Each transaction's
           ``schedule_e_line`` is re-resolved from its ``category_id`` against
           the current catalog, never trusted from the document.

        Consistency (Requirement 12): true all-or-nothing across batches is not
        possible on DynamoDB, so the guarantee is *validate-then-replace with a
        retry signal*: a malformed document never begins a clear, and a failure
        during the write phase (after the clear) is caught and surfaced as a
        **retryable** ``conflict`` error stating the restore did not complete and
        the store may be incomplete, so the user can retry (Requirement 12.2 /
        Property 9). A retry re-clears then re-writes, so a partial write from a
        failed attempt is wiped by the next attempt's clear.
        """
        # 1. Validate fully before any read or write (Requirement 3.3).
        validated = validate_document(raw_document)
        if not validated.is_ok:
            # No store access has occurred; nothing is mutated (3.1, 3.2, 3.4,
            # 4.1, 4.2, 5.1, 5.2).
            return Result(error=validated.error)
        document = validated.value

        # 2. Replace-all: remove everything the user owns first (Requirement
        #    2.1). A clear failure here is before any new write, so the store is
        #    simply the pre-existing data — surface it as a retryable error too.
        clear_result = self.clear()
        if not clear_result.is_ok:
            return Result(error=clear_result.error)

        # Empty-properties document: clear() already ran; return an empty
        # summary with no writes (Requirement 2.6).
        if not document.properties:
            return Result.success(
                RestoreSummary(
                    properties=0, transactions=0, assets=0, usage_years=0
                )
            )

        # 3. Build the write set, bucketed by money-attr group so no single
        #    transact_write mixes entities with conflicting money contracts.
        #    Each bucket carries (item dict, money_attrs) and is flushed in
        #    ≤ _TRANSACT_MAX-action batches.
        no_money: list[dict[str, Any]] = []  # property rows, details, note, usage
        txn_items: list[dict[str, Any]] = []  # money_attrs: default (amount)
        asset_items: list[dict[str, Any]] = []  # money_attrs: {costBasis}
        sched_items: list[dict[str, Any]] = []  # money_attrs: {amount, remainingBasis}

        property_count = 0
        transaction_count = 0
        asset_count = 0
        usage_year_count = 0

        for prop in document.properties:
            property_count += 1

            # Property list row + META mirror (ids/timestamps preserved, scoped
            # to the authenticated user). GSI1 keys emitted by the builder.
            restored_property = Property(
                id=prop.id,
                user_id=self._user_id,
                name=prop.name,
                address_text=prop.address_text,
                property_type=prop.property_type,
                created_at=prop.created_at,
                updated_at=prop.updated_at,
            )
            no_money.extend(property_to_rows(restored_property))

            # Details row (money inside the JSON; no top-level money attrs).
            if prop.details is not None:
                no_money.append(
                    property_details_row(self._user_id, prop.id, prop.details)
                )

            # Note row (only when set).
            if prop.note is not None:
                no_money.append(
                    property_note_row(
                        self._user_id,
                        prop.id,
                        prop.note,
                        prop.updated_at or "",
                    )
                )

            # Usage-year rows.
            for usage in prop.usage:
                usage_year_count += 1
                no_money.append(
                    property_usage_row(
                        prop.id,
                        usage.tax_year,
                        usage.fair_rental_days,
                        usage.personal_use_days,
                    )
                )

            # Transactions: re-resolve the Schedule E line from the category
            # catalog by category_id (never trust an embedded value), preserve
            # id/timestamps, and emit base + GSI2 tax-year keys via the builder.
            for txn in prop.transactions:
                transaction_count += 1
                category = category_by_id(txn.category_id)
                # validate_document already rejected any unknown category, so a
                # match is guaranteed here; fall back defensively just in case.
                schedule_e_line = (
                    category.schedule_e_line
                    if category is not None
                    else (txn.schedule_e_line or 0)
                )
                restored_txn = Transaction(
                    id=txn.id,
                    property_id=txn.property_id,
                    date=txn.date,
                    amount=txn.amount,
                    type=txn.type,  # type: ignore[arg-type]
                    category_id=txn.category_id,
                    schedule_e_line=schedule_e_line,
                    description=txn.description,
                    created_at=txn.created_at,
                    updated_at=txn.updated_at,
                )
                txn_date = datetime.strptime(txn.date, _DATE_FMT).date()
                txn_items.append(transaction_to_item(restored_txn, txn_date))

            # Assets: preserve id/timestamps, then RECOMPUTE the depreciation
            # schedule from the restored asset (Requirement 2.5) — schedule rows
            # are never read from the document.
            for asset in prop.assets:
                asset_count += 1
                restored_asset = DepreciableAsset(
                    id=asset.id,
                    property_id=asset.property_id,
                    description=asset.description,
                    cost_basis=asset.cost_basis,
                    placed_in_service_date=asset.placed_in_service_date,
                    recovery_period_years=asset.recovery_period_years,
                    created_at=asset.created_at,
                    updated_at=asset.updated_at,
                )
                asset_items.append(asset_to_item(restored_asset))
                for row in compute_schedule_rows(restored_asset):
                    sched_items.append(schedule_row_to_item(row))

        # Flush each money-attr group in ≤ _TRANSACT_MAX-action batches. A
        # repository failure mid-write (after the clear) is caught and surfaced
        # as a retryable error (Requirement 12.2 / Property 9): we do NOT claim
        # false all-or-nothing across batches.
        write_groups: list[tuple[list[dict[str, Any]], Iterable[str] | None]] = [
            (no_money, set()),
            (txn_items, None),  # default money attrs (amount)
            (asset_items, {"costBasis"}),
            (sched_items, {"amount", "remainingBasis"}),
        ]
        try:
            for items, money_attrs in write_groups:
                for start in range(0, len(items), self._TRANSACT_MAX):
                    batch = items[start : start + self._TRANSACT_MAX]
                    self._repo.transact_write(
                        [{"put": item} for item in batch],
                        money_attrs=money_attrs,
                    )
        except Exception as exc:  # noqa: BLE001 — surface as a retryable error
            return Result.failure(
                "conflict",
                "The restore did not complete after clearing existing data; "
                "your stored data may be incomplete. Please retry the restore "
                f"({exc}).",
            )

        return Result.success(
            RestoreSummary(
                properties=property_count,
                transactions=transaction_count,
                assets=asset_count,
                usage_years=usage_year_count,
            )
        )

    # --- Clear (Requirements 7, 8, 11) --------------------------------------

    #: DynamoDB caps ``TransactWriteItems`` at 100 actions per call, so row
    #: deletes are chunked into batches no larger than this.
    _TRANSACT_MAX = 100

    def clear(self) -> Result[ClearSummary]:
        """Delete everything the authenticated user owns (Requirements 7, 8).

        Enumerates the user's owned properties (Requirement 11.3: the set is
        derived from the owned-property list, so no other user's data is ever
        touched) and, per property partition, reads every child row once and
        removes it. S3 binaries are purged **first**, then DynamoDB rows are
        deleted bottom-up (children before the property META mirror and the
        ``USER#/PROP#`` list row) in atomic ``transact_write`` batches of at
        most :data:`_TRANSACT_MAX` actions.

        Ordering guarantees:

        * Each receipt/photo S3 object is deleted **before** its metadata row
          (Requirement 8.3); a crash between the two leaves at worst an orphaned
          metadata row pointing at an already-deleted (idempotent) key, never an
          orphaned S3 object.
        * A property's children are deleted **before** its META/list rows
          (Requirement 8.5).

        S3 deletion is best-effort: an individual ``delete_object`` failure is
        recorded in :attr:`ClearSummary.failed_s3_keys` and the clear continues
        rather than aborting (Requirement 8.4).

        Idempotent: clearing an already-empty store issues no writes and returns
        an empty summary. Returns a populated :class:`ClearSummary`.
        """
        # Batched deletes accumulated in bottom-up order (children first, then
        # each property's META + list rows appended last per property).
        delete_actions: list[dict[str, Any]] = []

        properties = self._properties.list()
        property_count = 0
        transaction_count = 0
        asset_count = 0
        photo_count = 0
        receipt_count = 0
        failed_s3_keys: list[str] = []

        for listed in properties:
            property_count += 1
            property_id = listed.id
            pk = keys.property_scoped_pk(property_id)

            # Read every child row of the partition once (no SK prefix), then
            # bucket by kind. Query results carry PK/SK, so each row can be
            # turned straight into a delete action.
            rows = self._repo.query(pk)

            child_actions: list[dict[str, Any]] = []
            for row in rows:
                sk = str(row["SK"])

                # The property's own META mirror is a parent row; defer it so it
                # is deleted after all children (Requirement 8.5).
                if sk == keys.META_SK:
                    continue

                # Receipt rows (TXN#…#DOC#…) and photo rows carry an S3 binary
                # that must be purged before the metadata row is removed.
                is_receipt = keys.DOC_PREFIX in sk
                is_photo = sk.startswith(keys.PHOTO_PREFIX)

                if is_receipt or is_photo:
                    s3_key = row.get("s3Key")
                    if s3_key:
                        # S3 purge FIRST (Requirement 8.3), best-effort: a single
                        # failed object never aborts the clear (Requirement 8.4).
                        try:
                            self._files.delete_object(str(s3_key))
                        except Exception:  # noqa: BLE001 — best-effort cleanup
                            failed_s3_keys.append(str(s3_key))
                    if is_receipt:
                        receipt_count += 1
                    else:
                        photo_count += 1
                elif sk.startswith(keys.TXN_PREFIX):
                    # A base TXN row (receipt DOC rows were caught above).
                    transaction_count += 1
                elif sk.startswith(keys.ASSET_PREFIX) and keys.SCHED_PREFIX not in sk:
                    # A base ASSET row (its SCHED# rows are children, not counted).
                    asset_count += 1

                child_actions.append({"delete": {"pk": pk, "sk": sk}})

            # Children first, then this property's META mirror and its
            # USER#/PROP# list row (Requirement 8.5).
            delete_actions.extend(child_actions)
            delete_actions.append(
                {"delete": {"pk": pk, "sk": keys.property_meta_sk()}}
            )
            delete_actions.append(
                {
                    "delete": {
                        "pk": keys.user_pk(self._user_id),
                        "sk": keys.property_user_sk(property_id),
                    }
                }
            )

        # Flush the accumulated deletes in ≤ 100-action batches (Requirement
        # 12.3). Order is preserved so children precede their parent rows.
        for start in range(0, len(delete_actions), self._TRANSACT_MAX):
            batch = delete_actions[start : start + self._TRANSACT_MAX]
            self._repo.transact_write(batch)

        return Result.success(
            ClearSummary(
                properties=property_count,
                transactions=transaction_count,
                assets=asset_count,
                photos=photo_count,
                receipts=receipt_count,
                failed_s3_keys=failed_s3_keys,
            )
        )
