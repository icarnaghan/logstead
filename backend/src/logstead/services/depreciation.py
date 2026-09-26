"""Depreciation Service: depreciable-asset CRUD (Requirement 8).

This module owns the lifecycle of :class:`DepreciableAsset` items — create,
list, get, update, and delete — scoped under a property, plus the correctness-
critical straight-line + mid-month **schedule engine** (Requirements 9.1-9.5).

Schedule materialization strategy
---------------------------------
Schedules are **materialized** in DynamoDB rather than computed on demand: on
:meth:`DepreciationService.create_asset` and
:meth:`DepreciationService.update_asset` the schedule is (re)computed and its
rows are (re)written under ``ASSET#<assetId>#SCHED#<taxYear>`` inside a single
transaction, and :meth:`DepreciationService.delete_asset` cascade-deletes them.
This keeps delete atomic and consistent with task 11.1, and lets the Schedule E
report read a property's per-year depreciation with one GSI2 tax-year query
(:meth:`DepreciationService.property_depreciation_for_year`) instead of
recomputing across assets. The math itself lives in the module-level **pure**
function :func:`compute_schedule_rows` (a function of the asset alone) so the
Property 17-19 tests can exercise it directly without a repository; the service
just persists what it returns.

Scope and identity
------------------
Assets live under their owning property's partition (``PK=PROPERTY#<propertyId>``,
``SK=ASSET#<assetId>`` — see :mod:`logstead.repository.keys`). Every operation
takes the ``property_id`` explicitly rather than resolving it from a property
service, so this module has no dependency on the (concurrently written)
property service. Callers (the router) are responsible for having already
scoped the ``property_id`` to the authenticated user.

Storage of the recovery period
-------------------------------
``costBasis`` is money and is stored as a fixed two-decimal string through the
repository's money handling (``costBasis`` is in
:data:`logstead.repository.dynamo_repo.DEFAULT_MONEY_ATTRS`).

``recoveryPeriodYears`` is **not** money — it is a period like ``27.5`` or
``5`` years and must not be forced to two-decimal money quantization (``27.50``
would be misleading, and periods such as ``39`` are whole numbers). It is
therefore stored as a plain ``Decimal`` string via ``str(Decimal)`` (which
never emits scientific notation for these small values) and parsed straight
back with ``Decimal(...)``. To keep it out of the money serializer, every
read/write here passes an explicit ``money_attrs={"costBasis"}`` so only the
cost basis is treated as money.

Validation (Requirements 8.2, 8.3)
----------------------------------
* ``property_id``, ``description``, ``cost_basis``, and
  ``placed_in_service_date`` are required; a missing one yields a
  ``validation`` failure whose ``field`` identifies the offending input
  (Requirement 8.3).
* ``cost_basis`` must be greater than zero after money coercion; ``<= 0`` is a
  ``validation`` failure on ``cost_basis`` (Requirement 8.2).
* ``recovery_period_years`` defaults to ``27.5`` when unspecified
  (Requirement 8.4) and, when provided, must be greater than zero.
"""

from __future__ import annotations

import math
import uuid
from datetime import datetime, timezone
from decimal import Decimal, InvalidOperation
from typing import Any

from logstead.models.depreciation import (
    DEFAULT_RECOVERY_PERIOD_YEARS,
    AssetInput,
    DepreciableAsset,
    DepreciationScheduleRow,
)
from logstead.models.result import Result
from logstead.repository import keys
from logstead.repository.dynamo_repo import DynamoRepository
from logstead.util.money import Money, to_money

__all__ = ["DepreciationService", "compute_schedule_rows"]

# Only the cost basis is money for asset items. The recovery period is a plain
# Decimal period (e.g. 27.5, 5, 39) and must not be money-quantized, so every
# asset read/write narrows the money set to just ``costBasis``.
_ASSET_MONEY_ATTRS: frozenset[str] = frozenset({"costBasis"})

# Schedule-row money attributes: both the per-year amount and the remaining
# basis are two-decimal money strings.
_SCHEDULE_MONEY_ATTRS: frozenset[str] = frozenset({"amount", "remainingBasis"})

_SCHED_MARKER = f"#{keys.SCHED_PREFIX}"  # "#SCHED#" — marks schedule-row SKs.


def _now_iso() -> str:
    """Current UTC time as an ISO-8601 timestamp (second precision, ``Z``)."""
    return datetime.now(timezone.utc).replace(microsecond=0).isoformat()


def _new_id() -> str:
    """Generate a fresh asset identifier."""
    return uuid.uuid4().hex


# --- Pure schedule engine (Requirements 9.1-9.4) ----------------------------
#
# This is deliberately a module-level *pure* function of the asset alone, so
# the correctness-critical math (Properties 17-19) can be tested directly with
# Hypothesis without a repository or DynamoDB in the loop. The service methods
# below call it to materialize schedule rows.

# Twelve months, used for the mid-month first-year proration.
_MONTHS_PER_YEAR = Decimal("12")
# Half of the placed-in-service month is counted (mid-month convention): an
# asset placed in month M is treated as in service at the middle of month M, so
# the first year covers (12 - M) whole months plus half of month M, i.e.
# (12 - M + 0.5) months == (12.5 - M) months.
_MID_MONTH_OFFSET = Decimal("12.5")


def compute_schedule_rows(asset: DepreciableAsset) -> list[DepreciationScheduleRow]:
    """Compute the straight-line + mid-month depreciation schedule for an asset.

    Straight-line: the full-year depreciation is ``cost_basis /
    recovery_period_years``. The **mid-month convention** treats the asset as
    placed in service at the midpoint of its placed-in-service month ``M``, so
    the first tax year is prorated by ``(12.5 - M) / 12`` (a full month for each
    month after ``M``, plus half of month ``M``). Because the first year is
    partial, recovery spills into one extra tax year: the schedule spans
    ``ceil(recovery_period_years) + 1`` tax years, and the final (partial) year
    absorbs whatever basis remains.

    Precision (Requirements 9.3, 9.4): amounts are two-decimal ``Decimal``. The
    schedule is built from the *ideal* (unrounded) cumulative depreciation at
    the end of each year, quantized to money; each year's amount is the
    difference of consecutive quantized cumulatives. The final year's cumulative
    is pinned to the exact cost basis, so the per-year amounts sum to the cost
    basis **exactly** and each ``remaining_basis`` (= cost_basis - cumulative)
    is non-increasing down to exactly ``0.00``.

    Args:
        asset: The asset to schedule. ``cost_basis`` must be positive and
            ``recovery_period_years`` must be positive; both are guaranteed by
            :class:`DepreciationService` validation.

    Returns:
        One :class:`DepreciationScheduleRow` per tax year, in ascending
        tax-year order, starting at the placed-in-service year.
    """
    cost_basis = to_money(asset.cost_basis)
    recovery = Decimal(str(asset.recovery_period_years))

    placed = datetime.strptime(asset.placed_in_service_date, "%Y-%m-%d").date()
    first_year = placed.year
    month = Decimal(placed.month)

    # First-year mid-month proration fraction of a full year.
    first_fraction = (_MID_MONTH_OFFSET - month) / _MONTHS_PER_YEAR

    annual = cost_basis / recovery

    # Number of tax years: whole recovery years rounded up, plus one partial
    # tail year to recover the mid-month remainder. e.g. 27.5 -> 29 rows, 5 -> 6.
    num_years = math.ceil(recovery) + 1

    # Ideal (unrounded) cumulative depreciation at the END of each tax year.
    # Year 0 accrues the mid-month-prorated first year; each subsequent year
    # accrues a full annual amount until the basis is exhausted. The last row's
    # cumulative is pinned to the exact cost basis so rounding never drifts.
    cumulative_ideal: list[Decimal] = []
    running = annual * first_fraction
    for i in range(num_years):
        if i == num_years - 1:
            cumulative_ideal.append(cost_basis)
        else:
            # Cap at cost_basis defensively; the tail year still pins to exact.
            cumulative_ideal.append(min(running, cost_basis))
            running += annual

    rows: list[DepreciationScheduleRow] = []
    prev_cum_money = Decimal("0.00")
    for i in range(num_years):
        if i == num_years - 1:
            cum_money = cost_basis  # already two decimals from to_money
        else:
            cum_money = to_money(cumulative_ideal[i])
            # Never let a rounding bump push cumulative past the basis.
            if cum_money > cost_basis:
                cum_money = cost_basis
        amount = cum_money - prev_cum_money
        remaining = cost_basis - cum_money
        rows.append(
            DepreciationScheduleRow(
                asset_id=asset.id,
                property_id=asset.property_id,
                tax_year=first_year + i,
                amount=amount,
                remaining_basis=remaining,
            )
        )
        prev_cum_money = cum_money

    return rows


class DepreciationService:
    """CRUD + schedule engine for depreciable assets under a property (Reqs 8, 9).

    Owns asset create/list/get/update/delete and the straight-line + mid-month
    schedule engine. :meth:`compute_schedule` wraps the pure
    :func:`compute_schedule_rows` engine; create/update materialize the rows
    and delete cascades them.
    """

    def __init__(self, repo: DynamoRepository) -> None:
        self._repo = repo

    # --- Serialization boundary ---------------------------------------------

    def _to_item(self, asset: DepreciableAsset) -> dict[str, Any]:
        """Render an asset as its DynamoDB item (design camelCase attributes).

        ``costBasis`` is left as a ``Decimal`` for the repository's money
        serializer to render as a two-decimal string. ``recoveryPeriodYears``
        is stored as a plain ``Decimal`` string (not money) so periods keep
        their natural precision.
        """
        return {
            "PK": keys.property_scoped_pk(asset.property_id),
            "SK": keys.asset_sk(asset.id),
            "id": asset.id,
            "propertyId": asset.property_id,
            "description": asset.description,
            "costBasis": asset.cost_basis,
            "placedInServiceDate": asset.placed_in_service_date,
            "recoveryPeriodYears": str(asset.recovery_period_years),
            "createdAt": asset.created_at,
            "updatedAt": asset.updated_at,
        }

    def _from_item(self, item: dict[str, Any]) -> DepreciableAsset:
        """Reconstruct an asset from a stored item.

        ``costBasis`` comes back as a ``Decimal`` (money-parsed by the repo);
        ``recoveryPeriodYears`` is parsed from its plain string back to a
        ``Decimal``.
        """
        return DepreciableAsset(
            id=str(item["id"]),
            property_id=str(item["propertyId"]),
            description=str(item["description"]),
            cost_basis=to_money(item["costBasis"]),
            placed_in_service_date=str(item["placedInServiceDate"]),
            recovery_period_years=Decimal(str(item["recoveryPeriodYears"])),
            created_at=item.get("createdAt"),
            updated_at=item.get("updatedAt"),
        )

    # --- Validation ----------------------------------------------------------

    @staticmethod
    def _coerce_cost_basis(raw: Decimal | None) -> Result[Money]:
        """Validate a cost basis: required and strictly greater than zero (8.2, 8.3)."""
        if raw is None:
            return Result.failure(
                "validation", "Cost basis is required.", field="cost_basis"
            )
        try:
            cost_basis = to_money(raw)
        except (TypeError, ValueError, InvalidOperation):
            return Result.failure(
                "validation", "Cost basis is not a valid amount.", field="cost_basis"
            )
        if cost_basis <= Decimal("0"):
            return Result.failure(
                "validation",
                "Cost basis must be greater than zero.",
                field="cost_basis",
            )
        return Result.success(cost_basis)

    @staticmethod
    def _coerce_recovery_period(raw: Decimal | None) -> Result[Decimal]:
        """Default the recovery period to 27.5 and require it to be positive (8.3, 8.4)."""
        if raw is None:
            # Requirement 8.4: 27.5 years is the default for residential rental.
            return Result.success(DEFAULT_RECOVERY_PERIOD_YEARS)
        try:
            years = Decimal(str(raw))
        except (InvalidOperation, ValueError):
            return Result.failure(
                "validation",
                "Recovery period is not a valid number of years.",
                field="recovery_period_years",
            )
        if not years.is_finite() or years <= Decimal("0"):
            return Result.failure(
                "validation",
                "Recovery period must be greater than zero.",
                field="recovery_period_years",
            )
        return Result.success(years)

    def _validate(self, data: AssetInput) -> Result[dict[str, Any]]:
        """Validate an asset input into normalized field values (8.2, 8.3, 8.4).

        Returns a success carrying ``{"property_id", "description",
        "cost_basis", "placed_in_service_date", "recovery_period_years"}`` or
        the first field-identifying validation failure.
        """
        property_id = (data.property_id or "").strip()
        if not property_id:
            return Result.failure(
                "validation", "Property is required.", field="property_id"
            )

        description = (data.description or "").strip()
        if not description:
            return Result.failure(
                "validation", "Description is required.", field="description"
            )

        placed = (data.placed_in_service_date or "").strip()
        if not placed:
            return Result.failure(
                "validation",
                "Placed-in-service date is required.",
                field="placed_in_service_date",
            )

        cost_result = self._coerce_cost_basis(data.cost_basis)
        if not cost_result.is_ok:
            return Result(error=cost_result.error)

        period_result = self._coerce_recovery_period(data.recovery_period_years)
        if not period_result.is_ok:
            return Result(error=period_result.error)

        return Result.success(
            {
                "property_id": property_id,
                "description": description,
                "cost_basis": cost_result.value,
                "placed_in_service_date": placed,
                "recovery_period_years": period_result.value,
            }
        )

    # --- Schedule engine seam (task 11.2) -----------------------------------

    def compute_schedule(
        self, asset: DepreciableAsset
    ) -> list[DepreciationScheduleRow]:
        """Compute the straight-line + mid-month schedule for an asset (9.1-9.3).

        Thin instance-level wrapper over the pure :func:`compute_schedule_rows`
        engine. Kept as a method so the service and its callers have a stable
        seam; the math itself lives in the module-level pure function so the
        property tests can exercise it directly.
        """
        return compute_schedule_rows(asset)

    # --- Schedule-row storage helpers ---------------------------------------

    def _schedule_row_item(self, row: DepreciationScheduleRow) -> dict[str, Any]:
        """Render one schedule row as its DynamoDB item.

        Schedule rows live under the owning property's partition, keyed
        ``ASSET#<assetId>#SCHED#<taxYear>``, and carry a GSI2 tax-year partition
        (``PROPERTY#<id>#YEAR#<taxYear>`` / ``SCHED#<assetId>``) so a property's
        per-year depreciation can be read with a single GSI2 query.
        """
        return {
            "PK": keys.property_scoped_pk(row.property_id),
            "SK": keys.schedule_row_sk(row.asset_id, row.tax_year),
            "GSI2PK": keys.gsi2_year_pk(row.property_id, row.tax_year),
            "GSI2SK": keys.gsi2_schedule_sk(row.asset_id),
            "assetId": row.asset_id,
            "propertyId": row.property_id,
            "taxYear": row.tax_year,
            "amount": row.amount,
            "remainingBasis": row.remaining_basis,
            "method": row.method,
            "convention": row.convention,
        }

    def _schedule_row_from_item(
        self, item: dict[str, Any]
    ) -> DepreciationScheduleRow:
        """Reconstruct a schedule row from a stored item."""
        return DepreciationScheduleRow(
            asset_id=str(item["assetId"]),
            property_id=str(item["propertyId"]),
            tax_year=int(item["taxYear"]),
            amount=to_money(item["amount"]),
            remaining_basis=to_money(item["remainingBasis"]),
            method=str(item.get("method", "straight_line")),
            convention=str(item.get("convention", "mid_month")),
        )

    def _existing_schedule_sks(self, property_id: str, asset_id: str) -> set[str]:
        """Sort keys of all currently materialized schedule rows of an asset."""
        rows = self._repo.query(
            keys.property_scoped_pk(property_id),
            sk_begins_with=keys.schedule_list_prefix(asset_id),
            money_attrs=_SCHEDULE_MONEY_ATTRS,
        )
        return {
            row["SK"] for row in rows if isinstance(row.get("SK"), str)
        }

    def _existing_schedule_actions(
        self, property_id: str, asset_id: str
    ) -> list[dict[str, Any]]:
        """Delete-actions for all currently materialized rows of an asset."""
        pk = keys.property_scoped_pk(property_id)
        return [
            {"delete": {"pk": pk, "sk": sk}}
            for sk in self._existing_schedule_sks(property_id, asset_id)
        ]

    def _materialize_schedule(self, asset: DepreciableAsset) -> None:
        """(Re)write an asset's schedule rows atomically (Requirements 9.1, 8.5).

        Puts the freshly computed rows (a put replaces any row with the same
        tax-year SK) and deletes only the *stale* prior rows whose tax year no
        longer appears in the new schedule. Overlapping SKs are handled by the
        put alone: a single ``TransactWriteItems`` cannot both delete and put
        the same item key, so a recompute after an edit fully replaces the prior
        schedule with no stale years left behind and no duplicate-key conflict.
        """
        pk = keys.property_scoped_pk(asset.property_id)
        new_rows = compute_schedule_rows(asset)
        new_sks = {
            keys.schedule_row_sk(asset.id, row.tax_year) for row in new_rows
        }

        actions: list[dict[str, Any]] = [
            {"put": self._schedule_row_item(row)} for row in new_rows
        ]
        stale = self._existing_schedule_sks(asset.property_id, asset.id) - new_sks
        actions.extend({"delete": {"pk": pk, "sk": sk}} for sk in stale)

        self._repo.transact_write(actions, money_attrs=_SCHEDULE_MONEY_ATTRS)

    def schedule_for(
        self, property_id: str, asset_id: str
    ) -> list[DepreciationScheduleRow]:
        """Return an asset's materialized schedule rows, oldest year first (9.4).

        Reads the persisted rows under the asset's ``SCHED#`` prefix and returns
        them sorted by tax year so callers get the year-by-year amount and
        remaining basis in order.
        """
        rows = self._repo.query(
            keys.property_scoped_pk(property_id),
            sk_begins_with=keys.schedule_list_prefix(asset_id),
            money_attrs=_SCHEDULE_MONEY_ATTRS,
        )
        parsed = [self._schedule_row_from_item(r) for r in rows]
        parsed.sort(key=lambda r: r.tax_year)
        return parsed

    def property_depreciation_for_year(
        self, property_id: str, tax_year: int
    ) -> Money:
        """Total depreciation for a property in a tax year (Requirement 9.5).

        Sums the scheduled ``amount`` of every asset's schedule row for the
        given tax year, via the GSI2 tax-year partition, and returns the
        two-decimal total. This is the per-(property, year) figure the Schedule
        E report consumes for Line 18 (Requirement 10.3). Returns ``0.00`` when
        no asset has depreciation in that year.
        """
        rows = self._repo.query(
            keys.gsi2_year_pk(property_id, tax_year),
            sk_begins_with=keys.gsi2_schedule_prefix(),
            index_name="GSI2",
            money_attrs=_SCHEDULE_MONEY_ATTRS,
        )
        total = Decimal("0.00")
        for row in rows:
            total += to_money(row["amount"])
        return to_money(total)

    # --- CRUD ----------------------------------------------------------------

    def create_asset(self, data: AssetInput) -> Result[DepreciableAsset]:
        """Create a depreciable asset under a property (Requirements 8.1-8.4).

        Validates required fields and a positive cost basis, defaults the
        recovery period to 27.5 years when unspecified, generates an id and
        timestamps, and persists the asset (cost basis as a money string).
        """
        validated = self._validate(data)
        if not validated.is_ok:
            return Result(error=validated.error)
        fields = validated.value

        now = _now_iso()
        asset = DepreciableAsset(
            id=_new_id(),
            property_id=fields["property_id"],
            description=fields["description"],
            cost_basis=fields["cost_basis"],
            placed_in_service_date=fields["placed_in_service_date"],
            recovery_period_years=fields["recovery_period_years"],
            created_at=now,
            updated_at=now,
        )
        self._repo.put_item(self._to_item(asset), money_attrs=_ASSET_MONEY_ATTRS)
        # Requirement 9.1: compute and materialize the schedule on create.
        self._materialize_schedule(asset)
        return Result.success(asset)

    def list_assets(self, property_id: str) -> list[DepreciableAsset]:
        """List all depreciable assets for a property (Requirement 8.7).

        Assets and their schedule rows share the ``ASSET#`` sort-key prefix
        (``ASSET#<id>`` vs ``ASSET#<id>#SCHED#<year>``), so this filters out
        any item whose SK carries the ``#SCHED#`` marker and returns only the
        asset rows.
        """
        items = self._repo.query(
            keys.property_scoped_pk(property_id),
            sk_begins_with=keys.asset_list_prefix(),
            money_attrs=_ASSET_MONEY_ATTRS,
        )
        return [
            self._from_item(item)
            for item in items
            if _SCHED_MARKER not in str(item.get("SK", ""))
        ]

    def get_asset(
        self, property_id: str, asset_id: str
    ) -> Result[DepreciableAsset]:
        """Fetch one asset, or a ``not_found`` failure if it is absent."""
        item = self._repo.get_item(
            keys.property_scoped_pk(property_id),
            keys.asset_sk(asset_id),
            money_attrs=_ASSET_MONEY_ATTRS,
        )
        if item is None:
            return Result.failure(
                "not_found", "Depreciable asset not found.", field="asset_id"
            )
        return Result.success(self._from_item(item))

    def update_asset(
        self, property_id: str, asset_id: str, data: AssetInput
    ) -> Result[DepreciableAsset]:
        """Update an asset's mutable fields (Requirement 8.5).

        Re-validates the input (same rules as create), preserves the asset's
        id, property, and created-at timestamp, refreshes ``updated_at``, and
        persists the change. Recomputing the schedule is deferred to task 11.2
        via :meth:`compute_schedule`.
        """
        existing = self.get_asset(property_id, asset_id)
        if not existing.is_ok:
            return existing
        current = existing.value

        validated = self._validate(data)
        if not validated.is_ok:
            return Result(error=validated.error)
        fields = validated.value

        updated = DepreciableAsset(
            id=current.id,
            property_id=current.property_id,
            description=fields["description"],
            cost_basis=fields["cost_basis"],
            placed_in_service_date=fields["placed_in_service_date"],
            recovery_period_years=fields["recovery_period_years"],
            created_at=current.created_at,
            updated_at=_now_iso(),
        )
        self._repo.put_item(self._to_item(updated), money_attrs=_ASSET_MONEY_ATTRS)
        # Requirement 8.5 / 9.1: recompute and rewrite the schedule on update.
        self._materialize_schedule(updated)
        return Result.success(updated)

    def delete_asset(self, property_id: str, asset_id: str) -> Result[None]:
        """Delete an asset and any materialized schedule rows (Requirement 8.6).

        The schedule engine (task 11.2) is what materializes schedule rows;
        until then none exist, but this deletes any present schedule rows under
        the asset's ``ASSET#<id>#SCHED#`` prefix together with the asset row in
        a single atomic transaction so the delete stays all-or-nothing.
        """
        existing = self.get_asset(property_id, asset_id)
        if not existing.is_ok:
            return existing

        pk = keys.property_scoped_pk(property_id)
        actions: list[dict[str, Any]] = [
            {"delete": {"pk": pk, "sk": keys.asset_sk(asset_id)}}
        ]

        actions.extend(self._existing_schedule_actions(property_id, asset_id))

        self._repo.transact_write(actions, money_attrs=_ASSET_MONEY_ATTRS)
        return Result.success(None)
