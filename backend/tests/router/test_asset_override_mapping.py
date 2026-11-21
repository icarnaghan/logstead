"""Route-level examples for depreciation-override request/response mapping.

Feature: depreciation-override-and-whole-dollar-display.

Covers `_asset_input` body → AssetInput override mapping (snake_case, camelCase,
empty/absent) and `_to_jsonable` serialization of an override map as
`{ "<year>": "<two-decimal string>" }`.

Validates: Requirements 1.4, 1.2
"""

from __future__ import annotations

from decimal import Decimal

from logstead.models.depreciation import DepreciableAsset
from logstead.router.handler import _asset_input, _to_jsonable


def test_asset_input_maps_snake_case_overrides():
    inp = _asset_input(
        {
            "description": "Building",
            "cost_basis": "140000",
            "placed_in_service_date": "2010-06-01",
            "depreciation_overrides": {"2010": "1952.00"},
        },
        "p1",
    )
    assert inp.depreciation_overrides == {2010: Decimal("1952.00")}


def test_asset_input_maps_camel_case_overrides():
    inp = _asset_input(
        {
            "description": "Building",
            "costBasis": "140000",
            "placedInServiceDate": "2010-06-01",
            "depreciationOverrides": {"2010": "1952.00"},
        },
        "p1",
    )
    assert inp.depreciation_overrides == {2010: Decimal("1952.00")}


def test_asset_input_absent_overrides_is_none():
    inp = _asset_input(
        {
            "description": "Building",
            "cost_basis": "140000",
            "placed_in_service_date": "2010-06-01",
        },
        "p1",
    )
    assert inp.depreciation_overrides is None


def test_to_jsonable_serializes_override_map_as_strings():
    asset = DepreciableAsset(
        id="a", property_id="p", description="Building",
        cost_basis=Decimal("140000.00"),
        placed_in_service_date="2010-06-01",
        recovery_period_years=Decimal("27.5"),
        depreciation_overrides={2010: Decimal("1952.00")},
    )
    rendered = _to_jsonable(asset)
    assert rendered["depreciation_overrides"] == {"2010": "1952.00"}
