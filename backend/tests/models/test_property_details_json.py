"""Round-trip tests for PropertyDetails <-> JSON serialization (Req 12.1, 13.3).

Proves the storage boundary preserves the two precision invariants:

* money fields survive as exact two-decimal ``Decimal`` with no float drift, and
* non-money decimals (latitude/longitude) keep full precision.

Also proves sparse omission (absent/empty fields are dropped) and that the
nested / year-keyed structures (features, HOA, owner, tax assessments, property
taxes, sale history) round-trip through the JSON string unchanged.
"""

from __future__ import annotations

import json
from decimal import Decimal

from logstead.models.property import (
    HoaDetails,
    PropertyDetails,
    PropertyFeatures,
    PropertyOwner,
    PropertyTax,
    SaleEvent,
    TaxAssessment,
)
from logstead.models.property_details_json import (
    details_from_dict,
    details_from_json,
    details_to_dict,
    details_to_json,
)


def _rich_details() -> PropertyDetails:
    return PropertyDetails(
        formatted_address="123 Main St, Austin, TX 78701",
        address_line1="123 Main St",
        city="Austin",
        state="TX",
        zip_code="78701",
        county="Travis",
        latitude=Decimal("30.26715012345"),
        longitude=Decimal("-97.74310098765"),
        property_type="Single Family",
        bedrooms=3,
        bathrooms=Decimal("2.5"),
        living_area_sqft=1800,
        lot_size=Decimal("6500"),
        year_built=1995,
        assessor_id="R12345",
        legal_description="LOT 4 BLK 2",
        subdivision="Sunset",
        zoning="R1",
        last_sale_date="2019-06-15",
        last_sale_price=Decimal("415000.00"),
        features=PropertyFeatures(
            architecture_type="Contemporary",
            roof_type="Shingle",
            heating=True,
            heating_type="Forced Air",
            cooling=False,
            garage=True,
            garage_spaces=2,
            garage_type="Attached",
            pool=False,
            fireplace=True,
            fireplace_type="Gas",
            floor_count=2,
            room_count=7,
            unit_count=1,
        ),
        hoa=HoaDetails(fee=Decimal("150.00")),
        owner=PropertyOwner(names=["Jane Doe"], type="Individual", occupied=True),
        tax_assessments=[
            TaxAssessment(
                year=2021,
                value=Decimal("380000.00"),
                land=Decimal("90000.00"),
                improvements=Decimal("290000.00"),
            ),
            TaxAssessment(year=2022, value=Decimal("400000.00")),
        ],
        property_taxes=[
            PropertyTax(year=2021, total=Decimal("6200.00")),
            PropertyTax(year=2022, total=Decimal("6500.00")),
        ],
        sale_history=[
            SaleEvent(date="2019-06-15", price=Decimal("415000.00"), event="Sale"),
            SaleEvent(date="2012-03-01", price=Decimal("250000.00"), event="Sale"),
        ],
    )


class TestRoundTrip:
    def test_rich_details_round_trip_via_json(self) -> None:
        original = _rich_details()
        restored = details_from_json(details_to_json(original))
        assert restored == original

    def test_money_fields_survive_as_exact_two_decimal_decimals(self) -> None:
        details = PropertyDetails(
            last_sale_price=Decimal("415000.00"),
            hoa=HoaDetails(fee=Decimal("150.10")),
            tax_assessments=[TaxAssessment(year=2022, value=Decimal("0.01"))],
            property_taxes=[PropertyTax(year=2022, total=Decimal("6500.00"))],
            sale_history=[SaleEvent(date="2019-06-15", price=Decimal("415000.55"))],
        )
        raw = details_to_json(details)
        # Money is rendered as two-decimal strings in the JSON document.
        doc = json.loads(raw)
        assert doc["last_sale_price"] == "415000.00"
        assert doc["hoa"]["fee"] == "150.10"
        assert doc["tax_assessments"][0]["value"] == "0.01"
        assert doc["sale_history"][0]["price"] == "415000.55"

        restored = details_from_json(raw)
        assert restored.last_sale_price == Decimal("415000.00")
        assert restored.hoa is not None and restored.hoa.fee == Decimal("150.10")
        assert restored.tax_assessments[0].value == Decimal("0.01")
        assert restored.property_taxes[0].total == Decimal("6500.00")
        assert restored.sale_history[0].price == Decimal("415000.55")

    def test_money_quantized_to_two_places_without_drift(self) -> None:
        # A three-decimal input is quantized to exactly two places (half-up).
        details = PropertyDetails(last_sale_price=Decimal("100.005"))
        restored = details_from_json(details_to_json(details))
        assert restored.last_sale_price == Decimal("100.01")

    def test_latitude_longitude_full_precision_preserved(self) -> None:
        details = PropertyDetails(
            latitude=Decimal("30.26715012345"),
            longitude=Decimal("-97.74310098765"),
        )
        doc = json.loads(details_to_json(details))
        # Non-money decimals render as their plain string (no quantization).
        assert doc["latitude"] == "30.26715012345"
        assert doc["longitude"] == "-97.74310098765"

        restored = details_from_json(details_to_json(details))
        assert restored.latitude == Decimal("30.26715012345")
        assert restored.longitude == Decimal("-97.74310098765")


class TestSparseOmission:
    def test_empty_details_serialize_to_empty_document(self) -> None:
        doc = details_to_dict(PropertyDetails())
        assert doc == {}

    def test_absent_and_empty_fields_are_omitted(self) -> None:
        details = PropertyDetails(city="Austin", features=PropertyFeatures())
        doc = details_to_dict(details)
        assert doc == {"city": "Austin"}
        # No features/hoa/owner/list keys when nothing is present.
        assert "features" not in doc
        assert "hoa" not in doc
        assert "owner" not in doc
        assert "tax_assessments" not in doc

    def test_sparse_round_trip_yields_only_present_fields(self) -> None:
        details = PropertyDetails(
            city="Austin",
            bedrooms=2,
            features=PropertyFeatures(heating=True),
        )
        restored = details_from_json(details_to_json(details))
        assert restored == details
        # Everything omitted stays unset.
        assert restored.state is None
        assert restored.last_sale_price is None
        assert restored.hoa is None
        assert restored.tax_assessments == []


class TestNestedStructures:
    def test_features_boolean_and_string_fields_round_trip(self) -> None:
        details = PropertyDetails(
            features=PropertyFeatures(
                heating=True,
                heating_type="Forced Air",
                cooling=False,
                garage_spaces=3,
            )
        )
        restored = details_from_dict(details_to_dict(details))
        assert restored.features.heating is True
        assert restored.features.heating_type == "Forced Air"
        assert restored.features.cooling is False
        assert restored.features.garage_spaces == 3

    def test_year_keyed_lists_round_trip_in_order(self) -> None:
        details = PropertyDetails(
            tax_assessments=[
                TaxAssessment(year=2020, value=Decimal("100.00")),
                TaxAssessment(year=2021, value=Decimal("110.00")),
            ],
            property_taxes=[PropertyTax(year=2021, total=Decimal("6.50"))],
        )
        restored = details_from_dict(details_to_dict(details))
        assert [a.year for a in restored.tax_assessments] == [2020, 2021]
        assert restored.tax_assessments[1].value == Decimal("110.00")
        assert restored.property_taxes[0].total == Decimal("6.50")
