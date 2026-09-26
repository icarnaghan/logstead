"""Serialize :class:`PropertyDetails` to/from a single JSON string (Req 12.1, 13.3).

``PropertyDetails`` is stored as one ``detailsJson`` attribute on the property's
``PROPERTY#<id> / DETAILS`` row rather than spread across many nested DynamoDB
attributes. This module is the boundary that renders the details tree to that
JSON string and parses it back, preserving the two precision invariants:

* **Money** fields (``hoa.fee``, ``last_sale_price``, each ``TaxAssessment``
  value/land/improvements, each ``PropertyTax`` total, each ``SaleEvent`` price)
  are rendered as fixed two-decimal strings via
  :func:`logstead.util.money.money_to_str` and parsed back with
  :func:`logstead.util.money.to_money`, so they round-trip as exact two-decimal
  ``Decimal`` values with no float drift (design Property 28).
* **Non-money decimals** (``latitude`` / ``longitude``) are rendered as their
  plain decimal string (full precision preserved, never a float) and parsed
  back with ``Decimal``.

Integers stay integers, booleans stay booleans, and any ``None`` / empty value
is omitted so the stored document stays sparse (Requirements 12.2, 12.3) — the
inverse parse therefore yields exactly the fields that were present.
"""

from __future__ import annotations

import json
from decimal import Decimal, InvalidOperation
from typing import Any

from logstead.models.property import (
    HoaDetails,
    PropertyDetails,
    PropertyFeatures,
    PropertyOwner,
    PropertyTax,
    SaleEvent,
    TaxAssessment,
)
from logstead.util.money import money_to_str, to_money

__all__ = ["details_to_dict", "details_to_json", "details_from_dict", "details_from_json"]


def _put(dst: dict[str, Any], key: str, value: Any) -> None:
    """Set ``dst[key] = value`` unless the value is absent (None/empty).

    Keeps the serialized document sparse: ``None`` and empty lists are dropped.
    """
    if value is None:
        return
    if isinstance(value, list) and not value:
        return
    dst[key] = value


def _money_str(value: Decimal | None) -> str | None:
    """Render a money ``Decimal`` as a two-decimal string, or ``None``."""
    return None if value is None else money_to_str(value)


def _decimal_str(value: Decimal | None) -> str | None:
    """Render a non-money ``Decimal`` as its exact plain string, or ``None``."""
    return None if value is None else str(value)


def _features_to_dict(features: PropertyFeatures) -> dict[str, Any]:
    """Render a :class:`PropertyFeatures` to a sparse dict (all-scalar fields)."""
    out: dict[str, Any] = {}
    _put(out, "architecture_type", features.architecture_type)
    _put(out, "exterior_type", features.exterior_type)
    _put(out, "foundation_type", features.foundation_type)
    _put(out, "roof_type", features.roof_type)
    _put(out, "view_type", features.view_type)
    _put(out, "heating", features.heating)
    _put(out, "heating_type", features.heating_type)
    _put(out, "cooling", features.cooling)
    _put(out, "cooling_type", features.cooling_type)
    _put(out, "garage", features.garage)
    _put(out, "garage_spaces", features.garage_spaces)
    _put(out, "garage_type", features.garage_type)
    _put(out, "pool", features.pool)
    _put(out, "pool_type", features.pool_type)
    _put(out, "fireplace", features.fireplace)
    _put(out, "fireplace_type", features.fireplace_type)
    _put(out, "floor_count", features.floor_count)
    _put(out, "room_count", features.room_count)
    _put(out, "unit_count", features.unit_count)
    return out


def details_to_dict(details: PropertyDetails) -> dict[str, Any]:
    """Render a :class:`PropertyDetails` into a sparse, JSON-safe dict.

    Money is rendered as two-decimal strings and lat/long as plain decimal
    strings; ``None`` / empty values are omitted so the document stays sparse.
    """
    out: dict[str, Any] = {}

    _put(out, "formatted_address", details.formatted_address)
    _put(out, "address_line1", details.address_line1)
    _put(out, "address_line2", details.address_line2)
    _put(out, "city", details.city)
    _put(out, "state", details.state)
    _put(out, "zip_code", details.zip_code)
    _put(out, "county", details.county)

    _put(out, "latitude", _decimal_str(details.latitude))
    _put(out, "longitude", _decimal_str(details.longitude))

    _put(out, "property_type", details.property_type)
    _put(out, "bedrooms", details.bedrooms)
    _put(out, "bathrooms", _decimal_str(details.bathrooms))
    _put(out, "living_area_sqft", details.living_area_sqft)
    _put(out, "lot_size", _decimal_str(details.lot_size))
    _put(out, "year_built", details.year_built)

    _put(out, "assessor_id", details.assessor_id)
    _put(out, "legal_description", details.legal_description)
    _put(out, "subdivision", details.subdivision)
    _put(out, "zoning", details.zoning)

    _put(out, "last_sale_date", details.last_sale_date)
    _put(out, "last_sale_price", _money_str(details.last_sale_price))

    features = _features_to_dict(details.features)
    _put(out, "features", features or None)

    if details.hoa is not None and details.hoa.fee is not None:
        out["hoa"] = {"fee": _money_str(details.hoa.fee)}

    if details.owner is not None:
        owner: dict[str, Any] = {}
        _put(owner, "names", list(details.owner.names))
        _put(owner, "type", details.owner.type)
        _put(owner, "occupied", details.owner.occupied)
        _put(out, "owner", owner or None)

    if details.tax_assessments:
        out["tax_assessments"] = [
            _put_all(
                {"year": a.year},
                value=_money_str(a.value),
                land=_money_str(a.land),
                improvements=_money_str(a.improvements),
            )
            for a in details.tax_assessments
        ]

    if details.property_taxes:
        out["property_taxes"] = [
            _put_all({"year": t.year}, total=_money_str(t.total))
            for t in details.property_taxes
        ]

    if details.sale_history:
        history: list[dict[str, Any]] = []
        for event in details.sale_history:
            entry: dict[str, Any] = {}
            _put(entry, "date", event.date)
            _put(entry, "price", _money_str(event.price))
            _put(entry, "event", event.event)
            history.append(entry)
        _put(out, "sale_history", history or None)

    return out


def _put_all(base: dict[str, Any], **fields: Any) -> dict[str, Any]:
    """Return ``base`` extended with each non-absent keyword field."""
    for key, value in fields.items():
        _put(base, key, value)
    return base


def details_to_json(details: PropertyDetails) -> str:
    """Render a :class:`PropertyDetails` into a single JSON string for storage."""
    return json.dumps(details_to_dict(details))


# --- Parsing (JSON / dict -> PropertyDetails) --------------------------------


def _get_str(src: dict[str, Any], key: str) -> str | None:
    value = src.get(key)
    if value is None:
        return None
    text = str(value).strip()
    return text or None


def _get_int(src: dict[str, Any], key: str) -> int | None:
    value = src.get(key)
    if value is None or value == "":
        return None
    try:
        return int(value)
    except (TypeError, ValueError):
        return None


def _get_bool(src: dict[str, Any], key: str) -> bool | None:
    value = src.get(key)
    return value if isinstance(value, bool) else None


def _get_money(src: dict[str, Any], key: str) -> Decimal | None:
    value = src.get(key)
    if value is None or value == "":
        return None
    try:
        return to_money(str(value))
    except (ValueError, TypeError):
        return None


def _get_decimal(src: dict[str, Any], key: str) -> Decimal | None:
    value = src.get(key)
    if value is None or value == "":
        return None
    try:
        return Decimal(str(value))
    except (InvalidOperation, TypeError, ValueError):
        return None


def _features_from_dict(src: Any) -> PropertyFeatures:
    if not isinstance(src, dict):
        return PropertyFeatures()
    return PropertyFeatures(
        architecture_type=_get_str(src, "architecture_type"),
        exterior_type=_get_str(src, "exterior_type"),
        foundation_type=_get_str(src, "foundation_type"),
        roof_type=_get_str(src, "roof_type"),
        view_type=_get_str(src, "view_type"),
        heating=_get_bool(src, "heating"),
        heating_type=_get_str(src, "heating_type"),
        cooling=_get_bool(src, "cooling"),
        cooling_type=_get_str(src, "cooling_type"),
        garage=_get_bool(src, "garage"),
        garage_spaces=_get_int(src, "garage_spaces"),
        garage_type=_get_str(src, "garage_type"),
        pool=_get_bool(src, "pool"),
        pool_type=_get_str(src, "pool_type"),
        fireplace=_get_bool(src, "fireplace"),
        fireplace_type=_get_str(src, "fireplace_type"),
        floor_count=_get_int(src, "floor_count"),
        room_count=_get_int(src, "room_count"),
        unit_count=_get_int(src, "unit_count"),
    )


def details_from_dict(src: dict[str, Any]) -> PropertyDetails:
    """Parse a details dict (money strings -> two-decimal ``Decimal``).

    The inverse of :func:`details_to_dict`. Money strings are parsed back to
    exact two-decimal ``Decimal`` via :func:`to_money`; lat/long parse back to
    full-precision ``Decimal``. Missing fields stay unset (sparse; 12.3).
    """
    if not isinstance(src, dict):
        return PropertyDetails()

    hoa = None
    hoa_src = src.get("hoa")
    if isinstance(hoa_src, dict):
        fee = _get_money(hoa_src, "fee")
        if fee is not None:
            hoa = HoaDetails(fee=fee)

    owner = None
    owner_src = src.get("owner")
    if isinstance(owner_src, dict):
        names_raw = owner_src.get("names")
        names = (
            [str(n) for n in names_raw if str(n).strip()]
            if isinstance(names_raw, list)
            else []
        )
        owner = PropertyOwner(
            names=names,
            type=_get_str(owner_src, "type"),
            occupied=_get_bool(owner_src, "occupied"),
        )

    tax_assessments: list[TaxAssessment] = []
    for entry in src.get("tax_assessments") or []:
        if not isinstance(entry, dict):
            continue
        year = _get_int(entry, "year")
        if year is None:
            continue
        tax_assessments.append(
            TaxAssessment(
                year=year,
                value=_get_money(entry, "value"),
                land=_get_money(entry, "land"),
                improvements=_get_money(entry, "improvements"),
            )
        )

    property_taxes: list[PropertyTax] = []
    for entry in src.get("property_taxes") or []:
        if not isinstance(entry, dict):
            continue
        year = _get_int(entry, "year")
        if year is None:
            continue
        property_taxes.append(PropertyTax(year=year, total=_get_money(entry, "total")))

    sale_history: list[SaleEvent] = []
    for entry in src.get("sale_history") or []:
        if not isinstance(entry, dict):
            continue
        sale_history.append(
            SaleEvent(
                date=_get_str(entry, "date"),
                price=_get_money(entry, "price"),
                event=_get_str(entry, "event"),
            )
        )

    return PropertyDetails(
        formatted_address=_get_str(src, "formatted_address"),
        address_line1=_get_str(src, "address_line1"),
        address_line2=_get_str(src, "address_line2"),
        city=_get_str(src, "city"),
        state=_get_str(src, "state"),
        zip_code=_get_str(src, "zip_code"),
        county=_get_str(src, "county"),
        latitude=_get_decimal(src, "latitude"),
        longitude=_get_decimal(src, "longitude"),
        property_type=_get_str(src, "property_type"),
        bedrooms=_get_int(src, "bedrooms"),
        bathrooms=_get_decimal(src, "bathrooms"),
        living_area_sqft=_get_int(src, "living_area_sqft"),
        lot_size=_get_decimal(src, "lot_size"),
        year_built=_get_int(src, "year_built"),
        assessor_id=_get_str(src, "assessor_id"),
        legal_description=_get_str(src, "legal_description"),
        subdivision=_get_str(src, "subdivision"),
        zoning=_get_str(src, "zoning"),
        last_sale_date=_get_str(src, "last_sale_date"),
        last_sale_price=_get_money(src, "last_sale_price"),
        features=_features_from_dict(src.get("features")),
        hoa=hoa,
        owner=owner,
        tax_assessments=tax_assessments,
        property_taxes=property_taxes,
        sale_history=sale_history,
    )


def details_from_json(raw: str) -> PropertyDetails:
    """Parse a stored ``detailsJson`` string back into a :class:`PropertyDetails`."""
    if not raw:
        return PropertyDetails()
    parsed = json.loads(raw)
    if not isinstance(parsed, dict):
        return PropertyDetails()
    return details_from_dict(parsed)
