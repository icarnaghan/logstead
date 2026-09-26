"""Address autocomplete adapter (Requirement 3.1).

Turns the partial address text a user is typing into a list of
:class:`AddressSuggestion` candidates. RentCast has no autocomplete endpoint, so
suggestions come from **Amazon Location Service** (the ``geo-places``
Autocomplete API) called server-side inside the Lambda. Autocomplete only needs
to produce a clean address string the user can select and hand to the RentCast
adapter for enrichment.

Contract (mirrors the RentCast adapter's design pattern):

* Calls Amazon Location ``geo-places`` ``autocomplete`` with the partial text.
  Authorization is via the Lambda's IAM role (SigV4) - there is no API key to
  manage or leak to the client. ``IntendedUse="SingleUse"`` marks results as
  not persisted.
* Maps each result item into an ``AddressSuggestion`` carrying a clean
  ``formatted_address`` (the address ``Label``) plus the provider's opaque
  ``PlaceId`` when available.
* Degrades gracefully to an **empty list** on ANY failure - a blank query, a
  botocore/client error, a throttle, or an unexpected response shape - rather
  than raising (Requirement 3.1). Autocomplete is a convenience; property
  creation never depends on it, so a failed lookup should simply yield no
  suggestions.

The Amazon Location client is injectable (the ``client`` constructor argument)
so tests can stub the response and never touch AWS or the network. The client
is created lazily on first use so importing this module never requires AWS
credentials.
"""

from __future__ import annotations

import os
from typing import Any

from logstead.models.property import AddressSuggestion

# Default number of suggestions to request (the API default is 5).
DEFAULT_MAX_RESULTS = 5

# Amazon Location's Geocode ``SecondaryAddresses`` feature returns the individual
# units (apartments/suites) that live behind a single building result, which
# Autocomplete never surfaces. Request up to this many so a large building's
# units are not truncated. The API caps MaxResults at 50.
DEFAULT_MAX_SECONDARY_ADDRESSES = 50


def map_response_to_suggestions(response: Any) -> list[AddressSuggestion]:
    """Map an Amazon Location ``autocomplete`` response into suggestions.

    Reads the ``ResultItems`` list; for each item the formatted address is
    ``Address.Label`` (falling back to ``Title``) and the opaque id is
    ``PlaceId``. Items without a usable address string are skipped. An
    unexpected shape yields an empty list.
    """
    if not isinstance(response, dict):
        return []

    items = response.get("ResultItems")
    if not isinstance(items, list):
        return []

    suggestions: list[AddressSuggestion] = []
    for item in items:
        if not isinstance(item, dict):
            continue
        address = item.get("Address")
        label = ""
        if isinstance(address, dict):
            label_val = address.get("Label")
            label = str(label_val).strip() if label_val is not None else ""
        if not label:
            # Fall back to the display Title when there is no assembled Label.
            title = item.get("Title")
            label = str(title).strip() if title is not None else ""
        if not label:
            continue
        place_id = item.get("PlaceId")
        provider_place_id = str(place_id).strip() if place_id is not None else ""
        suggestions.append(
            AddressSuggestion(
                formatted_address=label,
                provider_place_id=provider_place_id or None,
            )
        )
    return suggestions


def map_secondary_addresses(response: Any) -> list[AddressSuggestion]:
    """Map an Amazon Location ``geocode`` response's units into suggestions.

    Autocomplete only ever returns the base building (e.g.
    ``"123 Main St, Springfield, IL 62704"``); the individual units live in
    the ``SecondaryAddresses`` array attached to the first Geocode result item
    (``ResultItems[0].SecondaryAddresses``). Each entry becomes an
    :class:`AddressSuggestion` whose ``formatted_address`` is the unit's
    ``Address.Label`` (falling back to ``Title``) and whose ``provider_place_id``
    is its ``PlaceId``. Entries without a usable address string are skipped. An
    unexpected shape (or no secondary addresses) yields an empty list.
    """
    if not isinstance(response, dict):
        return []

    items = response.get("ResultItems")
    if not isinstance(items, list) or not items:
        return []

    first = items[0]
    if not isinstance(first, dict):
        return []

    secondary = first.get("SecondaryAddresses")
    if not isinstance(secondary, list):
        return []

    suggestions: list[AddressSuggestion] = []
    for entry in secondary:
        if not isinstance(entry, dict):
            continue
        address = entry.get("Address")
        label = ""
        if isinstance(address, dict):
            label_val = address.get("Label")
            label = str(label_val).strip() if label_val is not None else ""
        if not label:
            # Fall back to the display Title when there is no assembled Label.
            title = entry.get("Title")
            label = str(title).strip() if title is not None else ""
        if not label:
            continue
        place_id = entry.get("PlaceId")
        provider_place_id = str(place_id).strip() if place_id is not None else ""
        suggestions.append(
            AddressSuggestion(
                formatted_address=label,
                provider_place_id=provider_place_id or None,
            )
        )
    return suggestions


class AutocompleteAdapter:
    """Server-side adapter over Amazon Location Service address autocomplete.

    Args:
        client: An Amazon Location ``geo-places`` boto3 client. When omitted, a
            client is created lazily on first use from ``AWS_REGION`` (or
            ``AWS_DEFAULT_REGION``). Tests inject a stub so no AWS call is made.
        max_results: Number of suggestions to request per call.
        max_secondary_addresses: Number of secondary (unit) addresses to request
            per :meth:`secondary_addresses` call.
    """

    def __init__(
        self,
        client: Any | None = None,
        *,
        max_results: int = DEFAULT_MAX_RESULTS,
        max_secondary_addresses: int = DEFAULT_MAX_SECONDARY_ADDRESSES,
    ) -> None:
        self._client = client
        self._max_results = max_results
        self._max_secondary_addresses = max_secondary_addresses

    def _get_client(self) -> Any:
        """Lazily construct the geo-places client so import needs no creds."""
        if self._client is None:
            import boto3  # imported lazily; tests inject a client instead

            region = os.environ.get("AWS_REGION") or os.environ.get("AWS_DEFAULT_REGION")
            self._client = boto3.client("geo-places", region_name=region)
        return self._client

    def suggestions(self, query: str) -> list[AddressSuggestion]:
        """Return address suggestions for the partial ``query`` text.

        Degrades gracefully to an empty list on any failure - a blank query, a
        client/botocore error, a throttle, or an unexpected response shape -
        rather than raising (Requirement 3.1).
        """
        if query is None or not query.strip():
            # Nothing to suggest for empty input; avoid a pointless call.
            return []

        try:
            client = self._get_client()
        except Exception:
            # Client construction failed (e.g. no region/credentials).
            return []

        try:
            response = client.autocomplete(
                QueryText=query.strip(),
                MaxResults=self._max_results,
                IntendedUse="SingleUse",
            )
        except Exception:
            # Any client/botocore error (ValidationException, ThrottlingException,
            # AccessDeniedException, network, ...) degrades to no suggestions.
            return []

        try:
            return map_response_to_suggestions(response)
        except Exception:  # pragma: no cover - mapping is defensive already
            return []

    def secondary_addresses(self, address: str) -> list[AddressSuggestion]:
        """Return the secondary (unit) addresses for a selected building.

        Autocomplete rejects the ``SecondaryAddresses`` feature, so the units
        that live behind a building result must come from a second **Geocode**
        call on the already-selected building ``address``. Each unit is returned
        as an :class:`AddressSuggestion` carrying the unit's full
        ``Address.Label`` (falling back to ``Title``) and the provider's opaque
        ``PlaceId``.

        Degrades gracefully to an empty list on any failure - a blank address, a
        client/botocore error, a throttle, or an unexpected/shape-less response -
        rather than raising, mirroring :meth:`suggestions`. A building with no
        units simply yields an empty list, leaving the base behavior unchanged.
        """
        if address is None or not address.strip():
            # Nothing to look up for empty input; avoid a pointless call.
            return []

        try:
            client = self._get_client()
        except Exception:
            # Client construction failed (e.g. no region/credentials).
            return []

        try:
            response = client.geocode(
                QueryText=address.strip(),
                AdditionalFeatures=["SecondaryAddresses"],
                MaxResults=self._max_secondary_addresses,
                IntendedUse="SingleUse",
            )
        except Exception:
            # Any client/botocore error (ValidationException, ThrottlingException,
            # AccessDeniedException, network, ...) degrades to no units.
            return []

        try:
            return map_secondary_addresses(response)
        except Exception:  # pragma: no cover - mapping is defensive already
            return []
