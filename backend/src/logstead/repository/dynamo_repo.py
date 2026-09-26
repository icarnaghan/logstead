"""DynamoDB single-table repository (Requirements 12.2, 12.3, 13.1, 13.3).

This module is the only place that talks to DynamoDB. It encapsulates the
low-level access primitives — ``put_item``, ``get_item``, ``query`` (base table
or a GSI, optionally with a ``begins_with`` sort-key condition), ``delete_item``,
and a ``transact_write`` wrapper over ``TransactWriteItems`` for atomic
multi-item writes. Services build keys via :mod:`logstead.repository.keys` and
hand plain item dicts to this repository; the repository never encodes business
rules or the key scheme itself.

Money handling (Requirement 13.3)
---------------------------------
Money is ``decimal.Decimal`` in application code and is persisted as a fixed
two-decimal **string** in DynamoDB — never a DynamoDB ``Number`` (``N``), which
can drift for financial precision. The repository is the serialization boundary
that enforces this:

* **On write**, any attribute whose name is a *money attribute* is rendered with
  :func:`logstead.util.money.money_to_str` and stored as a string (``S``).
* **On read**, those same attributes are parsed back to ``Decimal`` with
  :func:`logstead.util.money.to_money`.

Which attributes are money is declared explicitly. Each operation accepts a
``money_attrs`` argument (a set of top-level attribute names). When omitted it
defaults to :data:`DEFAULT_MONEY_ATTRS`, the union of money attribute names used
by the Logstead item types (``amount``, ``costBasis``, ``remainingBasis``). This
keeps the money contract explicit and auditable rather than relying on value
sniffing, and lets a caller narrow or extend the set per call.

Sparse items (Requirements 12.2, 12.3)
--------------------------------------
Absent optional attributes are **omitted** from the write, never written as
``NULL``. A value of ``None`` in the item dict is dropped, so a stored item
carries only the attributes that were actually present. Reading the item back
therefore yields exactly the present attributes; any attribute not returned is
"unset" from the caller's point of view. This gives round-trip preservation for
the sparse, provider-driven ``PropertyDetails`` field set without a rigid schema.

boto3 usage
-----------
The repository uses the boto3 **client** API together with ``TypeSerializer`` /
``TypeDeserializer`` so attribute typing is explicit — this is what lets money
attributes be forced to ``S`` and lets us drop absent attributes deterministically.
The client and table name are injected, so tests can point the repository at a
moto-backed or DynamoDB-Local endpoint.
"""

from __future__ import annotations

from decimal import Decimal
from typing import Any, Iterable, Mapping, Sequence

from boto3.dynamodb.types import TypeDeserializer, TypeSerializer

from logstead.util.money import money_to_str, to_money

__all__ = ["DEFAULT_MONEY_ATTRS", "DynamoRepository"]

#: Top-level attribute names stored as two-decimal money strings across the
#: Logstead item types (Transaction.amount, DepreciableAsset.costBasis,
#: DepreciationScheduleRow.amount/remainingBasis, DraftTransaction.amount).
DEFAULT_MONEY_ATTRS: frozenset[str] = frozenset(
    {"amount", "costBasis", "remainingBasis"}
)

_SERIALIZER = TypeSerializer()
_DESERIALIZER = TypeDeserializer()


def _prepare_item(
    item: Mapping[str, Any], money_attrs: Iterable[str]
) -> dict[str, dict[str, Any]]:
    """Serialize a plain item dict into DynamoDB wire form.

    Applies the two sparse/money rules:

    * Attributes whose value is ``None`` are omitted (sparse write; 12.2).
    * Attributes named in ``money_attrs`` are rendered as fixed two-decimal
      strings and stored as ``S`` (13.3).

    Other attributes are serialized by boto3's ``TypeSerializer``.
    """
    money = set(money_attrs)
    prepared: dict[str, dict[str, Any]] = {}
    for name, value in item.items():
        if value is None:
            # Absent optional attribute — omit entirely so the item stays sparse.
            continue
        if name in money:
            # Force money to a two-decimal string attribute, never a Number.
            prepared[name] = {"S": money_to_str(value)}
        else:
            prepared[name] = _SERIALIZER.serialize(value)
    return prepared


def _parse_item(
    raw: Mapping[str, Mapping[str, Any]] | None, money_attrs: Iterable[str]
) -> dict[str, Any] | None:
    """Deserialize a DynamoDB wire item back into a plain dict.

    Money attributes are parsed back to ``Decimal`` (13.3). Attributes absent
    from the stored item are simply absent from the result (reported as unset;
    12.3).
    """
    if raw is None:
        return None
    money = set(money_attrs)
    result: dict[str, Any] = {}
    for name, wire in raw.items():
        if name in money:
            # Stored as a string; parse straight back to a two-decimal Decimal.
            result[name] = to_money(wire["S"])
        else:
            result[name] = _deserialize(wire)
    return result


def _deserialize(wire: Mapping[str, Any]) -> Any:
    """Deserialize one attribute, mapping any stray ``N`` values to ``Decimal``.

    boto3's ``TypeDeserializer`` already returns ``Decimal`` for ``N`` values;
    this wrapper exists so all numeric handling flows through one place.
    """
    return _DESERIALIZER.deserialize(dict(wire))


class DynamoRepository:
    """Thin single-table access layer over a boto3 DynamoDB client.

    Args:
        client: A boto3 DynamoDB **client** (``boto3.client("dynamodb", ...)``).
        table_name: The single Logstead table name.
        money_attrs: Default set of money attribute names applied when a
            per-call ``money_attrs`` is not supplied. Defaults to
            :data:`DEFAULT_MONEY_ATTRS`.
    """

    def __init__(
        self,
        client: Any,
        table_name: str,
        money_attrs: Iterable[str] = DEFAULT_MONEY_ATTRS,
    ) -> None:
        self._client = client
        self._table_name = table_name
        self._money_attrs = frozenset(money_attrs)

    # --- Writes --------------------------------------------------------------

    def put_item(
        self,
        item: Mapping[str, Any],
        *,
        money_attrs: Iterable[str] | None = None,
    ) -> None:
        """Write a single item (sparse; money as strings).

        ``None`` values are dropped so the stored item is sparse (12.2), and
        money attributes are stored as two-decimal strings (13.3).
        """
        attrs = self._money_attrs if money_attrs is None else set(money_attrs)
        self._client.put_item(
            TableName=self._table_name,
            Item=_prepare_item(item, attrs),
        )

    def delete_item(
        self, pk: str, sk: str, *, pk_name: str = "PK", sk_name: str = "SK"
    ) -> None:
        """Delete a single item by its primary key."""
        self._client.delete_item(
            TableName=self._table_name,
            Key={pk_name: {"S": pk}, sk_name: {"S": sk}},
        )

    def transact_write(
        self,
        items: Sequence[Mapping[str, Any]],
        *,
        money_attrs: Iterable[str] | None = None,
    ) -> None:
        """Atomically apply a batch of writes via ``TransactWriteItems`` (13.1).

        Each element of ``items`` describes one action and is one of:

        * ``{"put": <item dict>}`` — insert/replace an item. The item dict is
          sparse-/money-serialized exactly like :meth:`put_item`.
        * ``{"delete": {"pk": ..., "sk": ..., "pk_name"?: ..., "sk_name"?: ...}}``
          — delete by primary key.

        All actions succeed or fail together, so multi-item writes (e.g. a
        property's ``USER#`` row plus its mirrored ``PROPERTY#..META`` row, or an
        asset plus its cascade of schedule rows) stay consistent.
        """
        attrs = self._money_attrs if money_attrs is None else set(money_attrs)
        transact_items: list[dict[str, Any]] = []
        for entry in items:
            if "put" in entry:
                transact_items.append(
                    {
                        "Put": {
                            "TableName": self._table_name,
                            "Item": _prepare_item(entry["put"], attrs),
                        }
                    }
                )
            elif "delete" in entry:
                spec = entry["delete"]
                pk_name = spec.get("pk_name", "PK")
                sk_name = spec.get("sk_name", "SK")
                transact_items.append(
                    {
                        "Delete": {
                            "TableName": self._table_name,
                            "Key": {
                                pk_name: {"S": spec["pk"]},
                                sk_name: {"S": spec["sk"]},
                            },
                        }
                    }
                )
            else:
                raise ValueError(
                    f"transact_write entry must have a 'put' or 'delete' key, "
                    f"got keys {sorted(entry.keys())}"
                )
        if not transact_items:
            return
        self._client.transact_write_items(TransactItems=transact_items)

    # --- Reads ---------------------------------------------------------------

    def get_item(
        self,
        pk: str,
        sk: str,
        *,
        pk_name: str = "PK",
        sk_name: str = "SK",
        money_attrs: Iterable[str] | None = None,
    ) -> dict[str, Any] | None:
        """Fetch a single item by primary key, or ``None`` if it is absent.

        Money attributes are parsed back to ``Decimal`` and attributes not
        stored are absent from the result (reported as unset; 12.3).
        """
        attrs = self._money_attrs if money_attrs is None else set(money_attrs)
        resp = self._client.get_item(
            TableName=self._table_name,
            Key={pk_name: {"S": pk}, sk_name: {"S": sk}},
        )
        return _parse_item(resp.get("Item"), attrs)

    def query(
        self,
        pk: str,
        *,
        sk_begins_with: str | None = None,
        index_name: str | None = None,
        pk_name: str | None = None,
        sk_name: str | None = None,
        ascending: bool = True,
        money_attrs: Iterable[str] | None = None,
    ) -> list[dict[str, Any]]:
        """Query a partition on the base table or a GSI.

        Args:
            pk: The partition-key value to match.
            sk_begins_with: If given, restrict to items whose sort key begins
                with this prefix (``begins_with``). Used for listing a user's
                properties, a property's transactions, an asset's schedule rows,
                etc.
            index_name: ``"GSI1"`` or ``"GSI2"`` to query a secondary index;
                ``None`` (default) queries the base table.
            pk_name / sk_name: Override the key attribute names. Defaults are
                chosen from ``index_name`` (``PK``/``SK`` for the base table,
                ``GSI1PK``/``GSI1SK`` or ``GSI2PK``/``GSI2SK`` for indexes).
            ascending: DynamoDB's ``ScanIndexForward``. The Logstead sort keys
                use inverted dates, so the default ascending scan already yields
                newest-first; callers rarely need to change this.
            money_attrs: Override the money-attribute set for parsing results.

        Returns:
            All matching items (paginated internally), money parsed to
            ``Decimal``, in DynamoDB sort-key order.
        """
        attrs = self._money_attrs if money_attrs is None else set(money_attrs)
        resolved_pk_name, resolved_sk_name = self._key_names(
            index_name, pk_name, sk_name
        )

        expr_names = {"#pk": resolved_pk_name}
        expr_values: dict[str, dict[str, Any]] = {":pk": {"S": pk}}
        condition = "#pk = :pk"
        if sk_begins_with is not None:
            expr_names["#sk"] = resolved_sk_name
            expr_values[":skprefix"] = {"S": sk_begins_with}
            condition += " AND begins_with(#sk, :skprefix)"

        kwargs: dict[str, Any] = {
            "TableName": self._table_name,
            "KeyConditionExpression": condition,
            "ExpressionAttributeNames": expr_names,
            "ExpressionAttributeValues": expr_values,
            "ScanIndexForward": ascending,
        }
        if index_name is not None:
            kwargs["IndexName"] = index_name

        items: list[dict[str, Any]] = []
        last_key: Mapping[str, Any] | None = None
        while True:
            if last_key is not None:
                kwargs["ExclusiveStartKey"] = last_key
            resp = self._client.query(**kwargs)
            for raw in resp.get("Items", []):
                parsed = _parse_item(raw, attrs)
                if parsed is not None:
                    items.append(parsed)
            last_key = resp.get("LastEvaluatedKey")
            if not last_key:
                break
        return items

    # --- Helpers -------------------------------------------------------------

    @staticmethod
    def _key_names(
        index_name: str | None, pk_name: str | None, sk_name: str | None
    ) -> tuple[str, str]:
        """Resolve the (pk, sk) attribute names for a base-table or GSI query."""
        if pk_name is not None and sk_name is not None:
            return pk_name, sk_name
        if index_name is None:
            default_pk, default_sk = "PK", "SK"
        else:
            default_pk, default_sk = f"{index_name}PK", f"{index_name}SK"
        return pk_name or default_pk, sk_name or default_sk
