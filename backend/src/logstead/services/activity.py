"""Activity history: best-effort recording of mutations.

``ActivityRecorder`` writes one ``ACT#`` item per event under the user's
partition (plus GSI1 keys when the event has a property). It never raises:
a lost log line is cheaper than a failed save (design.md, "Where to record").
"""
from __future__ import annotations

import json
import logging
import uuid
import re
from collections.abc import Callable, Mapping
from dataclasses import dataclass
from datetime import datetime, timedelta, timezone
from decimal import Decimal, InvalidOperation
from typing import Any, Final

from logstead.models.result import Result
from logstead.repository import keys
from logstead.repository.dynamo_repo import ConditionFailed
from logstead.services import activity_events as ev
from logstead.services.activity_config import ACTIVITY_CONFIG, ActivityConfig
from logstead.util.logsafe import exc_summary

__all__ = [
    "ActivityEvent",
    "ActivityPage",
    "ActivityRecorder",
    "ActivityService",
    "NewEvent",
    "RestoreOutcome",
]

logger = logging.getLogger(__name__)

ENTITY_TYPE: Final = "ACTIVITY"
_BATCH: Final = 25
_NAME_MAX: Final = 200
READ_CAP: Final = 2000
CLAIM_STALE: Final = timedelta(minutes=5)
PENDING: Final = "pending"
ENTITIES: Final = frozenset(
    {"transaction", "itemized_entry", "asset", "loan", "property", "backup", "schedule_e"}
)
ACTIONS: Final = frozenset({"create", "update", "delete", "restore", "import"})
_EVENT_ID_RE: Final = re.compile(r"^\d{14}\.[0-9A-Za-z-]{1,64}$")
_PROPERTY_NOT_FOUND: Final = "Property not found."
_EVENT_NOT_FOUND: Final = "Activity event not found."


def _utcnow() -> datetime:
    return datetime.now(timezone.utc)


def _iso_millis(at: datetime) -> str:
    if at.tzinfo is None:
        at = at.replace(tzinfo=timezone.utc)
    at = at.astimezone(timezone.utc)
    return at.strftime("%Y-%m-%dT%H:%M:%S.") + f"{at.microsecond // 1000:03d}Z"


def _dumps(values: Mapping[str, Any]) -> str:
    return json.dumps(values, ensure_ascii=False, separators=(",", ":"))


@dataclass(frozen=True)
class NewEvent:
    """What a handler hands the recorder. ``before``/``after`` are already
    allow-listed (see ``activity_events.project``/``diff``); the recorder bounds them."""

    action: str
    entity: str
    summary: str
    record_id: str | None = None
    property_id: str | None = None
    property_name: str | None = None
    before: Mapping[str, Any] | None = None
    after: Mapping[str, Any] | None = None
    restorable: bool = False
    restore_payload: Mapping[str, Any] | None = None
    truncated: bool = False


class ActivityRecorder:
    """Best-effort writer and purger of the user's activity events."""

    def __init__(
        self,
        repo: Any,
        user_id: str,
        clock: Callable[[], datetime] = _utcnow,
        config: ActivityConfig = ACTIVITY_CONFIG,
        log: logging.Logger = logger,
    ) -> None:
        self._repo = repo
        self._user_id = user_id
        self._clock = clock
        self._cfg = config
        self._log = log

    # --- Recording -----------------------------------------------------------

    def record(self, event: NewEvent) -> None:
        """Write one event. Catches every exception, logs a warning, returns."""
        try:
            self._repo.put_item(self._build(event))
        except Exception as exc:  # noqa: BLE001 - recording must never fail the primary operation
            try:
                self._log.warning(
                    "activity_record_failed action=%s entity=%s error=%s",
                    getattr(event, "action", None),
                    getattr(event, "entity", None),
                    exc_summary(exc),
                )
            except Exception:  # noqa: BLE001
                pass

    def _build(self, event: NewEvent) -> dict[str, Any]:
        cfg = self._cfg
        at = self._clock()
        event_id = str(uuid.uuid4())
        sk = ev.event_sk(at, event_id)
        item: dict[str, Any] = {
            "PK": keys.user_pk(self._user_id),
            "SK": sk,
            "entityType": ENTITY_TYPE,
            "eventId": event_id,
            "at": _iso_millis(at),
            "action": event.action,
            "entity": event.entity,
            "summary": ev._clip(event.summary, cfg.summary_max_chars),
            "ttl": ev.ttl_for(at, cfg),
        }
        if event.property_id is not None:
            item["propertyId"] = event.property_id
            item["GSI1PK"] = keys.activity_gsi1_pk(event.property_id)
            item["GSI1SK"] = sk
        if event.property_name is not None:
            item["propertyName"] = event.property_name[:_NAME_MAX]
        if event.record_id is not None:
            item["recordId"] = event.record_id

        truncated = event.truncated
        for attr, values in (("beforeJson", event.before), ("afterJson", event.after)):
            if values is not None:
                bounded, cut = ev.bound(values, cfg)
                item[attr] = _dumps(bounded)
                truncated = truncated or cut
        if truncated:
            item["truncated"] = True

        if event.restorable and event.restore_payload is not None:
            payload = _dumps(event.restore_payload)
            # A payload that does not fit would restore a different record, so skip it.
            if len(payload.encode("utf-8")) <= cfg.json_max_bytes:
                item["restorable"] = True
                item["restorePayload"] = payload
        return item

    # --- Purging -------------------------------------------------------------

    def purge_user(self) -> int:
        """Delete all of the user's events. Returns the number deleted; never raises."""
        try:
            rows = self._repo.query(
                keys.user_pk(self._user_id), sk_begins_with=keys.activity_list_prefix()
            )
            return self._delete(rows)
        except Exception as exc:  # noqa: BLE001
            self._log_purge_failure("user", exc)
            return 0

    def purge_property(self, property_id: str) -> int:
        """Delete the user's events for one property (GSI1 query). Never raises."""
        try:
            rows = self._repo.query(
                keys.activity_gsi1_pk(property_id),
                sk_begins_with=keys.activity_list_prefix(),
                index_name="GSI1",
            )
            return self._delete(rows)
        except Exception as exc:  # noqa: BLE001
            self._log_purge_failure("property", exc)
            return 0

    def _delete(self, rows: list[dict[str, Any]]) -> int:
        pk = keys.user_pk(self._user_id)
        # Only this user's activity items, whatever the index returned.
        targets = [
            {"delete": {"pk": r["PK"], "sk": r["SK"]}}
            for r in rows
            if r.get("PK") == pk and str(r.get("SK", "")).startswith(keys.ACT_PREFIX)
        ]
        deleted = 0
        for i in range(0, len(targets), _BATCH):
            chunk = targets[i : i + _BATCH]
            self._repo.transact_write(chunk)
            deleted += len(chunk)
        return deleted

    def _log_purge_failure(self, scope: str, exc: Exception) -> None:
        try:
            self._log.warning("activity_purge_failed scope=%s error=%s", scope, exc_summary(exc))
        except Exception:  # noqa: BLE001
            pass


# --- Reading and restoring ---------------------------------------------------


@dataclass(frozen=True)
class ActivityEvent:
    """One event as the routes return it (``before``/``after`` are objects)."""

    event_id: str  # "<inverted ms>.<uuid>", the restore path segment
    at: str
    action: str
    entity: str
    summary: str
    record_id: str | None
    property_id: str | None
    property_name: str | None
    before: dict[str, Any] | None
    after: dict[str, Any] | None
    truncated: bool
    restorable: bool
    restored_at: str | None
    restored_as: str | None


@dataclass(frozen=True)
class ActivityPage:
    events: tuple[ActivityEvent, ...]
    next_cursor: str | None


@dataclass(frozen=True)
class RestoreOutcome:
    record_id: str
    event_id: str
    restored_at: str


def _loads_object(raw: Any) -> dict[str, Any] | None:
    if not isinstance(raw, str):
        return None
    try:
        value = json.loads(raw)
    except ValueError:
        return None
    return value if isinstance(value, dict) else None


def _wire_event_id(sk: str) -> str:
    return sk[len(keys.ACT_PREFIX) :].replace("#", ".", 1)


def _dec(value: Any) -> Decimal | None:
    if value is None or value == "":
        return None
    if isinstance(value, bool) or not isinstance(value, (str, int, Decimal)):
        raise ValueError("money values must be strings")
    try:
        return Decimal(str(value))
    except InvalidOperation as exc:
        raise ValueError("invalid number") from exc


def _opt_str(value: Any) -> str | None:
    return value if isinstance(value, str) else None


class ActivityService:
    """Reads the user's history and restores a safely deleted record.

    Every read is scoped to ``USER#<id>`` (or to a property the user owns), a
    list request performs no write, and a missing or foreign property returns
    the same ``Property not found.`` error.
    """

    def __init__(
        self,
        repo: Any,
        user_id: str,
        transactions: Any,
        itemized: Any,
        depreciation: Any,
        loans: Any,
        recorder: ActivityRecorder,
        clock: Callable[[], datetime] = _utcnow,
        config: ActivityConfig = ACTIVITY_CONFIG,
        log: logging.Logger = logger,
    ) -> None:
        self._repo = repo
        self._user_id = user_id
        self._transactions = transactions
        self._itemized = itemized
        self._depreciation = depreciation
        self._loans = loans
        self._recorder = recorder
        self._clock = clock
        self._cfg = config
        self._log = log

    # --- Ownership -----------------------------------------------------------

    def _owns_property(self, property_id: str) -> bool:
        if not isinstance(property_id, str) or not property_id:
            return False
        item = self._repo.get_item(
            keys.property_scoped_pk(property_id), keys.property_meta_sk()
        )
        return item is not None and str(item.get("userId")) == self._user_id

    # --- Listing -------------------------------------------------------------

    def list_user(
        self,
        *,
        limit: int | None = None,
        cursor: str | None = None,
        entity: str | None = None,
        action: str | None = None,
        property_id: str | None = None,
    ) -> Result[ActivityPage]:
        return self._list(
            limit=limit, cursor=cursor, entity=entity, action=action, property_id=property_id
        )

    def list_property(
        self,
        property_id: str,
        *,
        limit: int | None = None,
        cursor: str | None = None,
        entity: str | None = None,
        action: str | None = None,
    ) -> Result[ActivityPage]:
        return self._list(
            limit=limit, cursor=cursor, entity=entity, action=action, property_id=property_id
        )

    def _list(
        self,
        *,
        limit: int | None,
        cursor: str | None,
        entity: str | None,
        action: str | None,
        property_id: str | None,
    ) -> Result[ActivityPage]:
        cfg = self._cfg
        if limit is None:
            limit = cfg.default_page
        elif isinstance(limit, bool) or not isinstance(limit, int) or not 1 <= limit <= cfg.max_page:
            return Result.failure(
                "validation", f"limit must be an integer from 1 to {cfg.max_page}.", field="limit"
            )
        if entity is not None and entity not in ENTITIES:
            return Result.failure("validation", "entity is not a known kind.", field="entity")
        if action is not None and action not in ACTIONS:
            return Result.failure("validation", "action is not a known kind.", field="action")
        start_sk: str | None = None
        if cursor is not None:
            start_sk = ev.decode_cursor(cursor)
            if start_sk is None:
                return Result.failure("validation", "cursor is not valid.", field="cursor")
        if property_id is not None and not self._owns_property(property_id):
            return Result.failure("not_found", _PROPERTY_NOT_FOUND)

        pk = keys.user_pk(self._user_id)
        if property_id is None:
            query_args: dict[str, Any] = {"sk_begins_with": keys.activity_list_prefix()}
            query_pk = pk
        else:
            query_pk = keys.activity_gsi1_pk(property_id)
            query_args = {
                "sk_begins_with": keys.activity_list_prefix(),
                "index_name": "GSI1",
            }
        start_key: dict[str, Any] | None = None
        if start_sk is not None:
            start_key = {"PK": pk, "SK": start_sk}
            if property_id is not None:
                start_key.update({"GSI1PK": query_pk, "GSI1SK": start_sk})

        now = self._clock().timestamp()
        matches: list[dict[str, Any]] = []
        last_read_sk: str | None = start_sk
        read = 0
        exhausted = False
        while len(matches) <= limit and read < READ_CAP:
            batch = min(limit + 1, READ_CAP - read)
            rows = self._repo.query(query_pk, limit=batch, start_key=start_key, **query_args)
            for row in rows:
                read += 1
                sk = str(row.get("SK", ""))
                last_read_sk = sk
                if row.get("PK") != pk or not sk.startswith(keys.ACT_PREFIX):
                    continue  # never surface another user's item
                ttl = row.get("ttl")
                if ttl is not None and float(ttl) <= now:
                    continue
                if entity is not None and row.get("entity") != entity:
                    continue
                if action is not None and row.get("action") != action:
                    continue
                matches.append(row)
                if len(matches) > limit:
                    break
            if len(rows) < batch:
                exhausted = True
                break
            if last_read_sk is None:
                break
            start_key = {"PK": pk, "SK": last_read_sk}
            if property_id is not None:
                start_key.update({"GSI1PK": query_pk, "GSI1SK": last_read_sk})

        if len(matches) > limit:
            page_rows = matches[:limit]
            next_sk: str | None = str(page_rows[-1]["SK"])
        else:
            page_rows = matches
            # Read cap reached before the partition ended: continue after the last item read.
            next_sk = None if exhausted else last_read_sk
        return Result.success(
            ActivityPage(
                events=tuple(self._view(r) for r in page_rows),
                next_cursor=ev.encode_cursor(next_sk) if next_sk else None,
            )
        )

    @staticmethod
    def _view(row: Mapping[str, Any]) -> ActivityEvent:
        restored_as = _opt_str(row.get("restoredAs"))
        return ActivityEvent(
            event_id=_wire_event_id(str(row["SK"])),
            at=str(row.get("at", "")),
            action=str(row.get("action", "")),
            entity=str(row.get("entity", "")),
            summary=str(row.get("summary", "")),
            record_id=_opt_str(row.get("recordId")),
            property_id=_opt_str(row.get("propertyId")),
            property_name=_opt_str(row.get("propertyName")),
            before=_loads_object(row.get("beforeJson")),
            after=_loads_object(row.get("afterJson")),
            truncated=bool(row.get("truncated", False)),
            restorable=bool(row.get("restorable", False)),
            restored_at=_opt_str(row.get("restoredAt")),
            restored_as=None if restored_as == PENDING else restored_as,
        )

    # --- Restore -------------------------------------------------------------

    def restore(self, property_id: str, event_id: str) -> Result[RestoreOutcome]:
        if not self._owns_property(property_id):
            return Result.failure("not_found", _PROPERTY_NOT_FOUND)
        if not isinstance(event_id, str) or not _EVENT_ID_RE.fullmatch(event_id):
            return Result.failure("not_found", _EVENT_NOT_FOUND)
        pk = keys.user_pk(self._user_id)
        sk = keys.ACT_PREFIX + event_id.replace(".", "#", 1)
        item = self._repo.get_item(pk, sk)
        if item is None or item.get("propertyId") != property_id:
            return Result.failure("not_found", _EVENT_NOT_FOUND)

        now = self._clock()
        stale_at = _iso_millis(now - CLAIM_STALE)
        if item.get("action") != "delete":
            return Result.failure("conflict", "Only a delete event can be restored.")
        if not item.get("restorable") or not isinstance(item.get("restorePayload"), str):
            return Result.failure("conflict", "This event cannot be restored.")
        claimed_at = item.get("restoredAt")
        if claimed_at is not None and not (
            item.get("restoredAs") == PENDING and str(claimed_at) < stale_at
        ):
            return Result.failure("conflict", "This event was already restored.")

        payload = _loads_object(item["restorePayload"])
        if payload is None:
            return Result.failure("conflict", "The stored restore data is not readable.")
        entity = str(item.get("entity", ""))
        try:
            create = self._creator(entity, property_id, payload)
        except ValueError:
            return Result.failure("conflict", "The stored restore data is not valid.")
        if create is None:
            return Result.failure("conflict", "This event cannot be restored.")

        base = {k: v for k, v in item.items() if k not in ("restoredAt", "restoredAs")}
        claim_time = _iso_millis(now)
        claimed = {**base, "restoredAt": claim_time, "restoredAs": PENDING}
        try:
            self._repo.put_item(
                claimed,
                condition=(
                    "attribute_not_exists(restoredAt) OR "
                    "(restoredAs = :pending AND restoredAt < :stale)"
                ),
                values={":pending": PENDING, ":stale": stale_at},
            )
        except ConditionFailed:
            return Result.failure("conflict", "This event was already restored.")

        try:
            created = create()
        except Exception:
            self._release(base, claim_time)
            raise
        if not created.is_ok:
            self._release(base, claim_time)
            return Result.failure(
                created.error.kind,  # type: ignore[union-attr]
                created.error.message,  # type: ignore[union-attr]
                field=created.error.field,  # type: ignore[union-attr]
                errors=created.error.errors,  # type: ignore[union-attr]
            )

        new_id = str(created.value.id)
        try:
            self._repo.put_item(
                {**claimed, "restoredAs": new_id},
                condition="restoredAs = :pending AND restoredAt = :at",
                values={":pending": PENDING, ":at": claim_time},
            )
        except Exception as exc:  # noqa: BLE001 - the record exists; do not fail the restore
            self._warn("activity_restore_mark_failed", exc)

        self._record_restore(item, entity, payload, new_id)
        return Result.success(
            RestoreOutcome(record_id=new_id, event_id=event_id, restored_at=claim_time)
        )

    def _creator(
        self, entity: str, property_id: str, payload: Mapping[str, Any]
    ) -> Callable[[], Result[Any]] | None:
        """A thunk that re-creates the record through the existing service."""
        if entity == "transaction":
            from logstead.models.transaction import TransactionInput

            tx = TransactionInput(
                property_id=property_id,
                date=_opt_str(payload.get("date")),
                amount=_dec(payload.get("amount")),
                type=_opt_str(payload.get("type")),  # type: ignore[arg-type]
                category_id=_opt_str(payload.get("category_id")),
                description=_opt_str(payload.get("description")),
                notes=_opt_str(payload.get("notes")),
            )
            return lambda: self._transactions.create(tx)
        if entity == "itemized_entry":
            from logstead.services.itemized import EntryInput

            category_id = _opt_str(payload.get("category_id"))
            if not category_id:
                raise ValueError("category_id")
            raw_year = payload.get("tax_year")
            if raw_year is not None and (isinstance(raw_year, bool) or not isinstance(raw_year, int)):
                raise ValueError("tax_year")
            entry = EntryInput(
                date=_opt_str(payload.get("date")),
                amount=_dec(payload.get("amount")),
                description=_opt_str(payload.get("description")),
                notes=_opt_str(payload.get("notes")),
                tax_year=raw_year,
            )
            return lambda: self._itemized.create_entry(property_id, category_id, entry)
        if entity == "asset":
            from logstead.models.depreciation import AssetInput

            overrides_raw = payload.get("depreciation_overrides")
            overrides: dict[int, Decimal] = {}
            if isinstance(overrides_raw, dict):
                for year, value in overrides_raw.items():
                    amount = _dec(value)
                    if amount is not None:
                        overrides[int(year)] = amount
            asset = AssetInput(
                property_id=property_id,
                description=_opt_str(payload.get("description")),
                cost_basis=_dec(payload.get("cost_basis")),
                placed_in_service_date=_opt_str(payload.get("placed_in_service_date")),
                recovery_period_years=_dec(payload.get("recovery_period_years")),
                depreciation_overrides=overrides or None,
            )
            return lambda: self._depreciation.create_asset(asset)
        if entity == "loan":
            from logstead.models.loan import LoanInput

            include = payload.get("include_in_report", True)
            if not isinstance(include, bool):
                raise ValueError("include_in_report")
            loan = LoanInput(
                property_id=property_id,
                description=_opt_str(payload.get("description")),
                annual_interest_rate=_dec(payload.get("annual_interest_rate")),
                monthly_payment=_dec(payload.get("monthly_payment")),
                anchor_balance=_dec(payload.get("anchor_balance")),
                anchor_date=_opt_str(payload.get("anchor_date")),
                extra_principal=_dec(payload.get("extra_principal")),
                payoff_date=_opt_str(payload.get("payoff_date")),
                original_principal=_dec(payload.get("original_principal")),
                closing_date=_opt_str(payload.get("closing_date")),
                include_in_report=include,
            )
            return lambda: self._loans.create_loan(loan)
        return None

    def _release(self, base: Mapping[str, Any], claim_time: str) -> None:
        """Remove our claim so the user can retry. Never raises."""
        try:
            self._repo.put_item(
                dict(base),
                condition="restoredAs = :pending AND restoredAt = :at",
                values={":pending": PENDING, ":at": claim_time},
            )
        except Exception as exc:  # noqa: BLE001
            self._warn("activity_restore_release_failed", exc)

    def _record_restore(
        self, item: Mapping[str, Any], entity: str, payload: Mapping[str, Any], new_id: str
    ) -> None:
        after = ev.project(entity, payload)
        self._recorder.record(
            NewEvent(
                action="restore",
                entity=entity,
                summary=ev.summarize("restore", entity, None, after),
                record_id=new_id,
                property_id=_opt_str(item.get("propertyId")),
                property_name=_opt_str(item.get("propertyName")),
                after=after,
            )
        )

    def _warn(self, label: str, exc: Exception) -> None:
        try:
            self._log.warning("%s error=%s", label, exc_summary(exc))
        except Exception:  # noqa: BLE001
            pass
