"""Unit tests for the address autocomplete adapter (Requirement 3.1).

Amazon Location Service (geo-places Autocomplete) backs the adapter. These
exercise the response mapping and the graceful-degradation branches against a
stubbed boto3 client so no AWS call is ever made. Every failure mode (client
error, throttle, unexpected shape) must degrade to an empty suggestion list
rather than raising.
"""

from __future__ import annotations

from typing import Any

from logstead.adapters.autocomplete import (
    AutocompleteAdapter,
    map_response_to_suggestions,
    map_secondary_addresses,
)
from logstead.models.property import AddressSuggestion


class _StubClient:
    """A stub geo-places client returning a canned response or raising.

    Backs both the ``autocomplete`` and the ``geocode`` operations; the same
    canned ``response``/``error`` is used for whichever one the adapter calls.
    """

    def __init__(self, response: Any = None, error: Exception | None = None) -> None:
        self._response = response
        self._error = error
        self.calls: list[dict[str, Any]] = []
        self.geocode_calls: list[dict[str, Any]] = []

    def autocomplete(self, **kwargs: Any) -> Any:
        self.calls.append(kwargs)
        if self._error is not None:
            raise self._error
        return self._response

    def geocode(self, **kwargs: Any) -> Any:
        self.geocode_calls.append(kwargs)
        if self._error is not None:
            raise self._error
        return self._response


def _adapter_returning(response: Any) -> tuple[AutocompleteAdapter, _StubClient]:
    client = _StubClient(response=response)
    return AutocompleteAdapter(client=client), client


RESULT_ITEMS_RESPONSE = {
    "ResultItems": [
        {
            "PlaceId": "place-1",
            "Title": "123 Main St",
            "Address": {"Label": "123 Main St, Austin, TX, USA"},
        },
        {
            "PlaceId": "place-2",
            "Title": "123 Main Ave",
            "Address": {"Label": "123 Main Ave, Dallas, TX, USA"},
        },
    ]
}


class TestMapping:
    def test_maps_result_items_to_suggestions(self) -> None:
        adapter, _client = _adapter_returning(RESULT_ITEMS_RESPONSE)

        result = adapter.suggestions("123 Main")

        assert result == [
            AddressSuggestion(
                formatted_address="123 Main St, Austin, TX, USA",
                provider_place_id="place-1",
            ),
            AddressSuggestion(
                formatted_address="123 Main Ave, Dallas, TX, USA",
                provider_place_id="place-2",
            ),
        ]

    def test_sends_query_text_and_single_use(self) -> None:
        adapter, client = _adapter_returning(RESULT_ITEMS_RESPONSE)

        adapter.suggestions("123 Main St")

        assert client.calls[0]["QueryText"] == "123 Main St"
        assert client.calls[0]["IntendedUse"] == "SingleUse"
        assert client.calls[0]["MaxResults"] > 0

    def test_item_without_place_id_maps_to_none(self) -> None:
        suggestions = map_response_to_suggestions(
            {"ResultItems": [{"Address": {"Label": "500 Oak Ave, Dallas, TX"}}]}
        )
        assert suggestions == [
            AddressSuggestion(
                formatted_address="500 Oak Ave, Dallas, TX",
                provider_place_id=None,
            )
        ]

    def test_falls_back_to_title_when_no_label(self) -> None:
        suggestions = map_response_to_suggestions(
            {"ResultItems": [{"PlaceId": "t1", "Title": "Fallback Title"}]}
        )
        assert suggestions == [
            AddressSuggestion(
                formatted_address="Fallback Title", provider_place_id="t1"
            )
        ]

    def test_items_without_any_address_string_are_skipped(self) -> None:
        suggestions = map_response_to_suggestions(
            {
                "ResultItems": [
                    {"PlaceId": "no-text"},
                    {"PlaceId": "blank", "Address": {"Label": "  "}},
                    {"PlaceId": "ok", "Address": {"Label": "1 Real St"}},
                ]
            }
        )
        assert suggestions == [
            AddressSuggestion(formatted_address="1 Real St", provider_place_id="ok")
        ]

    def test_empty_result_items_maps_to_empty(self) -> None:
        adapter, _client = _adapter_returning({"ResultItems": []})
        assert adapter.suggestions("nothing") == []


class TestGracefulDegradation:
    def test_blank_query_returns_empty_without_calling_provider(self) -> None:
        adapter, client = _adapter_returning(RESULT_ITEMS_RESPONSE)

        assert adapter.suggestions("   ") == []
        assert client.calls == []

    def test_none_query_returns_empty_without_calling_provider(self) -> None:
        adapter, client = _adapter_returning(RESULT_ITEMS_RESPONSE)
        assert adapter.suggestions(None) == []  # type: ignore[arg-type]
        assert client.calls == []

    def test_client_error_degrades_to_empty(self) -> None:
        client = _StubClient(error=RuntimeError("ThrottlingException"))
        adapter = AutocompleteAdapter(client=client)
        assert adapter.suggestions("123 Main") == []

    def test_access_denied_degrades_to_empty(self) -> None:
        client = _StubClient(error=RuntimeError("AccessDeniedException"))
        adapter = AutocompleteAdapter(client=client)
        assert adapter.suggestions("123 Main") == []

    def test_unexpected_response_shape_degrades_to_empty(self) -> None:
        adapter, _client = _adapter_returning({"foo": "bar"})
        assert adapter.suggestions("123 Main") == []

    def test_result_items_not_a_list_degrades_to_empty(self) -> None:
        assert map_response_to_suggestions({"ResultItems": {"unexpected": "shape"}}) == []

    def test_non_dict_response_degrades_to_empty(self) -> None:
        assert map_response_to_suggestions(["not", "a", "dict"]) == []


# --- Secondary (unit) addresses (Requirement 3.1) ---------------------------
#
# Autocomplete only returns the base building; the individual units come from a
# second Geocode call with AdditionalFeatures=["SecondaryAddresses"]. The base
# ResultItems[0] carries a top-level SecondaryAddresses array. This is the shape
# verified live against `aws geo-places geocode ... --additional-features
# SecondaryAddresses`.

SECONDARY_ADDRESSES_RESPONSE = {
    "ResultItems": [
        {
            "PlaceId": "base-place",
            "PlaceType": "PointAddress",
            "Title": "123 Main St, Springfield, IL 62704, United States",
            "Address": {"Label": "123 Main St, Springfield, IL 62704, United States"},
            "Position": [-76.8, 39.1],
            "SecondaryAddresses": [
                {
                    "PlaceId": "unit-101",
                    "PlaceType": "SecondaryAddress",
                    "Title": "123 Main St Unit 101, Springfield, IL 62704-1997, United States",
                    "Address": {
                        "Label": "123 Main St Unit 101, Springfield, IL 62704-1997, United States",
                        "SecondaryAddressComponents": [{"Number": "101"}],
                    },
                    "Position": [-76.8, 39.1],
                },
                {
                    "PlaceId": "unit-102",
                    "PlaceType": "SecondaryAddress",
                    "Title": "123 Main St Unit 102, Springfield, IL 62704-1997, United States",
                    "Address": {
                        "Label": "123 Main St Unit 102, Springfield, IL 62704-1997, United States",
                        "SecondaryAddressComponents": [{"Number": "102"}],
                    },
                    "Position": [-76.8, 39.1],
                },
            ],
        }
    ]
}


class TestSecondaryAddressMapping:
    def test_maps_secondary_addresses_to_suggestions(self) -> None:
        adapter, _client = _adapter_returning(SECONDARY_ADDRESSES_RESPONSE)

        result = adapter.secondary_addresses(
            "123 Main St, Springfield, IL 62704"
        )

        assert result == [
            AddressSuggestion(
                formatted_address="123 Main St Unit 101, Springfield, IL 62704-1997, United States",
                provider_place_id="unit-101",
            ),
            AddressSuggestion(
                formatted_address="123 Main St Unit 102, Springfield, IL 62704-1997, United States",
                provider_place_id="unit-102",
            ),
        ]

    def test_sends_geocode_with_secondary_addresses_feature(self) -> None:
        adapter, client = _adapter_returning(SECONDARY_ADDRESSES_RESPONSE)

        adapter.secondary_addresses("123 Main St, Springfield, IL 62704")

        call = client.geocode_calls[0]
        assert call["QueryText"] == "123 Main St, Springfield, IL 62704"
        assert call["AdditionalFeatures"] == ["SecondaryAddresses"]
        assert call["IntendedUse"] == "SingleUse"
        assert call["MaxResults"] > 0

    def test_entry_falls_back_to_title_when_no_label(self) -> None:
        suggestions = map_secondary_addresses(
            {
                "ResultItems": [
                    {
                        "SecondaryAddresses": [
                            {"PlaceId": "u1", "Title": "Unit Title Fallback"}
                        ]
                    }
                ]
            }
        )
        assert suggestions == [
            AddressSuggestion(
                formatted_address="Unit Title Fallback", provider_place_id="u1"
            )
        ]

    def test_entry_without_place_id_maps_to_none(self) -> None:
        suggestions = map_secondary_addresses(
            {
                "ResultItems": [
                    {"SecondaryAddresses": [{"Address": {"Label": "5 A St Unit 2"}}]}
                ]
            }
        )
        assert suggestions == [
            AddressSuggestion(formatted_address="5 A St Unit 2", provider_place_id=None)
        ]

    def test_entries_without_any_address_string_are_skipped(self) -> None:
        suggestions = map_secondary_addresses(
            {
                "ResultItems": [
                    {
                        "SecondaryAddresses": [
                            {"PlaceId": "no-text"},
                            {"PlaceId": "blank", "Address": {"Label": "  "}},
                            {"PlaceId": "ok", "Address": {"Label": "1 Real St Unit 9"}},
                        ]
                    }
                ]
            }
        )
        assert suggestions == [
            AddressSuggestion(
                formatted_address="1 Real St Unit 9", provider_place_id="ok"
            )
        ]


class TestSecondaryAddressGracefulDegradation:
    def test_blank_address_returns_empty_without_calling_provider(self) -> None:
        adapter, client = _adapter_returning(SECONDARY_ADDRESSES_RESPONSE)

        assert adapter.secondary_addresses("   ") == []
        assert client.geocode_calls == []

    def test_none_address_returns_empty_without_calling_provider(self) -> None:
        adapter, client = _adapter_returning(SECONDARY_ADDRESSES_RESPONSE)
        assert adapter.secondary_addresses(None) == []  # type: ignore[arg-type]
        assert client.geocode_calls == []

    def test_client_error_degrades_to_empty(self) -> None:
        client = _StubClient(error=RuntimeError("ValidationException"))
        adapter = AutocompleteAdapter(client=client)
        assert adapter.secondary_addresses("123 Main St") == []

    def test_no_secondary_addresses_array_maps_to_empty(self) -> None:
        adapter, _client = _adapter_returning(
            {"ResultItems": [{"PlaceId": "base", "Address": {"Label": "1 A St"}}]}
        )
        assert adapter.secondary_addresses("1 A St") == []

    def test_empty_result_items_maps_to_empty(self) -> None:
        assert map_secondary_addresses({"ResultItems": []}) == []

    def test_secondary_addresses_not_a_list_maps_to_empty(self) -> None:
        assert (
            map_secondary_addresses(
                {"ResultItems": [{"SecondaryAddresses": {"unexpected": "shape"}}]}
            )
            == []
        )

    def test_unexpected_response_shape_degrades_to_empty(self) -> None:
        adapter, _client = _adapter_returning({"foo": "bar"})
        assert adapter.secondary_addresses("1 A St") == []

    def test_non_dict_response_degrades_to_empty(self) -> None:
        assert map_secondary_addresses(["not", "a", "dict"]) == []
