"""Address enrichment service (Requirements 3.1, 3.2, 3.4, 3.5, 3.6, 3.7).

Composes the two external adapters behind a single service the Property flow can
call while a user adds a property:

* :class:`~logstead.adapters.autocomplete.AutocompleteAdapter` turns the partial
  address text into a list of :class:`AddressSuggestion` candidates (Req 3.1).
* :class:`~logstead.adapters.rentcast.RentCastAdapter` turns a selected address
  into a sparse :class:`PropertyDetails` (Req 3.2, 3.8).

The central design rule is that **RentCast is an optional enrichment, never a
gate**: property creation must always succeed regardless of RentCast
availability (Requirement 3.7). This service never raises on a provider failure;
instead :meth:`AddressEnrichmentService.enrich` returns an
:class:`EnrichmentResult` whose ``status`` lets the caller (property router)
tell the three outcomes apart:

* ``"found"``     — RentCast returned a record; ``details`` carries the prefilled,
  editable :class:`PropertyDetails` (Req 3.2, 3.4).
* ``"not_found"`` — RentCast has no record for the address; the caller shows a
  "no property data found" message and enables manual entry (Req 3.5).
* ``"unavailable"`` — the RentCast call failed/timed out; the caller shows a
  "property data could not be retrieved" message, enables manual entry, and can
  offer the user a retry later (Req 3.6). This is the "enrich later" signal.

In every case the caller may proceed to create the property without details
(Requirement 3.7); enrichment only prefills, it never blocks.

Both adapters are injected via the constructor so tests can stub them and never
touch the network.
"""

from __future__ import annotations

from dataclasses import dataclass
from typing import Literal, Protocol

from logstead.models.property import AddressSuggestion, PropertyDetails
from logstead.models.result import Result

__all__ = ["EnrichmentResult", "AddressEnrichmentService"]


# The three outcomes a caller must distinguish. Kept as a Literal so the router
# can branch exhaustively and map each to the right UI message / behavior.
EnrichmentStatus = Literal["found", "not_found", "unavailable"]


@dataclass(frozen=True)
class EnrichmentResult:
    """Outcome of enriching a selected address (design "EnrichmentResult").

    Attributes:
        status: ``"found"`` when RentCast returned a record (``details`` set),
            ``"not_found"`` when RentCast has no record for the address, or
            ``"unavailable"`` when the RentCast call failed/timed out — the
            "enrich later" signal that lets the caller create the property now
            and offer a retry (Requirements 3.5, 3.6, 3.7).
        details: The prefilled, editable property details when ``status`` is
            ``"found"``; ``None`` for ``"not_found"`` and ``"unavailable"``.
        message: A human-readable message safe to surface to the client,
            populated for the ``"not_found"`` and ``"unavailable"`` cases so the
            UI can explain why nothing was prefilled (Requirements 3.5, 3.6).
    """

    status: EnrichmentStatus
    details: PropertyDetails | None = None
    message: str | None = None

    @property
    def is_found(self) -> bool:
        """True when enrichment produced details to prefill."""
        return self.status == "found"

    @property
    def can_retry_later(self) -> bool:
        """True when enrichment was only temporarily unavailable.

        Distinguishes the "enrich later" case (transient provider failure) from
        a definitive "no record" so the caller can offer a retry (Req 3.6).
        """
        return self.status == "unavailable"


class _AutocompletePort(Protocol):
    """The slice of the autocomplete adapter this service depends on."""

    def suggestions(self, query: str) -> list[AddressSuggestion]: ...

    def secondary_addresses(self, address: str) -> list[AddressSuggestion]: ...


class _RentCastPort(Protocol):
    """The slice of the RentCast adapter this service depends on."""

    def get_property_record(self, address: str) -> Result[PropertyDetails | None]: ...


class AddressEnrichmentService:
    """Compose autocomplete + RentCast into the add-property enrichment flow.

    Args:
        autocomplete: Adapter that turns partial address text into address
            suggestions. Degrades to an empty list on any failure, so
            :meth:`suggest_addresses` inherits that graceful behavior (Req 3.1).
        rentcast: Adapter that turns a selected address into a sparse
            ``PropertyDetails`` result (found / not_found / unavailable).
    """

    def __init__(
        self,
        autocomplete: _AutocompletePort,
        rentcast: _RentCastPort,
    ) -> None:
        self._autocomplete = autocomplete
        self._rentcast = rentcast

    def suggest_addresses(self, query: str) -> list[AddressSuggestion]:
        """Return address suggestions for the partial ``query`` text (Req 3.1).

        Delegates to the autocomplete adapter, which already degrades to an
        empty list on any provider failure — autocomplete is a convenience and
        never gates property creation.
        """
        return self._autocomplete.suggestions(query)

    # The design's Protocol names this ``suggest_addresses``; ``suggest`` is a
    # convenience alias for callers that prefer the shorter name.
    def suggest(self, query: str) -> list[AddressSuggestion]:
        """Alias for :meth:`suggest_addresses` (Req 3.1)."""
        return self.suggest_addresses(query)

    def unit_addresses(self, address: str) -> list[AddressSuggestion]:
        """Return the secondary (unit) addresses for a selected building (Req 3.1).

        Autocomplete only surfaces the base building; the individual units come
        from a second geocode lookup. Delegates to the autocomplete adapter,
        which already degrades to an empty list on any provider failure — a
        building with no units (or any failure) simply yields no picker, leaving
        the base flow unchanged.
        """
        return self._autocomplete.secondary_addresses(address)

    def enrich(self, selected_address: str) -> EnrichmentResult:
        """Enrich a selected address into an :class:`EnrichmentResult`.

        Calls RentCast and classifies the outcome so the caller can prefill,
        prompt for manual entry, or offer a retry — while always being free to
        create the property without details (Requirement 3.7):

        * RentCast success carrying details → ``status="found"`` with those
          details for the user to review and edit (Requirements 3.2, 3.4).
        * RentCast success carrying ``None`` (404/empty) → ``status="not_found"``
          with a "no property data found" message (Requirement 3.5).
        * RentCast failure/timeout ("unavailable") → ``status="unavailable"``
          with a "could not be retrieved" message — the "enrich later" signal
          (Requirements 3.6, 3.7).

        Never raises; a provider failure always maps to an ``"unavailable"``
        result so property creation is never blocked.
        """
        result = self._rentcast.get_property_record(selected_address)

        if not result.is_ok:
            # RentCast failed/timed out (an "unavailable" error). Signal that
            # the property can be created now and enrichment retried later.
            error = result.error
            message = (
                error.message
                if error is not None and error.message
                else "Property data could not be retrieved. You can enter details "
                "manually and try again later."
            )
            return EnrichmentResult(status="unavailable", message=message)

        details = result.value
        if details is None:
            # RentCast has no record for this address (404 / empty).
            return EnrichmentResult(
                status="not_found",
                message="No property data was found for this address. You can "
                "enter the details manually.",
            )

        # RentCast returned a record; hand back the prefilled, editable details.
        return EnrichmentResult(status="found", details=details)
