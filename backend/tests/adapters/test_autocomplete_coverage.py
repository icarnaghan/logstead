"""Broader adapter coverage for the address autocomplete adapter (task 7.5).

Requirement: 3.1.

The narrow branch tests live in ``test_autocomplete.py``. This module fills the
gaps task 7.5 calls out without duplicating them, adapted to the Amazon Location
Service (geo-places Autocomplete) backing:

* mapping ResultItems -> ``AddressSuggestion`` with additional shapes and order,
* end-to-end request through a stubbed client, and
* the remaining graceful-degradation shapes: a ``None`` query, a client raising,
  and a ``ResultItems`` value that is present but not a list.

Every failure mode must degrade to an empty suggestion list rather than raise
(Requirement 3.1); autocomplete is a convenience and never gates property
creation.
"""

from __future__ import annotations

from typing import Any

from logstead.adapters.autocomplete import (
    AutocompleteAdapter,
    map_response_to_suggestions,
)
from logstead.models.property import AddressSuggestion


class _StubClient:
    def __init__(self, response: Any = None, error: Exception | None = None) -> None:
        self._response = response
        self._error = error
        self.calls: list[dict[str, Any]] = []

    def autocomplete(self, **kwargs: Any) -> Any:
        self.calls.append(kwargs)
        if self._error is not None:
            raise self._error
        return self._response


def _item(label: str, place_id: str) -> dict[str, Any]:
    return {"PlaceId": place_id, "Address": {"Label": label}}


class TestMappingShapes:
    def test_preserves_result_order(self) -> None:
        response = {"ResultItems": [_item("A St", "a"), _item("B St", "b"), _item("C St", "c")]}
        suggestions = map_response_to_suggestions(response)
        assert [s.formatted_address for s in suggestions] == ["A St", "B St", "C St"]
        assert [s.provider_place_id for s in suggestions] == ["a", "b", "c"]

    def test_blank_place_id_maps_to_none(self) -> None:
        response = {"ResultItems": [{"PlaceId": "   ", "Address": {"Label": "1 Real St"}}]}
        assert map_response_to_suggestions(response) == [
            AddressSuggestion(formatted_address="1 Real St", provider_place_id=None)
        ]

    def test_non_dict_result_entries_are_skipped(self) -> None:
        response = {"ResultItems": ["not-a-dict", None, _item("1 Real St", "ok")]}
        assert map_response_to_suggestions(response) == [
            AddressSuggestion(formatted_address="1 Real St", provider_place_id="ok")
        ]

    def test_result_items_not_a_list_maps_to_empty(self) -> None:
        assert map_response_to_suggestions({"ResultItems": {"unexpected": "shape"}}) == []
        assert map_response_to_suggestions({"ResultItems": "OK"}) == []

    def test_full_request_maps_response_end_to_end(self) -> None:
        client = _StubClient(response={"ResultItems": [_item("10 Pine Rd, Boise, ID", "p")]})
        adapter = AutocompleteAdapter(client=client)
        assert adapter.suggestions("10 Pine") == [
            AddressSuggestion(formatted_address="10 Pine Rd, Boise, ID", provider_place_id="p")
        ]
        # MaxResults is bounded/positive on the outgoing request.
        assert client.calls[0]["MaxResults"] > 0


class TestGracefulDegradation:
    def test_client_error_degrades_to_empty(self) -> None:
        client = _StubClient(error=RuntimeError("boom"))
        adapter = AutocompleteAdapter(client=client)
        assert adapter.suggestions("123 Main") == []

    def test_none_query_returns_empty_without_calling_provider(self) -> None:
        client = _StubClient(response={"ResultItems": []})
        adapter = AutocompleteAdapter(client=client)
        assert adapter.suggestions(None) == []  # type: ignore[arg-type]
        assert client.calls == []

    def test_result_items_wrong_type_degrades_to_empty(self) -> None:
        client = _StubClient(response={"ResultItems": "OK"})
        adapter = AutocompleteAdapter(client=client)
        assert adapter.suggestions("123 Main") == []
