"""Property-based tests for ``ItemizedExpenseService`` over moto.

Design Properties 6 to 9 (Requirements 2.8, 5.7, 5.8, 8.2, 8.4, 8.5, 8.6, 9.5,
9.6, 15.4). The real ``TransactionService`` and ``ItemizedExpenseService`` run
over moto-backed DynamoDB and S3.
"""

from __future__ import annotations

from dataclasses import asdict
from decimal import Decimal

import boto3
from hypothesis import given, settings
from hypothesis import strategies as st
from moto import mock_aws

from logstead.models.transaction import TransactionInput
from logstead.services.itemized import EntryInput, ItemizedExpenseService

from tests.services.test_imported_marker_update_property import (
    BUCKET,
    REGION,
    TAX_YEAR,
    _amounts,
    _Env,
)

CATEGORY = "repairs"

_text = st.text(alphabet="abc xyz", min_size=1, max_size=20).filter(
    lambda s: s.strip()
)
_months = st.integers(min_value=1, max_value=12)
_days = st.integers(min_value=1, max_value=28)
_amount = _amounts.map(Decimal)

_entry = st.tuples(_amount, _months, _days, _text, st.booleans())
_entries = st.lists(_entry, min_size=0, max_size=4)
_total = st.tuples(_amount, st.booleans(), st.booleans(), st.one_of(st.none(), _text))
# (amount, imported, has_receipt, description)


class _World:
    """Services, a fixture property, and snapshot helpers."""

    def __init__(self) -> None:
        self.env = _Env()
        self.txns = self.env.txns
        self.pid = self.env.property_id
        self.svc = ItemizedExpenseService(self.txns)
        self.s3 = boto3.client("s3", region_name=REGION)

    def receipt(self, txn_id: str) -> None:
        upload = self.txns.attach_receipt(
            self.pid, txn_id, "receipt.pdf", "application/pdf"
        )
        assert upload.is_ok, upload.error
        self.s3.put_object(
            Bucket=BUCKET, Key=upload.value.document.s3_key, Body=b"%PDF-1.4"
        )

    def add_entry(self, spec, year: int = TAX_YEAR):
        amount, month, day, description, with_receipt = spec
        created = self.svc.create_entry(
            self.pid,
            CATEGORY,
            EntryInput(
                date=f"{year}-{month:02d}-{day:02d}",
                amount=amount,
                description=description,
                tax_year=year,
            ),
        )
        assert created.is_ok, created.error
        if with_receipt:
            self.receipt(created.value.id)
        return created.value

    def add_total_row(self, spec, year: int = TAX_YEAR):
        amount, imported, with_receipt, description = spec
        created = self.txns.create(
            TransactionInput(
                property_id=self.pid,
                date=f"{year}-12-31",
                amount=amount,
                type="expense",
                category_id=CATEGORY,
                description=description,
                imported=imported,
            )
        )
        assert created.is_ok, created.error
        if with_receipt:
            self.receipt(created.value.id)
        return created.value

    def snapshot(self, year: int = TAX_YEAR, *, itemized: bool | None = None):
        """id -> (fields, receipt ids) of the year's repairs rows."""
        listed = self.txns.list_for_property(self.pid, year)
        assert listed.is_ok
        state = {}
        for row in listed.value:
            if row.category_id != CATEGORY:
                continue
            if itemized is not None and row.itemized != itemized:
                continue
            receipts = self.txns.list_receipts(self.pid, row.id)
            assert receipts.is_ok
            state[row.id] = (
                asdict(row),
                sorted(r.document.id for r in receipts.value),
            )
        return state

    def summary(self, year: int = TAX_YEAR):
        result = self.svc.summary(self.pid, CATEGORY, year)
        assert result.is_ok, result.error
        return result.value


# Feature: itemized-expenses, Property 6: Entry operations and total operations are independent
@settings(deadline=None, max_examples=100)
@given(
    entries=st.lists(_entry, min_size=1, max_size=4),
    total=st.one_of(st.none(), _total),
    edit=_entry,
    new_entry=_entry,
    total_amount=_amount,
    total_amount2=_amount,
)
def test_entry_and_total_operations_are_independent(
    entries, total, edit, new_entry, total_amount, total_amount2
) -> None:
    """**Validates: Requirements 2.8, 5.7, 5.8**"""
    with mock_aws():
        w = _World()
        created = [w.add_entry(e) for e in entries]
        if total is not None:
            w.add_total_row(total)

        # Entry operations leave every unmarked row (and its receipts) alone.
        totals_before = w.snapshot(itemized=False)
        target = created[0]
        before_target = w.snapshot(itemized=True)[target.id]

        amount, month, day, description, _ = edit
        edited = w.svc.update_entry(
            w.pid,
            CATEGORY,
            target.id,
            EntryInput(
                date=f"{TAX_YEAR}-{month:02d}-{day:02d}",
                amount=amount,
                description=description,
                notes="n",
                tax_year=TAX_YEAR,
            ),
        )
        assert edited.is_ok, edited.error
        assert edited.value.id == target.id
        assert edited.value.itemized is True
        after_target = w.snapshot(itemized=True)[target.id]
        assert after_target[1] == before_target[1]  # receipts kept
        assert w.snapshot(itemized=False) == totals_before

        added = w.add_entry(new_entry)
        assert w.snapshot(itemized=False) == totals_before

        deleted = w.svc.delete_entry(w.pid, CATEGORY, added.id)
        assert deleted.is_ok, deleted.error
        assert w.snapshot(itemized=False) == totals_before

        # Total operations leave every itemized entry (and receipts) alone.
        entries_before = w.snapshot(itemized=True)
        for op in ("set", "edit", "remove"):
            if op == "remove":
                result = w.svc.remove_total(w.pid, CATEGORY, TAX_YEAR)
            else:
                value = total_amount if op == "set" else total_amount2
                result = w.svc.set_total(w.pid, CATEGORY, TAX_YEAR, value)
            assert result.is_ok, result.error
            assert w.snapshot(itemized=True) == entries_before


# Feature: itemized-expenses, Property 7: Total operations behave as specified
@settings(deadline=None, max_examples=100)
@given(
    year=st.integers(min_value=2015, max_value=2030),
    amount=_amount,
    new_amount=_amount,
    entries=_entries,
    total=_total,
)
def test_total_operations_behave_as_specified(
    year, amount, new_amount, entries, total
) -> None:
    """**Validates: Requirements 8.2, 8.4, 8.5**"""
    with mock_aws():
        w = _World()
        for e in entries:
            w.add_entry(e, year)

        # Set when absent: exactly one unmarked row with the specified shape.
        result = w.svc.set_total(w.pid, CATEGORY, year, amount)
        assert result.is_ok, result.error
        rows = result.value.entered_total_rows
        assert len(rows) == 1
        row = rows[0]
        assert row.date == f"{year}-12-31"
        assert row.type == "expense"
        assert row.category_id == CATEGORY
        assert row.imported is False
        assert row.itemized is False
        assert row.amount == amount
        assert result.value.entered_total == amount

        # Remove returns to absent, with source itemized or none.
        removed = w.svc.remove_total(w.pid, CATEGORY, year)
        assert removed.is_ok, removed.error
        assert removed.value.entered_total is None
        assert removed.value.entered_total_rows == []
        assert removed.value.line_source == ("itemized" if entries else "none")

        # Edit a single arbitrary total row: only amount (and updated_at) change.
        existing = w.add_total_row(total, year)
        before = w.snapshot(year)[existing.id]
        edited = w.svc.set_total(w.pid, CATEGORY, year, new_amount)
        assert edited.is_ok, edited.error
        after = w.snapshot(year)[existing.id]
        assert after[1] == before[1]  # receipts
        fields_before, fields_after = dict(before[0]), dict(after[0])
        assert fields_after.pop("amount") == new_amount
        fields_before.pop("amount")
        fields_before.pop("updated_at")
        fields_after.pop("updated_at")
        assert fields_after == fields_before
        assert len(w.snapshot(year, itemized=False)) == 1

        # Removing the edited total returns to absent again.
        gone = w.svc.remove_total(w.pid, CATEGORY, year)
        assert gone.is_ok, gone.error
        assert gone.value.entered_total is None
        assert gone.value.line_source == ("itemized" if entries else "none")


# Feature: itemized-expenses, Property 8: Sync sets the total to the itemized sum and Undo restores it
@settings(deadline=None, max_examples=100)
@given(
    entries=st.lists(_entry, min_size=1, max_size=4),
    total=_total,
)
def test_sync_sets_total_to_itemized_sum_and_undo_restores(entries, total) -> None:
    """**Validates: Requirements 9.5, 9.6, 15.4**"""
    with mock_aws():
        w = _World()
        for e in entries:
            w.add_entry(e)
        total_row = w.add_total_row(total)
        summary = w.summary()
        itemized_sum = summary.itemized_sum
        previous = summary.entered_total
        if previous == itemized_sum:
            # Precondition: the total differs from the itemized sum.
            total_row_amount = previous + Decimal("1.00")
            fixed = w.svc.set_total(w.pid, CATEGORY, TAX_YEAR, total_row_amount)
            assert fixed.is_ok, fixed.error
            previous = total_row_amount
        before = w.snapshot(itemized=False)[total_row.id]

        synced = w.svc.set_total(w.pid, CATEGORY, TAX_YEAR, itemized_sum)
        assert synced.is_ok, synced.error
        s = synced.value
        assert [r.id for r in s.entered_total_rows] == [total_row.id]
        assert s.entered_total == itemized_sum
        assert s.remainder == Decimal("0.00")
        assert s.line_total == itemized_sum
        assert s.line_source == "entered_total"
        assert w.snapshot(itemized=False)[total_row.id][1] == before[1]

        undone = w.svc.set_total(w.pid, CATEGORY, TAX_YEAR, previous)
        assert undone.is_ok, undone.error
        u = undone.value
        assert [r.id for r in u.entered_total_rows] == [total_row.id]
        assert u.entered_total == previous
        assert u.line_total == previous
        after = w.snapshot(itemized=False)[total_row.id]
        assert after[1] == before[1]
        restored = dict(after[0])
        restored.pop("updated_at")
        original = dict(before[0])
        original.pop("updated_at")
        assert restored == original


# Feature: itemized-expenses, Property 9: Several total rows block total operations
@settings(deadline=None, max_examples=100)
@given(
    totals=st.lists(_total, min_size=2, max_size=4),
    entries=_entries,
    amount=_amount,
)
def test_several_total_rows_block_total_operations(totals, entries, amount) -> None:
    """**Validates: Requirements 8.6**"""
    with mock_aws():
        w = _World()
        for e in entries:
            w.add_entry(e)
        for t in totals:
            w.add_total_row(t)
        before = w.snapshot()
        assert len(w.snapshot(itemized=False)) == len(totals)
        itemized_sum = w.summary().itemized_sum

        # set / edit and sync all go through set_total; remove has its own path.
        for result in (
            w.svc.set_total(w.pid, CATEGORY, TAX_YEAR, amount),
            w.svc.set_total(w.pid, CATEGORY, TAX_YEAR, itemized_sum),
            w.svc.remove_total(w.pid, CATEGORY, TAX_YEAR),
        ):
            assert not result.is_ok
            assert result.error.kind == "conflict"
            assert w.snapshot() == before
