"""Broader compose-behavior coverage for AddressEnrichmentService (task 7.5).

Requirements: 3.1, 3.2, 3.3, 3.8.

The narrow service tests live in ``test_enrichment.py``. This module fills the
gaps task 7.5 calls out without duplicating them:

* ``suggest`` delegates to autocomplete, including inheriting its empty
  degradation (Req 3.1) — verified both with a stub and through the real
  ``AutocompleteAdapter`` wired to a failing/stubbed ``fetch``.
* ``enrich`` maps the RentCast found / not_found / unavailable outcomes to an
  ``EnrichmentResult`` with the correct ``details`` / ``message`` /
  ``can_retry_later`` — verified through the real ``RentCastAdapter`` composed
  into the service, so the full compose path (adapter mapping -> service
  classification) is exercised, not just a canned ``Result`` (Req 3.2, 3.3, 3.8).

No network is hit: the real adapters are constructed with a stubbed ``fetch``.
"""

from __future__ import annotations

import json


from typing import Any

from logstead.adapters.autocomplete import AutocompleteAdapter
from logstead.adapters.rentcast import HttpResponse as RcHttpResponse
from logstead.adapters.rentcast import RentCastAdapter
from logstead.models.property import AddressSuggestion
from logstead.services.enrichment import AddressEnrichmentService


class _StubGeoClient:
    """A stub Amazon Location geo-places client for the autocomplete adapter."""

    def __init__(self, response: Any = None, error: Exception | None = None) -> None:
        self._response = response
        self._error = error

    def autocomplete(self, **kwargs: Any) -> Any:
        if self._error is not None:
            raise self._error
        return self._response


def _service_with_real_adapters(
    *,
    autocomplete_response: Any = None,
    autocomplete_error: Exception | None = None,
    rentcast_response: RcHttpResponse | None = None,
    rentcast_fetch=None,
) -> AddressEnrichmentService:
    """Wire the service to REAL adapters backed by stubs (no network/AWS)."""

    def _rc_fetch(url, headers, timeout):
        assert rentcast_response is not None
        return rentcast_response

    autocomplete = AutocompleteAdapter(
        client=_StubGeoClient(response=autocomplete_response, error=autocomplete_error)
    )
    rentcast = RentCastAdapter(api_key="rc-key", fetch=rentcast_fetch or _rc_fetch)
    return AddressEnrichmentService(autocomplete, rentcast)


# --- suggest compose + empty degradation (Requirement 3.1) -------------------


class TestSuggestCompose:
    def test_suggest_maps_results_through_real_autocomplete(self) -> None:
        response = {
            "ResultItems": [
                {"PlaceId": "p1", "Address": {"Label": "1 Main St, Reno, NV"}},
                {"PlaceId": "p2", "Address": {"Label": "2 Main St, Reno, NV"}},
            ]
        }
        service = _service_with_real_adapters(autocomplete_response=response)

        assert service.suggest_addresses("main") == [
            AddressSuggestion(formatted_address="1 Main St, Reno, NV", provider_place_id="p1"),
            AddressSuggestion(formatted_address="2 Main St, Reno, NV", provider_place_id="p2"),
        ]

    def test_suggest_inherits_empty_degradation_on_provider_failure(self) -> None:
        # Autocomplete degrades to [] on failure; the service must surface that
        # empty list unchanged (never raising) so it can't gate creation.
        service = _service_with_real_adapters(
            autocomplete_error=RuntimeError("ThrottlingException")
        )
        assert service.suggest_addresses("anything") == []

    def test_suggest_inherits_empty_degradation_on_unexpected_shape(self) -> None:
        service = _service_with_real_adapters(autocomplete_response={"foo": "bar"})
        assert service.suggest("anything") == []


# --- enrich compose: found (Requirements 3.2, 3.8) ---------------------------


class TestEnrichComposeFound:
    def test_found_returns_details_mapped_by_real_rentcast_adapter(self) -> None:
        record = {
            "formattedAddress": "123 Elm St, Denver, CO 80202",
            "city": "Denver",
            "state": "CO",
            "bedrooms": 3,
            "features": {"heating": True, "heatingType": "Forced Air"},
        }
        service = _service_with_real_adapters(
            rentcast_response=RcHttpResponse(status=200, body=json.dumps([record]))
        )

        result = service.enrich("123 Elm St")

        assert result.status == "found"
        assert result.is_found is True
        assert result.can_retry_later is False
        assert result.details is not None
        assert result.details.formatted_address == "123 Elm St, Denver, CO 80202"
        assert result.details.city == "Denver"
        assert result.details.bedrooms == 3
        assert result.details.features.heating is True
        assert result.details.features.heating_type == "Forced Air"

    def test_found_from_sparse_record_carries_only_provided_fields(self) -> None:
        # Compose path preserves the adapter's sparse mapping (Req 3.3).
        record = {"addressLine1": "9 Sparse Ln"}
        service = _service_with_real_adapters(
            rentcast_response=RcHttpResponse(status=200, body=json.dumps([record]))
        )

        result = service.enrich("9 Sparse Ln")

        assert result.status == "found"
        assert result.details is not None
        assert result.details.address_line1 == "9 Sparse Ln"
        assert result.details.city is None
        assert result.details.bedrooms is None


# --- enrich compose: not_found (Requirement 3.5) -----------------------------


class TestEnrichComposeNotFound:
    def test_404_from_real_adapter_maps_to_not_found(self) -> None:
        service = _service_with_real_adapters(
            rentcast_response=RcHttpResponse(status=404, body='{"error":"nope"}')
        )

        result = service.enrich("Nowhere Rd")

        assert result.status == "not_found"
        assert result.is_found is False
        assert result.can_retry_later is False
        assert result.details is None
        assert result.message is not None

    def test_empty_list_from_real_adapter_maps_to_not_found(self) -> None:
        service = _service_with_real_adapters(
            rentcast_response=RcHttpResponse(status=200, body="[]")
        )

        result = service.enrich("Nowhere Rd")

        assert result.status == "not_found"
        assert result.details is None


# --- enrich compose: unavailable (Requirements 3.6, 3.7) ---------------------


class TestEnrichComposeUnavailable:
    def test_5xx_from_real_adapter_maps_to_unavailable(self) -> None:
        service = _service_with_real_adapters(
            rentcast_response=RcHttpResponse(status=503, body="down")
        )

        result = service.enrich("500 Slow Way")

        assert result.status == "unavailable"
        assert result.is_found is False
        assert result.can_retry_later is True
        assert result.details is None
        assert result.message  # a usable "could not be retrieved" message

    def test_timeout_from_real_adapter_maps_to_unavailable(self) -> None:
        def timing_out_fetch(url, headers, timeout):
            raise TimeoutError("timed out")

        service = _service_with_real_adapters(rentcast_fetch=timing_out_fetch)

        result = service.enrich("500 Slow Way")

        assert result.status == "unavailable"
        assert result.can_retry_later is True
        assert result.details is None
        assert result.message
