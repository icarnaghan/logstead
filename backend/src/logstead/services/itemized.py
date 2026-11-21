"""Itemized expense configuration and the pure line-total resolver.

``ITEMIZED_CATEGORIES`` is the only place that names which categories support
itemized entries. :class:`LineAccumulator` implements the precedence rule:

* an entered total is *present* when at least one unmarked row exists, and then
  it is the line total (the itemized sum is never added to it);
* otherwise the itemized sum is the line total;
* otherwise the line total is ``0.00`` with source ``none``.
"""

from __future__ import annotations

from collections.abc import Iterable
from dataclasses import dataclass
from datetime import date
from decimal import Decimal
from typing import TYPE_CHECKING, Literal

from logstead.models.result import Result
from logstead.models.transaction import Transaction, TransactionInput
from logstead.services.category import CATEGORY_CATALOG
from logstead.util.money import Money, to_money

if TYPE_CHECKING:
    # Imported for typing only: transaction.py imports this module.
    from logstead.services.transaction import TransactionService

__all__ = [
    "CategoryRows",
    "EntryInput",
    "ItemizedExpenseService",
    "ItemizedSummary",
    "ITEMIZED_CATEGORIES",
    "ItemizedCategory",
    "LineAccumulator",
    "LineResolution",
    "LineSource",
    "is_itemized_category",
    "resolve_category_rows",
]


@dataclass(frozen=True)
class ItemizedCategory:
    """A Schedule E expense category enabled for itemized entries."""

    category_id: str


ITEMIZED_CATEGORIES: dict[str, ItemizedCategory] = {
    "repairs": ItemizedCategory("repairs"),
}


def is_itemized_category(category_id: str) -> bool:
    """Return True when ``category_id`` is enabled for itemized entries."""
    return category_id in ITEMIZED_CATEGORIES


LineSource = Literal["entered_total", "itemized", "none"]


@dataclass(frozen=True)
class LineResolution:
    """Result of applying the precedence rule to one line."""

    line_total: Money
    source: LineSource
    entered_total: Money | None
    entered_total_rows: int
    itemized_sum: Money
    itemized_count: int
    remainder: Money | None
    total_imported: bool


class LineAccumulator:
    """Accumulates one line's rows and resolves the precedence rule."""

    def __init__(self) -> None:
        self._entered = Decimal("0")
        self._entered_rows = 0
        self._itemized = Decimal("0")
        self._itemized_count = 0
        self._total_imported = False

    def add(self, amount: Money, *, itemized: bool, imported: bool = False) -> None:
        """Add one row. ``imported`` only matters for unmarked (total) rows."""
        if itemized:
            self._itemized += amount
            self._itemized_count += 1
        else:
            self._entered += amount
            self._entered_rows += 1
            if imported:
                self._total_imported = True

    def resolve(self) -> LineResolution:
        itemized_sum = to_money(self._itemized)
        if self._entered_rows > 0:
            entered = to_money(self._entered)
            return LineResolution(
                line_total=entered,
                source="entered_total",
                entered_total=entered,
                entered_total_rows=self._entered_rows,
                itemized_sum=itemized_sum,
                itemized_count=self._itemized_count,
                remainder=to_money(entered - itemized_sum),
                total_imported=self._total_imported,
            )
        if self._itemized_count > 0:
            source: LineSource = "itemized"
            total = itemized_sum
        else:
            source = "none"
            total = to_money(Decimal("0"))
        return LineResolution(
            line_total=total,
            source=source,
            entered_total=None,
            entered_total_rows=0,
            itemized_sum=itemized_sum,
            itemized_count=self._itemized_count,
            remainder=None,
            total_imported=False,
        )


# --- Service -----------------------------------------------------------------


@dataclass(frozen=True)
class EntryInput:
    """Fields of an itemized entry. ``tax_year``, when given, must match the
    year of ``date``."""

    date: str | None
    amount: Decimal | None
    description: str | None
    notes: str | None = None
    tax_year: int | None = None


@dataclass(frozen=True)
class ItemizedSummary:
    """One category's itemized view for one tax year."""

    category_id: str
    label: str
    schedule_e_line: int
    tax_year: int
    entered_total: Money | None
    entered_total_rows: list[Transaction]
    itemized_sum: Money
    itemized_count: int
    entries: list[Transaction]
    remainder: Money | None
    line_total: Money
    line_source: LineSource
    total_differs_from_itemized: bool


_CATALOG_BY_ID = {c.id: c for c in CATEGORY_CATALOG}


def _is_entry(txn: Transaction, category_id: str) -> bool:
    return (
        txn.itemized
        and txn.category_id == category_id
        and is_itemized_category(txn.category_id)
    )


@dataclass(frozen=True)
class CategoryRows:
    """One category's rows split into itemized entries and entered-total rows,
    with the resolved line."""

    resolution: LineResolution
    entries: tuple[Transaction, ...]
    total_rows: tuple[Transaction, ...]


def resolve_category_rows(
    transactions: Iterable[Transaction], category_id: str
) -> CategoryRows:
    """Filter ``transactions`` to ``category_id``, classify each row as an
    itemized entry or an entered-total row, and apply the precedence rule."""
    acc = LineAccumulator()
    entries: list[Transaction] = []
    totals: list[Transaction] = []
    for txn in transactions:
        if txn.category_id != category_id:
            continue
        is_entry = _is_entry(txn, category_id)
        acc.add(txn.amount, itemized=is_entry, imported=txn.imported)
        (entries if is_entry else totals).append(txn)
    return CategoryRows(
        resolution=acc.resolve(),
        entries=tuple(entries),
        total_rows=tuple(totals),
    )


class ItemizedExpenseService:
    """Itemized entries and the entered total for an enabled category."""

    def __init__(self, transactions: "TransactionService") -> None:
        self._txns = transactions

    # --- Reads ---------------------------------------------------------------

    def summary(
        self, property_id: str, category_id: str, tax_year: int
    ) -> Result[ItemizedSummary]:
        checked = self._check_category(category_id)
        if not checked.is_ok:
            return _fail(checked)
        category = checked.value
        listed = self._txns.list_for_property(property_id, tax_year)
        if not listed.is_ok:
            return _fail(listed)
        rows = resolve_category_rows(listed.value, category_id)
        res = rows.resolution
        entries = list(rows.entries)
        totals = list(rows.total_rows)
        differs = (
            res.entered_total is not None
            and res.itemized_count > 0
            and res.entered_total != res.itemized_sum
        )
        return Result.success(
            ItemizedSummary(
                category_id=category_id,
                label=category.label,
                schedule_e_line=category.schedule_e_line,
                tax_year=tax_year,
                entered_total=res.entered_total,
                entered_total_rows=totals,
                itemized_sum=res.itemized_sum,
                itemized_count=res.itemized_count,
                entries=entries,
                remainder=res.remainder,
                line_total=res.line_total,
                line_source=res.source,
                total_differs_from_itemized=differs,
            )
        )

    # --- Entries -------------------------------------------------------------

    def create_entry(
        self, property_id: str, category_id: str, data: EntryInput
    ) -> Result[Transaction]:
        checked = self._check_category(category_id)
        if not checked.is_ok:
            return _fail(checked)
        bad = _check_year(data)
        if bad is not None:
            return bad
        return self._txns.create(_entry_to_input(property_id, category_id, data))

    def update_entry(
        self, property_id: str, category_id: str, entry_id: str, data: EntryInput
    ) -> Result[Transaction]:
        checked = self._check_category(category_id)
        if not checked.is_ok:
            return _fail(checked)
        found = self._find_entry(property_id, category_id, entry_id)
        if not found.is_ok:
            return _fail(found)
        bad = _check_year(data)
        if bad is not None:
            return bad
        return self._txns.update(
            property_id,
            entry_id,
            _entry_to_input(property_id, category_id, data),
        )

    def delete_entry(
        self, property_id: str, category_id: str, entry_id: str
    ) -> Result[None]:
        checked = self._check_category(category_id)
        if not checked.is_ok:
            return _fail(checked)
        found = self._find_entry(property_id, category_id, entry_id)
        if not found.is_ok:
            return _fail(found)
        return self._txns.delete(property_id, entry_id)

    # --- Entered total -------------------------------------------------------

    def set_total(
        self,
        property_id: str,
        category_id: str,
        tax_year: int,
        amount: Decimal | None,
    ) -> Result[ItemizedSummary]:
        current = self._total_rows(property_id, category_id, tax_year)
        if not current.is_ok:
            return _fail(current)
        rows = current.value
        if len(rows) > 1:
            return _several_totals()
        if not rows:
            written = self._txns.create(
                TransactionInput(
                    property_id=property_id,
                    date=f"{tax_year:04d}-12-31",
                    amount=amount,
                    type="expense",
                    category_id=category_id,
                    imported=False,
                )
            )
        else:
            row = rows[0]
            written = self._txns.update(
                property_id,
                row.id,
                TransactionInput(
                    property_id=property_id,
                    date=row.date,
                    amount=amount,
                    type=row.type,
                    category_id=row.category_id,
                    description=row.description,
                    imported=row.imported,
                    itemized=False,
                ),
            )
        if not written.is_ok:
            return _fail(written)
        return self.summary(property_id, category_id, tax_year)

    def remove_total(
        self, property_id: str, category_id: str, tax_year: int
    ) -> Result[ItemizedSummary]:
        current = self._total_rows(property_id, category_id, tax_year)
        if not current.is_ok:
            return _fail(current)
        rows = current.value
        if not rows:
            return Result.failure(
                "not_found", "There is no entered total to remove.", field="total"
            )
        if len(rows) > 1:
            return _several_totals()
        deleted = self._txns.delete(property_id, rows[0].id)
        if not deleted.is_ok:
            return _fail(deleted)
        return self.summary(property_id, category_id, tax_year)

    # --- Internals -----------------------------------------------------------

    def _check_category(self, category_id: str):  # type: ignore[no-untyped-def]
        category = _CATALOG_BY_ID.get(category_id)
        if category is None:
            return Result.failure(
                "not_found",
                f"Unknown category: {category_id!r}.",
                field="category_id",
            )
        if not is_itemized_category(category_id):
            return Result.failure(
                "validation",
                "Itemized entries are not supported for this category.",
                field="category_id",
            )
        return Result.success(category)

    def _find_entry(
        self, property_id: str, category_id: str, entry_id: str
    ) -> Result[Transaction]:
        found = self._txns.get(property_id, entry_id)
        if not found.is_ok or not _is_entry(found.value, category_id):
            return Result.failure(
                "not_found", "Entry not found.", field="entry_id"
            )
        return found

    def _total_rows(
        self, property_id: str, category_id: str, tax_year: int
    ) -> Result[list[Transaction]]:
        checked = self._check_category(category_id)
        if not checked.is_ok:
            return _fail(checked)
        listed = self._txns.list_for_property(property_id, tax_year)
        if not listed.is_ok:
            return _fail(listed)
        return Result.success(
            [
                t
                for t in listed.value
                if t.category_id == category_id and not _is_entry(t, category_id)
            ]
        )


def _fail(result: Result) -> Result:  # type: ignore[type-arg]
    err = result.error
    assert err is not None
    return Result.failure(err.kind, err.message, err.field, err.errors)


def _several_totals() -> Result:  # type: ignore[type-arg]
    return Result.failure(
        "conflict",
        "There is more than one entered total row for this year. "
        "Manage them on the Transactions page.",
        field="total",
    )


def _check_year(data: EntryInput) -> Result | None:  # type: ignore[type-arg]
    if data.tax_year is None or not data.date:
        return None
    try:
        parsed = date.fromisoformat(data.date)
    except (ValueError, TypeError):
        return None  # TransactionService reports the invalid date
    if parsed.year != data.tax_year:
        return Result.failure(
            "validation",
            f"Date must fall in tax year {data.tax_year}.",
            field="date",
        )
    return None


def _entry_to_input(
    property_id: str, category_id: str, data: EntryInput
) -> TransactionInput:
    return TransactionInput(
        property_id=property_id,
        date=data.date,
        amount=data.amount,
        type="expense",
        category_id=category_id,
        description=data.description,
        imported=False,
        itemized=True,
        notes=data.notes,
    )
