"""Pure helpers for building activity events. No I/O.

Records are the wire-shaped (snake_case) mappings the routes return. Money is
kept as the stored string, never rounded or parsed to float.
"""
from __future__ import annotations

import base64
import binascii
import json
import re
from collections.abc import Mapping
from datetime import datetime, timedelta, timezone
from decimal import Decimal
from typing import Any, Final

from logstead.repository import keys
from logstead.services.activity_config import ACTIVITY_CONFIG, ActivityConfig

_TX_FIELDS: Final = ("date", "amount", "type", "category_id", "description", "notes")

FIELDS: Final[Mapping[str, tuple[str, ...]]] = {
    "transaction": _TX_FIELDS,
    "itemized_entry": _TX_FIELDS,
    "asset": ("description", "cost_basis", "placed_in_service_date", "recovery_period_years"),
    "loan": (
        "description",
        "annual_interest_rate",
        "monthly_payment",
        "anchor_balance",
        "anchor_date",
        "include_in_report",
    ),
    "property": ("name", "address_text", "property_type", "business_id"),
}

_ENTITY_LABELS: Final = {
    "transaction": "transaction",
    "itemized_entry": "itemized entry",
    "asset": "asset",
    "loan": "loan",
    "property": "property",
    "backup": "backup",
    "schedule_e": "Schedule E",
}
_ACTION_VERBS: Final = {
    "create": "Added",
    "update": "Updated",
    "delete": "Deleted",
    "restore": "Restored",
    "import": "Imported",
}
_NAME_FIELDS: Final = ("description", "name")

_CURSOR_SK_RE: Final = re.compile(r"^ACT#\d{14}#[0-9A-Za-z-]{1,64}$")
_CURSOR_MAX_LEN: Final = 200

Values = dict[str, "str | bool | None"]


def _scalar(value: Any) -> str | bool | None:
    if value is None or isinstance(value, bool):
        return value
    if isinstance(value, str):
        return value
    if isinstance(value, Decimal):
        return format(value, "f")
    return str(value)


def project(entity: str, record: Mapping[str, Any]) -> Values:
    """Allow-listed fields of ``record``; every allowed key present, missing as None."""
    return {f: _scalar(record.get(f)) for f in FIELDS.get(entity, ())}


def diff(entity: str, before: Mapping[str, Any], after: Mapping[str, Any]) -> tuple[Values, Values]:
    """Changed allow-listed fields as (before, after); two empty maps when unchanged."""
    b, a = project(entity, before), project(entity, after)
    changed = [f for f in FIELDS.get(entity, ()) if b[f] != a[f]]
    return {f: b[f] for f in changed}, {f: a[f] for f in changed}


def _json_size(values: Mapping[str, Any]) -> int:
    return len(json.dumps(values, ensure_ascii=False, separators=(",", ":")).encode("utf-8"))


def bound(values: Mapping[str, Any], cfg: ActivityConfig = ACTIVITY_CONFIG) -> tuple[Values, bool]:
    """Truncate text values and keep the JSON within ``json_max_bytes``."""
    out: Values = dict(values)
    truncated = False
    for k, v in out.items():
        if isinstance(v, str) and len(v) > cfg.value_max_chars:
            out[k] = v[: cfg.value_max_chars]
            truncated = True
    while _json_size(out) > cfg.json_max_bytes:
        longest = max(
            (k for k, v in out.items() if isinstance(v, str) and v),
            key=lambda k: len(out[k]),  # type: ignore[arg-type]
            default=None,
        )
        if longest is None:
            break
        text = out[longest]
        assert isinstance(text, str)
        out[longest] = text[: len(text) // 2]
        truncated = True
    return out, truncated


def _clip(text: str, limit: int) -> str:
    return text if len(text) <= limit else text[: max(limit - 1, 0)] + "\u2026"


def summarize(
    action: str,
    entity: str,
    before: Mapping[str, Any] | None,
    after: Mapping[str, Any] | None,
    extra: Mapping[str, Any] | None = None,
    cfg: ActivityConfig = ACTIVITY_CONFIG,
) -> str:
    """One plain-language line, at most ``summary_max_chars`` characters."""
    extra = extra or {}
    label = _ENTITY_LABELS.get(entity, entity)
    if action == "import":
        if entity == "schedule_e":
            text = (
                f"Imported Schedule E: {extra.get('created', 0)} rows created, "
                f"{extra.get('replaced', 0)} replaced"
            )
        elif entity == "backup":
            text = "Restored from backup"
        else:
            text = f"Imported {extra.get('created', 0)} {label}s"
    else:
        text = f"{_ACTION_VERBS.get(action, action.capitalize())} {label}"
        source = (after if action in ("create", "restore") else before) or {}
        name = next((str(source[f]) for f in _NAME_FIELDS if source.get(f)), "")
        if name:
            text += f": {name}"
        if action == "update" and before and after:
            changed = [f for f in before if f in after and before[f] != after[f]]
            if changed:
                text += f" ({', '.join(changed)})"
    return _clip(" ".join(text.split()), cfg.summary_max_chars)


def inverted_millis(at: datetime) -> str:
    """14-digit ``99999999999999 - epoch_ms``; later times sort first."""
    if at.tzinfo is None:
        at = at.replace(tzinfo=timezone.utc)
    return f"{keys.ACTIVITY_INVERT_BASE - int(at.timestamp() * 1000):014d}"


def event_sk(at: datetime, event_id: str) -> str:
    """``ACT#<inverted ms>#<id>``."""
    return keys.activity_sk(at, event_id)


def ttl_for(at: datetime, cfg: ActivityConfig | None = None) -> int:
    """Epoch seconds at which the event expires: ``at`` plus the retention window."""
    days = (cfg or ACTIVITY_CONFIG).retention_days
    if at.tzinfo is None:
        at = at.replace(tzinfo=timezone.utc)
    return int((at + timedelta(days=days)).timestamp())


def encode_cursor(sk: str) -> str:
    return base64.urlsafe_b64encode(sk.encode("utf-8")).decode("ascii").rstrip("=")


def decode_cursor(raw: str) -> str | None:
    """The SK a cursor names, or None when malformed. Never raises."""
    if not isinstance(raw, str) or not raw or len(raw) > _CURSOR_MAX_LEN or not raw.isascii():
        return None
    try:
        sk = base64.urlsafe_b64decode(raw + "=" * (-len(raw) % 4)).decode("utf-8")
    except (binascii.Error, ValueError):
        return None
    if not _CURSOR_SK_RE.fullmatch(sk) or encode_cursor(sk) != raw:
        return None
    return sk


def is_restorable(
    entity: str,
    action: str,
    record: Mapping[str, Any],
    receipt_count: int | None,
) -> bool:
    """True only for a delete the toast Undo would also allow (unknown receipt count is unsafe)."""
    if action != "delete":
        return False
    if entity == "transaction":
        return (
            not record.get("itemized")
            and not record.get("imported")
            and receipt_count == 0
        )
    if entity == "itemized_entry":
        return receipt_count == 0
    if entity == "asset":
        return True
    if entity == "loan":
        return not (record.get("interest_overrides") or {})
    return False
