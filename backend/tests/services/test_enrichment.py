"""Unit tests for the AddressEnrichmentService (task 7.3).

Covers Requirements 3.1 (suggest passthrough), 3.2/3.4 (found → editable
details), 3.5 (not_found), and 3.6/3.7 (unavailable → "enrich later" signal so
property creation can proceed without details).

Both adapters are stubbed so the tests never touch the network. The Property 5
property-based test (task 7.4) and the broad adapter tests (task 7.5) are
intentionally not implemented here.
"""

from __future__ import annotations

from logstead.models.property import AddressSuggestion, PropertyDetails
from logstead.models.result import Result
from logstead.services.enrichment import AddressEnrichmentService, EnrichmentResult


class _StubAutocomplete:
    """Autocomplete adapter stub that returns fixed suggestion / unit lists."""

    def __init__(
        self,
        result: list[AddressSuggestion],
        units: list[AddressSuggestion] | None = None,
    ) -> None:
        self._result = result
        self._units = units or []
        self.calls: list[str] = []
        self.unit_calls: list[str] = []

    def suggestions(self, query: str) -> list[AddressSuggestion]:
        self.calls.append(query)
        return self._result

    def secondary_addresses(self, address: str) -> list[AddressSuggestion]:
        self.unit_calls.append(address)
        return self._units


class _StubRentCast:
    """RentCast adapter stub that returns a canned Result."""

    def __init__(self, result: Result[PropertyDetails | None]) -> None:
        self._result = result
        self.calls: list[str] = []

    def get_property_record(self, address: str) -> Result[PropertyDetails | None]:
        self.calls.append(address)
        return self._result


def _service(
    *,
    suggestions: list[AddressSuggestion] | None = None,
    units: list[AddressSuggestion] | None = None,
    rentcast: Result[PropertyDetails | None] | None = None,
) -> tuple[AddressEnrichmentService, _StubAutocomplete, _StubRentCast]:
    autocomplete = _StubAutocomplete(suggestions or [], units=units)
    rc = _StubRentCast(rentcast or Result.success(None))
    return AddressEnrichmentService(autocomplete, rc), autocomplete, rc


# --- suggest passthrough (Requirement 3.1) -----------------------------------

def test_suggest_addresses_delegates_to_autocomplete():
    expected = [
        AddressSuggestion(formatted_address="1 Main St, Springfield, IL", provider_place_id="p1"),
        AddressSuggestion(formatted_address="2 Main St, Springfield, IL"),
    ]
    service, autocomplete, _ = _service(suggestions=expected)

    result = service.suggest_addresses("main st")

    assert result == expected
    assert autocomplete.calls == ["main st"]


def test_suggest_alias_matches_suggest_addresses():
    expected = [AddressSuggestion(formatted_address="99 Oak Ave, Portland, OR")]
    service, _, _ = _service(suggestions=expected)

    assert service.suggest("oak") == expected


def test_suggest_returns_empty_when_autocomplete_has_nothing():
    service, _, _ = _service(suggestions=[])

    assert service.suggest_addresses("nomatch") == []


# --- unit_addresses passthrough (Requirement 3.1) ----------------------------

def test_unit_addresses_delegates_to_autocomplete():
    units = [
        AddressSuggestion(
            formatted_address="123 Main St Unit 101, Springfield, IL 62704",
            provider_place_id="u101",
        ),
        AddressSuggestion(
            formatted_address="123 Main St Unit 102, Springfield, IL 62704",
            provider_place_id="u102",
        ),
    ]
    service, autocomplete, _ = _service(units=units)

    result = service.unit_addresses("123 Main St, Springfield, IL 62704")

    assert result == units
    assert autocomplete.unit_calls == ["123 Main St, Springfield, IL 62704"]


def test_unit_addresses_returns_empty_when_building_has_no_units():
    service, _, _ = _service(units=[])

    assert service.unit_addresses("123 Elm St, Denver, CO") == []


# --- enrich: found (Requirements 3.2, 3.4) -----------------------------------

def test_enrich_found_returns_editable_details():
    details = PropertyDetails(
        formatted_address="123 Elm St, Denver, CO 80202",
        city="Denver",
        state="CO",
        bedrooms=3,
    )
    service, _, rentcast = _service(rentcast=Result.success(details))

    result = service.enrich("123 Elm St")

    assert isinstance(result, EnrichmentResult)
    assert result.status == "found"
    assert result.is_found is True
    assert result.can_retry_later is False
    assert result.details is details
    assert rentcast.calls == ["123 Elm St"]


# --- enrich: not_found (Requirement 3.5) -------------------------------------

def test_enrich_not_found_signals_no_record_with_no_details():
    service, _, _ = _service(rentcast=Result.success(None))

    result = service.enrich("Nowhere Rd")

    assert result.status == "not_found"
    assert result.is_found is False
    assert result.can_retry_later is False
    assert result.details is None
    assert result.message is not None  # a "no data found" message for the UI


# --- enrich: unavailable / "enrich later" (Requirements 3.6, 3.7) ------------

def test_enrich_unavailable_signals_enrich_later_without_details():
    service, _, _ = _service(
        rentcast=Result.failure(
            "unavailable", "Property enrichment is temporarily unavailable: timeout"
        )
    )

    result = service.enrich("500 Slow Provider Way")

    assert result.status == "unavailable"
    assert result.is_found is False
    # The "enrich later" signal: caller can create the property now and retry.
    assert result.can_retry_later is True
    assert result.details is None
    # Surfaces the adapter's message so the UI can explain the failure.
    assert result.message is not None
    assert "temporarily unavailable" in result.message


def test_enrich_unavailable_uses_fallback_message_when_adapter_gives_none():
    # A failure Result with an empty message still yields a usable UI message.
    service, _, _ = _service(rentcast=Result.failure("unavailable", ""))

    result = service.enrich("addr")

    assert result.status == "unavailable"
    assert result.can_retry_later is True
    assert result.message  # non-empty fallback
