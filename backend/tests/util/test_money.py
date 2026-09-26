"""Unit tests for logstead.util.money (Requirement 13.3).

These are example/edge-case unit tests for the money boundary utilities. The
universal round-trip property (design Property 28) is covered separately by the
property-based test in task 1.2.
"""

from __future__ import annotations

from decimal import Decimal

import pytest

from logstead.util.money import Money, TWO_PLACES, money_to_str, to_money


class TestToMoney:
    def test_quantizes_decimal_to_two_places(self) -> None:
        assert to_money(Decimal("1234.5")) == Decimal("1234.50")

    def test_quantizes_string_to_two_places(self) -> None:
        assert to_money("1234.5") == Decimal("1234.50")

    def test_already_two_places_is_unchanged(self) -> None:
        assert to_money("1234.56") == Decimal("1234.56")

    def test_rounds_half_up(self) -> None:
        assert to_money("1.005") == Decimal("1.01")
        assert to_money("2.675") == Decimal("2.68")

    def test_rounds_extra_precision_down_when_below_half(self) -> None:
        assert to_money("1.004") == Decimal("1.00")

    def test_zero(self) -> None:
        assert to_money("0") == Decimal("0.00")

    def test_smallest_unit(self) -> None:
        assert to_money("0.01") == Decimal("0.01")

    def test_negative_amount_is_allowed(self) -> None:
        # Negative amounts are valid at this boundary (e.g. adjustments);
        # sign validity is a service-layer concern, not the coercion layer.
        assert to_money("-42.5") == Decimal("-42.50")

    def test_strips_surrounding_whitespace(self) -> None:
        assert to_money("  1234.56  ") == Decimal("1234.56")

    def test_large_amount(self) -> None:
        assert to_money("99999999.99") == Decimal("99999999.99")

    @pytest.mark.parametrize("bad", ["NaN", "Infinity", "-Infinity", "inf", "nan"])
    def test_rejects_non_finite_strings(self, bad: str) -> None:
        with pytest.raises(ValueError):
            to_money(bad)

    @pytest.mark.parametrize(
        "bad", [Decimal("NaN"), Decimal("Infinity"), Decimal("-Infinity")]
    )
    def test_rejects_non_finite_decimals(self, bad: Decimal) -> None:
        with pytest.raises(ValueError):
            to_money(bad)

    @pytest.mark.parametrize("bad", ["", "   ", "abc", "1.2.3", "$5.00", "1,234.56"])
    def test_rejects_unparseable_strings(self, bad: str) -> None:
        with pytest.raises(ValueError):
            to_money(bad)

    @pytest.mark.parametrize("bad", [1.5, 10, None, object(), True])
    def test_rejects_non_str_non_decimal_types(self, bad: object) -> None:
        with pytest.raises(TypeError):
            to_money(bad)  # type: ignore[arg-type]


class TestMoneyToStr:
    def test_fixed_two_decimals(self) -> None:
        assert money_to_str(Decimal("1234.5")) == "1234.50"

    def test_zero_renders_two_zeros(self) -> None:
        assert money_to_str(Decimal("0")) == "0.00"

    def test_smallest_unit(self) -> None:
        assert money_to_str(Decimal("0.01")) == "0.01"

    def test_never_uses_scientific_notation_for_large_values(self) -> None:
        assert money_to_str(Decimal("1E7")) == "10000000.00"

    def test_accepts_string_input(self) -> None:
        assert money_to_str("42") == "42.00"

    def test_rounds_half_up(self) -> None:
        assert money_to_str("1.005") == "1.01"

    def test_negative(self) -> None:
        assert money_to_str(Decimal("-3.1")) == "-3.10"


class TestModuleContract:
    def test_money_alias_is_decimal(self) -> None:
        assert Money is Decimal

    def test_two_places_constant(self) -> None:
        assert TWO_PLACES == Decimal("0.01")

    def test_round_trip_examples(self) -> None:
        for text in ["0.00", "0.01", "1234.56", "99999999.99", "-500.00"]:
            assert money_to_str(to_money(text)) == text
