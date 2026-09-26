"""RentCast property-enrichment adapter (Requirements 3.2, 3.3, 3.8, 12.1, 12.2).

Wraps the RentCast Property Records API so the Property/Enrichment services can
turn a full street address into a sparse :class:`PropertyDetails`. The adapter
lives entirely server-side inside the Lambda so the API key never leaves the
backend.

Contract (see design "RentCast Adapter"):

* Calls ``GET /properties?address=<address>`` with the API key in an
  ``X-Api-Key`` header (read from the ``RENTCAST_API_KEY`` env var) and a
  bounded HTTP timeout so a slow provider cannot exhaust the Lambda budget.
* Maps the returned record into ``PropertyDetails``, copying ONLY the fields
  RentCast actually provides and leaving everything else unset (Req 3.3, 12.2).
* A 404 or empty result maps to a success carrying ``None`` (→ not_found).
* A network error, 5xx, or timeout maps to an ``unavailable`` error Result.

The network call is injectable (the ``fetch`` constructor argument) so tests can
stub the HTTP response and never hit the network.
"""

from __future__ import annotations

import json
import os
import urllib.error
import urllib.parse
import urllib.request
from dataclasses import dataclass
from decimal import Decimal, InvalidOperation
from typing import Any, Callable

from logstead.models.property import (
    HoaDetails,
    PropertyDetails,
    PropertyFeatures,
    PropertyOwner,
    PropertyTax,
    SaleEvent,
    TaxAssessment,
)
from logstead.models.result import Result

# RentCast Property Records API base. The endpoint accepts a full address and
# returns records for it (there is no separate autocomplete endpoint).
RENTCAST_BASE_URL = "https://api.rentcast.io/v1"

# Bounded HTTP timeout (seconds). Kept well under a typical Lambda budget so a
# slow provider degrades to "unavailable" rather than a Lambda timeout.
DEFAULT_TIMEOUT_SECONDS = 5.0


@dataclass(frozen=True)
class HttpResponse:
    """A minimal HTTP response shape the adapter needs.

    Decoupled from ``urllib`` so tests can construct responses directly and the
    fetch function stays trivially mockable.
    """

    status: int
    body: str


# A fetch function turns a URL + headers into an :class:`HttpResponse`. The
# default implementation uses ``urllib.request``; tests inject a stub.
FetchFn = Callable[[str, dict[str, str], float], HttpResponse]


def _urllib_fetch(url: str, headers: dict[str, str], timeout: float) -> HttpResponse:
    """Default fetch backed by ``urllib.request`` with a bounded timeout.

    Raises the underlying ``urllib``/``OSError`` exceptions on transport
    failure; :meth:`RentCastAdapter.get_property_record` maps those to an
    ``unavailable`` error. HTTP error statuses (4xx/5xx) are surfaced as an
    :class:`HttpResponse` with the corresponding status code rather than an
    exception, so the caller can distinguish 404 (not_found) from 5xx.
    """
    request = urllib.request.Request(url, headers=headers, method="GET")
    try:
        with urllib.request.urlopen(request, timeout=timeout) as response:
            charset = response.headers.get_content_charset() or "utf-8"
            body = response.read().decode(charset, errors="replace")
            return HttpResponse(status=response.status, body=body)
    except urllib.error.HTTPError as exc:  # 4xx / 5xx come through here
        body = ""
        try:
            body = exc.read().decode("utf-8", errors="replace")
        except Exception:  # pragma: no cover - body is best-effort only
            body = ""
        return HttpResponse(status=exc.code, body=body)


def _opt_str(value: Any) -> str | None:
    """Coerce a provider value to a non-empty string, else ``None``.

    Only present, meaningful values are copied (Req 3.3, 12.2); ``None`` and
    blank strings are treated as absent.
    """
    if value is None:
        return None
    text = str(value).strip()
    return text or None


def _opt_int(value: Any) -> int | None:
    """Coerce a provider value to an ``int``, else ``None`` if absent/invalid."""
    if value is None or value == "":
        return None
    try:
        return int(value)
    except (TypeError, ValueError):
        return None


def _opt_decimal(value: Any) -> Decimal | None:
    """Coerce a provider value to a ``Decimal``, else ``None`` if absent/invalid."""
    if value is None or value == "":
        return None
    try:
        return Decimal(str(value))
    except (InvalidOperation, TypeError, ValueError):
        return None


def _opt_bool(value: Any) -> bool | None:
    """Coerce a provider value to a ``bool``, else ``None`` if absent.

    RentCast presence flags arrive as JSON booleans; a missing flag stays unset
    (``None``) so the sparse contract is preserved (Req 3.3, 12.2). Only a
    genuine boolean is accepted — non-boolean values map to ``None`` rather than
    guessing truthiness.
    """
    if isinstance(value, bool):
        return value
    return None


def _map_features(record: dict[str, Any]) -> PropertyFeatures:
    """Map RentCast feature fields into :class:`PropertyFeatures`.

    RentCast nests structural features under a ``features`` object; older/flat
    shapes may place them at the top level, so both are checked. The descriptive
    ``*Type`` fields (``heatingType`` etc.) map to the string fields, while the
    ``heating``/``cooling``/``garage``/``pool``/``fireplace`` booleans map to the
    presence flags. Only provided fields are copied.
    """
    features = record.get("features")
    if not isinstance(features, dict):
        features = {}

    def pick(key: str) -> Any:
        # Prefer the nested features object, fall back to a top-level key.
        return features.get(key, record.get(key))

    return PropertyFeatures(
        architecture_type=_opt_str(pick("architectureType")),
        exterior_type=_opt_str(pick("exteriorType")),
        foundation_type=_opt_str(pick("foundationType")),
        roof_type=_opt_str(pick("roofType")),
        view_type=_opt_str(pick("viewType")),
        heating=_opt_bool(pick("heating")),
        heating_type=_opt_str(pick("heatingType")),
        cooling=_opt_bool(pick("cooling")),
        cooling_type=_opt_str(pick("coolingType")),
        garage=_opt_bool(pick("garage")),
        garage_spaces=_opt_int(pick("garageSpaces")),
        garage_type=_opt_str(pick("garageType")),
        pool=_opt_bool(pick("pool")),
        pool_type=_opt_str(pick("poolType")),
        fireplace=_opt_bool(pick("fireplace")),
        fireplace_type=_opt_str(pick("fireplaceType")),
        floor_count=_opt_int(pick("floorCount")),
        room_count=_opt_int(pick("roomCount")),
        unit_count=_opt_int(pick("unitCount")),
    )


def _map_hoa(record: dict[str, Any]) -> HoaDetails | None:
    """Map the ``hoa`` object into :class:`HoaDetails`, or ``None`` when absent."""
    hoa = record.get("hoa")
    if not isinstance(hoa, dict):
        return None
    fee = _opt_decimal(hoa.get("fee"))
    if fee is None:
        return None
    return HoaDetails(fee=fee)


def _map_owner(record: dict[str, Any]) -> PropertyOwner | None:
    """Map the ``owner`` object into :class:`PropertyOwner`, or ``None``.

    The owner-occupied flag lives at the record top level (``ownerOccupied``),
    so it is folded in here alongside the nested owner names/type.
    """
    owner = record.get("owner")
    occupied = _opt_bool(record.get("ownerOccupied"))
    if not isinstance(owner, dict):
        if occupied is None:
            return None
        return PropertyOwner(occupied=occupied)

    names_raw = owner.get("names")
    names: list[str] = []
    if isinstance(names_raw, list):
        names = [n for n in (_opt_str(item) for item in names_raw) if n is not None]

    owner_type = _opt_str(owner.get("type"))
    if not names and owner_type is None and occupied is None:
        return None
    return PropertyOwner(names=names, type=owner_type, occupied=occupied)


def _map_tax_assessments(record: dict[str, Any]) -> list[TaxAssessment]:
    """Map the year-keyed ``taxAssessments`` object into a year-sorted list."""
    raw = record.get("taxAssessments")
    if not isinstance(raw, dict):
        return []
    entries: list[TaxAssessment] = []
    for key, entry in raw.items():
        if not isinstance(entry, dict):
            continue
        year = _opt_int(entry.get("year"))
        if year is None:
            year = _opt_int(key)
        if year is None:
            continue
        entries.append(
            TaxAssessment(
                year=year,
                value=_opt_decimal(entry.get("value")),
                land=_opt_decimal(entry.get("land")),
                improvements=_opt_decimal(entry.get("improvements")),
            )
        )
    entries.sort(key=lambda a: a.year)
    return entries


def _map_property_taxes(record: dict[str, Any]) -> list[PropertyTax]:
    """Map the year-keyed ``propertyTaxes`` object into a year-sorted list."""
    raw = record.get("propertyTaxes")
    if not isinstance(raw, dict):
        return []
    entries: list[PropertyTax] = []
    for key, entry in raw.items():
        if not isinstance(entry, dict):
            continue
        year = _opt_int(entry.get("year"))
        if year is None:
            year = _opt_int(key)
        if year is None:
            continue
        entries.append(PropertyTax(year=year, total=_opt_decimal(entry.get("total"))))
    entries.sort(key=lambda t: t.year)
    return entries


def _map_sale_history(record: dict[str, Any]) -> list[SaleEvent]:
    """Map the date-keyed ``history`` object into a date-descending list."""
    raw = record.get("history")
    if not isinstance(raw, dict):
        return []
    entries: list[tuple[str, SaleEvent]] = []
    for key, entry in raw.items():
        if not isinstance(entry, dict):
            continue
        date_str = _opt_str(entry.get("date")) or _opt_str(key)
        event = SaleEvent(
            date=date_str,
            price=_opt_decimal(entry.get("price")),
            event=_opt_str(entry.get("event")),
        )
        # Sort key falls back to the map key so undated entries still order.
        entries.append((date_str or _opt_str(key) or "", event))
    entries.sort(key=lambda pair: pair[0], reverse=True)
    return [event for _, event in entries]


def map_record_to_details(record: dict[str, Any]) -> PropertyDetails:
    """Map a single RentCast property record into a sparse ``PropertyDetails``.

    Copies only the fields RentCast provides; any field the provider omits (or
    supplies as null/blank) is left unset (Requirements 3.3, 12.1, 12.2). The
    year-keyed ``taxAssessments`` / ``propertyTaxes`` and date-keyed ``history``
    objects are rolled up into ordered lists.
    """
    return PropertyDetails(
        formatted_address=_opt_str(record.get("formattedAddress")),
        address_line1=_opt_str(record.get("addressLine1")),
        address_line2=_opt_str(record.get("addressLine2")),
        city=_opt_str(record.get("city")),
        state=_opt_str(record.get("state")),
        zip_code=_opt_str(record.get("zipCode")),
        county=_opt_str(record.get("county")),
        latitude=_opt_decimal(record.get("latitude")),
        longitude=_opt_decimal(record.get("longitude")),
        property_type=_opt_str(record.get("propertyType")),
        bedrooms=_opt_int(record.get("bedrooms")),
        bathrooms=_opt_decimal(record.get("bathrooms")),
        living_area_sqft=_opt_int(record.get("squareFootage")),
        lot_size=_opt_decimal(record.get("lotSize")),
        year_built=_opt_int(record.get("yearBuilt")),
        assessor_id=_opt_str(record.get("assessorID")),
        legal_description=_opt_str(record.get("legalDescription")),
        subdivision=_opt_str(record.get("subdivision")),
        zoning=_opt_str(record.get("zoning")),
        last_sale_date=_opt_str(record.get("lastSaleDate")),
        last_sale_price=_opt_decimal(record.get("lastSalePrice")),
        features=_map_features(record),
        hoa=_map_hoa(record),
        owner=_map_owner(record),
        tax_assessments=_map_tax_assessments(record),
        property_taxes=_map_property_taxes(record),
        sale_history=_map_sale_history(record),
    )


class RentCastAdapter:
    """Server-side adapter over the RentCast Property Records API.

    Args:
        api_key: The RentCast API key. Defaults to the ``RENTCAST_API_KEY``
            environment variable (server-held; never sent to the client).
        base_url: Override the API base URL (useful for tests).
        timeout: Bounded HTTP timeout in seconds.
        fetch: Injectable fetch function; defaults to a ``urllib``-backed one so
            tests can stub the HTTP layer and never hit the network.
    """

    def __init__(
        self,
        api_key: str | None = None,
        *,
        base_url: str = RENTCAST_BASE_URL,
        timeout: float = DEFAULT_TIMEOUT_SECONDS,
        fetch: FetchFn | None = None,
    ) -> None:
        self._api_key = api_key if api_key is not None else os.environ.get("RENTCAST_API_KEY")
        self._base_url = base_url.rstrip("/")
        self._timeout = timeout
        self._fetch = fetch or _urllib_fetch

    def get_property_record(self, address: str) -> Result[PropertyDetails | None]:
        """Fetch and map the RentCast record for ``address``.

        Returns:
            * ``Result.success(PropertyDetails)`` when a record is found.
            * ``Result.success(None)`` when RentCast returns 404 or an empty
              result (→ not_found).
            * ``Result.failure("unavailable", ...)`` on a network error, a 5xx,
              a timeout, or an unparseable/unexpected response body.
        """
        query = urllib.parse.urlencode({"address": address})
        url = f"{self._base_url}/properties?{query}"
        headers = {"Accept": "application/json"}
        if self._api_key:
            headers["X-Api-Key"] = self._api_key

        try:
            response = self._fetch(url, headers, self._timeout)
        except (urllib.error.URLError, TimeoutError, OSError) as exc:
            # Network error / timeout at the transport layer.
            return Result.failure(
                "unavailable",
                f"Property enrichment is temporarily unavailable: {exc}",
            )

        status = response.status

        if status == 404:
            # Provider explicitly has no record for this address.
            return Result.success(None)

        if status >= 500:
            return Result.failure(
                "unavailable",
                f"Property enrichment provider returned an error (status {status}).",
            )

        if status >= 400:
            # Other 4xx (bad key, bad request, etc.). Not a user-recoverable
            # not_found, so surface as unavailable rather than a false negative.
            return Result.failure(
                "unavailable",
                f"Property enrichment request failed (status {status}).",
            )

        try:
            payload = json.loads(response.body) if response.body else None
        except (json.JSONDecodeError, ValueError):
            return Result.failure(
                "unavailable",
                "Property enrichment returned an unreadable response.",
            )

        record = _first_record(payload)
        if record is None:
            # 200 with an empty list / empty body → treated as not_found.
            return Result.success(None)

        return Result.success(map_record_to_details(record))


def _first_record(payload: Any) -> dict[str, Any] | None:
    """Extract the first property record from a RentCast payload.

    RentCast may return a list of records or a single object. An empty list,
    empty object, or ``None`` means "no record".
    """
    if payload is None:
        return None
    if isinstance(payload, list):
        for item in payload:
            if isinstance(item, dict) and item:
                return item
        return None
    if isinstance(payload, dict):
        return payload or None
    return None
