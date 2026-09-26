"""Unit tests for the RentCast adapter (Requirements 3.2, 3.3, 3.8, 12.1, 12.2).

These exercise the mapping, not_found, and unavailable branches against a
stubbed HTTP layer so no network call is ever made. Broader integration
coverage lives in task 7.5.
"""

from __future__ import annotations

import json
import urllib.error
from decimal import Decimal

import pytest

from logstead.adapters.rentcast import (
    HttpResponse,
    RentCastAdapter,
    map_record_to_details,
)


def _adapter_returning(response: HttpResponse) -> RentCastAdapter:
    """Build an adapter whose fetch always returns ``response``."""
    calls: list[tuple[str, dict[str, str], float]] = []

    def fetch(url: str, headers: dict[str, str], timeout: float) -> HttpResponse:
        calls.append((url, headers, timeout))
        return response

    adapter = RentCastAdapter(api_key="test-key", fetch=fetch)
    adapter._calls = calls  # type: ignore[attr-defined]  # exposed for assertions
    return adapter


FULL_RECORD = {
    "formattedAddress": "123 Main St, Austin, TX 78701",
    "addressLine1": "123 Main St",
    "addressLine2": "Apt 4",
    "city": "Austin",
    "state": "TX",
    "zipCode": "78701",
    "county": "Travis",
    "latitude": 30.2672,
    "longitude": -97.7431,
    "propertyType": "Single Family",
    "bedrooms": 3,
    "bathrooms": 2.5,
    "squareFootage": 1800,
    "lotSize": 6500,
    "yearBuilt": 1995,
    "assessorID": "R12345",
    "legalDescription": "LOT 4 BLK 2 SUNSET SUBDIVISION",
    "subdivision": "Sunset",
    "zoning": "R1",
    "lastSaleDate": "2019-06-15",
    "lastSalePrice": 415000,
    "features": {
        "architectureType": "Contemporary",
        "exteriorType": "Brick",
        "foundationType": "Slab",
        "roofType": "Shingle",
        "viewType": "City",
        "heating": True,
        "heatingType": "Forced Air",
        "cooling": True,
        "coolingType": "Central",
        "garage": True,
        "garageSpaces": 2,
        "garageType": "Attached",
        "pool": False,
        "poolType": "None",
        "fireplace": True,
        "fireplaceType": "Gas",
        "floorCount": 2,
        "roomCount": 7,
        "unitCount": 1,
    },
    "hoa": {"fee": 150},
    "taxAssessments": {
        "2021": {"year": 2021, "value": 380000, "land": 90000, "improvements": 290000},
        "2022": {"year": 2022, "value": 400000, "land": 95000, "improvements": 305000},
    },
    "propertyTaxes": {
        "2021": {"year": 2021, "total": 6200},
        "2022": {"year": 2022, "total": 6500},
    },
    "history": {
        "2019-06-15": {"event": "Sale", "date": "2019-06-15", "price": 415000},
        "2012-03-01": {"event": "Sale", "date": "2012-03-01", "price": 250000},
    },
    "owner": {
        "names": ["Jane Doe"],
        "type": "Individual",
    },
    "ownerOccupied": True,
}


class TestMapping:
    def test_maps_all_provided_fields(self) -> None:
        response = HttpResponse(status=200, body=json.dumps([FULL_RECORD]))
        result = _adapter_returning(response).get_property_record("123 Main St")

        assert result.is_ok
        details = result.value
        assert details is not None
        assert details.formatted_address == "123 Main St, Austin, TX 78701"
        assert details.address_line1 == "123 Main St"
        assert details.address_line2 == "Apt 4"
        assert details.city == "Austin"
        assert details.state == "TX"
        assert details.zip_code == "78701"
        assert details.county == "Travis"
        assert details.latitude == Decimal("30.2672")
        assert details.longitude == Decimal("-97.7431")
        assert details.property_type == "Single Family"
        assert details.bedrooms == 3
        assert details.bathrooms == Decimal("2.5")
        assert details.living_area_sqft == 1800
        assert details.lot_size == Decimal("6500")
        assert details.year_built == 1995
        # Parcel / legal + last sale (top-level).
        assert details.assessor_id == "R12345"
        assert details.legal_description == "LOT 4 BLK 2 SUNSET SUBDIVISION"
        assert details.subdivision == "Sunset"
        assert details.zoning == "R1"
        assert details.last_sale_date == "2019-06-15"
        assert details.last_sale_price == Decimal("415000.00")
        # Features: descriptive *_type strings + separate boolean presence flags
        # (the boolean fix — heating is a flag, heating_type is the string).
        assert details.features.architecture_type == "Contemporary"
        assert details.features.exterior_type == "Brick"
        assert details.features.foundation_type == "Slab"
        assert details.features.roof_type == "Shingle"
        assert details.features.view_type == "City"
        assert details.features.heating is True
        assert details.features.heating_type == "Forced Air"
        assert details.features.cooling is True
        assert details.features.cooling_type == "Central"
        assert details.features.garage is True
        assert details.features.garage_spaces == 2
        assert details.features.garage_type == "Attached"
        assert details.features.pool is False
        assert details.features.pool_type == "None"
        assert details.features.fireplace is True
        assert details.features.fireplace_type == "Gas"
        assert details.features.floor_count == 2
        assert details.features.room_count == 7
        assert details.features.unit_count == 1
        # HOA fee (money).
        assert details.hoa is not None
        assert details.hoa.fee == Decimal("150.00")
        # Owner (names/type + top-level ownerOccupied folded in).
        assert details.owner is not None
        assert details.owner.names == ["Jane Doe"]
        assert details.owner.type == "Individual"
        assert details.owner.occupied is True
        # Tax assessments sorted ascending by year; money as Decimal.
        assert [a.year for a in details.tax_assessments] == [2021, 2022]
        assert details.tax_assessments[1].value == Decimal("400000.00")
        assert details.tax_assessments[1].land == Decimal("95000.00")
        assert details.tax_assessments[1].improvements == Decimal("305000.00")
        # Property taxes sorted ascending by year.
        assert [t.year for t in details.property_taxes] == [2021, 2022]
        assert details.property_taxes[1].total == Decimal("6500.00")
        # Sale history sorted date-descending; money as Decimal.
        assert [e.date for e in details.sale_history] == ["2019-06-15", "2012-03-01"]
        assert details.sale_history[0].event == "Sale"
        assert details.sale_history[0].price == Decimal("415000.00")

    def test_copies_only_provided_fields_leaving_others_unset(self) -> None:
        # Sparse record: only address + city present.
        record = {"addressLine1": "500 Oak Ave", "city": "Dallas"}
        details = map_record_to_details(record)

        assert details.address_line1 == "500 Oak Ave"
        assert details.city == "Dallas"
        # Everything the provider omitted stays unset.
        assert details.state is None
        assert details.zip_code is None
        assert details.bedrooms is None
        assert details.bathrooms is None
        assert details.latitude is None
        assert details.year_built is None
        assert details.features.heating is None
        assert details.features.roof_type is None

    def test_blank_and_null_values_treated_as_absent(self) -> None:
        record = {"city": "  ", "state": None, "bedrooms": "", "propertyType": "Condo"}
        details = map_record_to_details(record)

        assert details.city is None
        assert details.state is None
        assert details.bedrooms is None
        assert details.property_type == "Condo"

    def test_accepts_single_object_payload(self) -> None:
        response = HttpResponse(status=200, body=json.dumps(FULL_RECORD))
        result = _adapter_returning(response).get_property_record("123 Main St")
        assert result.is_ok
        assert result.value is not None
        assert result.value.city == "Austin"

    def test_sends_api_key_header_and_address_query(self) -> None:
        response = HttpResponse(status=200, body=json.dumps([FULL_RECORD]))
        adapter = _adapter_returning(response)
        adapter.get_property_record("123 Main St, Austin, TX")

        url, headers, timeout = adapter._calls[0]  # type: ignore[attr-defined]
        assert headers["X-Api-Key"] == "test-key"
        assert "address=123+Main+St%2C+Austin%2C+TX" in url
        assert timeout > 0


class TestNotFound:
    def test_404_maps_to_none(self) -> None:
        response = HttpResponse(status=404, body='{"error": "not found"}')
        result = _adapter_returning(response).get_property_record("nowhere")
        assert result.is_ok
        assert result.value is None

    def test_empty_list_maps_to_none(self) -> None:
        response = HttpResponse(status=200, body="[]")
        result = _adapter_returning(response).get_property_record("nowhere")
        assert result.is_ok
        assert result.value is None

    def test_empty_body_maps_to_none(self) -> None:
        response = HttpResponse(status=200, body="")
        result = _adapter_returning(response).get_property_record("nowhere")
        assert result.is_ok
        assert result.value is None


class TestUnavailable:
    def test_5xx_maps_to_unavailable(self) -> None:
        response = HttpResponse(status=503, body="upstream down")
        result = _adapter_returning(response).get_property_record("123 Main St")
        assert not result.is_ok
        assert result.error is not None
        assert result.error.kind == "unavailable"

    def test_other_4xx_maps_to_unavailable(self) -> None:
        response = HttpResponse(status=401, body="bad key")
        result = _adapter_returning(response).get_property_record("123 Main St")
        assert not result.is_ok
        assert result.error is not None
        assert result.error.kind == "unavailable"

    def test_network_error_maps_to_unavailable(self) -> None:
        def fetch(url: str, headers: dict[str, str], timeout: float) -> HttpResponse:
            raise urllib.error.URLError("connection refused")

        adapter = RentCastAdapter(api_key="k", fetch=fetch)
        result = adapter.get_property_record("123 Main St")
        assert not result.is_ok
        assert result.error is not None
        assert result.error.kind == "unavailable"

    def test_timeout_maps_to_unavailable(self) -> None:
        def fetch(url: str, headers: dict[str, str], timeout: float) -> HttpResponse:
            raise TimeoutError("timed out")

        adapter = RentCastAdapter(api_key="k", fetch=fetch)
        result = adapter.get_property_record("123 Main St")
        assert not result.is_ok
        assert result.error is not None
        assert result.error.kind == "unavailable"

    def test_unreadable_body_maps_to_unavailable(self) -> None:
        response = HttpResponse(status=200, body="{not json")
        result = _adapter_returning(response).get_property_record("123 Main St")
        assert not result.is_ok
        assert result.error is not None
        assert result.error.kind == "unavailable"
