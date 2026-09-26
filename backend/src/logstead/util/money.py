"""Money / decimal utilities (Requirement 13.3).

Money is represented as ``decimal.Decimal`` in application code and persisted
as fixed two-decimal **strings** in DynamoDB (never floating point, never a
DynamoDB ``Number``, both of which can drift for financial precision).

This module is the single boundary that:

* coerces raw input (``str`` or ``Decimal``) into a two-decimal ``Decimal``
  (:func:`to_money`), and
* renders a ``Decimal`` into the exact two-decimal string stored in DynamoDB
  (:func:`money_to_str`).

The round-trip ``to_money(money_to_str(x)) == x`` holds with no drift for any
value produced by :func:`to_money` (design Property 28).
"""

from __future__ import annotations

from decimal import (
    ROUND_HALF_UP,
    Decimal,
    DecimalException,
    InvalidOperation,
)
from typing import Final, TypeAlias, Union

__all__ = ["Money", "TWO_PLACES", "to_money", "money_to_str"]

#: Type alias for a monetary value. Semantically a ``decimal.Decimal``
#: constrained to exactly two decimal places (see :func:`to_money`).
Money: TypeAlias = Decimal

#: The quantization exponent used for all monetary values: two decimal places.
TWO_PLACES: Final[Decimal] = Decimal("0.01")

#: Inputs accepted at the money boundary.
MoneyInput: TypeAlias = Union[str, Decimal]


def to_money(value: MoneyInput) -> Money:
    """Coerce ``value`` into a ``Decimal`` quantized to two decimal places.

    Accepts a ``str`` (e.g. ``"1234.5"``, ``"1234.567"``) or a ``Decimal``.
    The result is always rounded half-up to exactly two decimal places, so it
    is safe to persist via :func:`money_to_str`.

    ``float`` is intentionally rejected: floats cannot represent most decimal
    fractions exactly and admitting them would reintroduce the drift this
    module exists to prevent. Callers holding a float must convert it to a
    ``str`` themselves and accept the precision they pass in.

    Args:
        value: A ``str`` or ``Decimal`` monetary amount.

    Returns:
        The amount as a two-decimal ``Decimal``.

    Raises:
        TypeError: If ``value`` is not a ``str`` or ``Decimal`` (e.g. a
            ``float``, ``int``, or ``None``).
        ValueError: If ``value`` is not a finite number (NaN or Infinity) or
            cannot be parsed as a decimal.
    """
    if isinstance(value, bool) or not isinstance(value, (str, Decimal)):
        raise TypeError(
            f"money must be a str or Decimal, got {type(value).__name__}"
        )

    if isinstance(value, str):
        text = value.strip()
        if not text:
            raise ValueError("money string is empty")
        try:
            dec = Decimal(text)
        except (InvalidOperation, ValueError) as exc:
            raise ValueError(f"invalid money string: {value!r}") from exc
    else:
        dec = value

    if not dec.is_finite():
        raise ValueError(f"money must be a finite amount, got {value!r}")

    try:
        return dec.quantize(TWO_PLACES, rounding=ROUND_HALF_UP)
    except (InvalidOperation, DecimalException) as exc:
        raise ValueError(f"money amount cannot be quantized: {value!r}") from exc


def money_to_str(value: Money) -> str:
    """Render a monetary ``Decimal`` as a fixed two-decimal string.

    Produces the exact string stored in DynamoDB (e.g. ``"0.00"``, ``"0.01"``,
    ``"1234.56"``). The value is quantized via :func:`to_money` first, so this
    function is total over any input :func:`to_money` accepts and never emits
    scientific notation.

    Args:
        value: A ``Decimal`` (or two-decimal ``str``) monetary amount.

    Returns:
        A fixed two-decimal string suitable for DynamoDB storage.

    Raises:
        TypeError: If ``value`` is not a ``str`` or ``Decimal``.
        ValueError: If ``value`` is non-finite or cannot be parsed.
    """
    return f"{to_money(value):.2f}"
