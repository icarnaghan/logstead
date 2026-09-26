"""Broader adapter coverage for the RentCast adapter (task 7.5).

Requirements: 3.1, 3.2, 3.3, 3.8.

The narrow branch tests live in ``test_rentcast.py``. This module fills the
gaps task 7.5 calls out without duplicating them:

* full-field mapping incl. the flat (non-nested) ``features`` fallback (3.8),
* additional sparse / partial-record shapes (only-provided-fields, 3.3),
* the ``X-Api-Key`` header + ``address`` query construction against a real
  ``RentCastAdapter`` (not just ``map_record_to_details``),
* the bounded-timeout contract: the adapter always passes a positive timeout
  to ``fetch`` (default and custom), and
* the remaining transport-failure shape (``OSError``) that maps to
  ``unavailable`` (timeouts / ``URLError`` are covered in ``test_rentcast.py``).

Everything runs against a stubbed ``fetch`` so no network call is made.
"""

from __future__ import annotations

import json
import urllib.error
from decimal import Decimal

from logstead.adapters.rentcast import (
    DEFAULT_TIMEOUT_SECONDS,
    HttpResponse,
    RentCastAdapter,
    map_record_to_details,
)


def _capturing_adapter(
    response: HttpResponse, **kwargs: object
) -> tuple[RentCastAdapter, list[tuple[str, dict[str, str], float]]]:
    """Adapter whose fetch records every call and returns ``response``."""
    calls: list[tuple[str, dict[str, str], float]] = []

    def fetch(url: str, headers: dict[str, str], timeout: float) -> HttpResponse:
        calls.append((url, headers, timeout))
        return response

    adapter = RentCastAdapter(api_key="test-key", fetch=fetch, **kwargs)  # type: ignore[arg-type]
    return adapter, calls


class TestFlatFeaturesFallback:
    """RentCast may return features at the top level rather than nested (3.8)."""

    def test_maps_flat_top_level_feature_fields(self) -> None:
        record = {
            "addressLine1": "9 Flat St",
            # No nested "features" object; provider put them at the top level.
            "architectureType": "Ranch",
            "heating": True,
            "heatingType": "Baseboard",
            "cooling": True,
            "coolingType": "Window Unit",
            "garage": True,
            "garageType": "Detached",
            "pool": True,
            "poolType": "In Ground",
            "roofType": "Metal",
        }
        details = map_record_to_details(record)

        assert details.address_line1 == "9 Flat St"
        assert details.features.architecture_type == "Ranch"
        assert details.features.heating is True
        assert details.features.heating_type == "Baseboard"
        assert details.features.cooling is True
        assert details.features.cooling_type == "Window Unit"
        assert details.features.garage is True
        assert details.features.garage_type == "Detached"
        assert details.features.pool is True
        assert details.features.pool_type == "In Ground"
        assert details.features.roof_type == "Metal"

    def test_nested_features_take_precedence_over_flat(self) -> None:
        record = {
            "heatingType": "flat-heating",
            "features": {"heatingType": "nested-heating"},
        }
        details = map_record_to_details(record)
        assert details.features.heating_type == "nested-heating"

    def test_non_dict_features_object_is_ignored(self) -> None:
        # A malformed "features" value must not raise; treated as absent.
        record = {"city": "Reno", "features": "not-an-object"}
        details = map_record_to_details(record)
        assert details.city == "Reno"
        assert details.features.heating is None
        assert details.features.roof_type is None


class TestPartialRecords:
    """Only-provided-fields mapping across a few distinct sparse shapes (3.3)."""

    def test_geo_only_record(self) -> None:
        record = {"latitude": "40.1", "longitude": "-105.2"}
        details = map_record_to_details(record)
        assert details.latitude == Decimal("40.1")
        assert details.longitude == Decimal("-105.2")
        assert details.formatted_address is None
        assert details.city is None
        assert details.bedrooms is None

    def test_structure_only_record(self) -> None:
        record = {
            "propertyType": "Condo",
            "bedrooms": 2,
            "bathrooms": 1.5,
            "squareFootage": 900,
            "yearBuilt": 2005,
        }
        details = map_record_to_details(record)
        assert details.property_type == "Condo"
        assert details.bedrooms == 2
        assert details.bathrooms == Decimal("1.5")
        assert details.living_area_sqft == 900
        assert details.year_built == 2005
        assert details.address_line1 is None
        assert details.features.heating is None

    def test_invalid_numeric_values_drop_to_unset(self) -> None:
        # Non-numeric provider values must not raise; they map to unset (3.3).
        record = {
            "bedrooms": "three",
            "bathrooms": "n/a",
            "latitude": "not-a-number",
            "yearBuilt": "recently",
            "squareFootage": "big",
        }
        details = map_record_to_details(record)
        assert details.bedrooms is None
        assert details.bathrooms is None
        assert details.latitude is None
        assert details.year_built is None
        assert details.living_area_sqft is None

    def test_empty_record_maps_to_all_unset(self) -> None:
        details = map_record_to_details({})
        assert details.formatted_address is None
        assert details.city is None
        assert details.bedrooms is None
        assert details.latitude is None
        assert details.features.heating is None


class TestRequestConstruction:
    """The adapter builds the GET /properties?address= request correctly (3.2)."""

    def test_sends_api_key_header_and_url_encoded_address(self) -> None:
        adapter, calls = _capturing_adapter(
            HttpResponse(status=200, body=json.dumps([{"city": "Austin"}]))
        )
        adapter.get_property_record("742 Evergreen Ter, Springfield, IL 62704")

        url, headers, _timeout = calls[0]
        assert headers["X-Api-Key"] == "test-key"
        assert headers["Accept"] == "application/json"
        assert url.startswith("https://api.rentcast.io/v1/properties?")
        # Address is URL-encoded (spaces -> +, comma -> %2C).
        assert "address=742+Evergreen+Ter%2C+Springfield%2C+IL+62704" in url

    def test_omits_api_key_header_when_no_key_configured(self) -> None:
        calls: list[tuple[str, dict[str, str], float]] = []

        def fetch(url: str, headers: dict[str, str], timeout: float) -> HttpResponse:
            calls.append((url, headers, timeout))
            return HttpResponse(status=200, body="[]")

        adapter = RentCastAdapter(api_key=None, fetch=fetch)
        adapter.get_property_record("123 Main St")

        _url, headers, _timeout = calls[0]
        assert "X-Api-Key" not in headers


class TestBoundedTimeout:
    """The adapter must pass a positive, bounded timeout to fetch."""

    def test_default_timeout_is_positive_and_passed_through(self) -> None:
        adapter, calls = _capturing_adapter(HttpResponse(status=200, body="[]"))
        adapter.get_property_record("123 Main St")

        _url, _headers, timeout = calls[0]
        assert timeout == DEFAULT_TIMEOUT_SECONDS
        assert timeout > 0

    def test_custom_timeout_is_passed_through(self) -> None:
        adapter, calls = _capturing_adapter(
            HttpResponse(status=200, body="[]"), timeout=1.25
        )
        adapter.get_property_record("123 Main St")

        _url, _headers, timeout = calls[0]
        assert timeout == 1.25
        assert timeout > 0


class TestTransportFailures:
    """Remaining transport-failure shape maps to unavailable (3.2)."""

    def test_oserror_maps_to_unavailable(self) -> None:
        def fetch(url: str, headers: dict[str, str], timeout: float) -> HttpResponse:
            raise OSError("socket blew up")

        adapter = RentCastAdapter(api_key="k", fetch=fetch)
        result = adapter.get_property_record("123 Main St")

        assert not result.is_ok
        assert result.error is not None
        assert result.error.kind == "unavailable"

    def test_url_error_wrapping_timeout_maps_to_unavailable(self) -> None:
        # urllib surfaces a socket timeout as URLError(reason=TimeoutError).
        def fetch(url: str, headers: dict[str, str], timeout: float) -> HttpResponse:
            raise urllib.error.URLError(TimeoutError("timed out"))

        adapter = RentCastAdapter(api_key="k", fetch=fetch)
        result = adapter.get_property_record("123 Main St")

        assert not result.is_ok
        assert result.error is not None
        assert result.error.kind == "unavailable"
        assert "unavailable" in result.error.message.lower()
