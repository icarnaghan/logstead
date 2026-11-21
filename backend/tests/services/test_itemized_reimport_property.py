"""Schedule E re-import leaves itemized entries unchanged.

# Feature: itemized-expenses, Property 16: Schedule E re-import leaves itemized entries unchanged

Validates: Requirements 4.3, 4.4

For any set of itemized repairs entries (some with receipts) and any Schedule E
import for the same (property, tax year), the entries' ids, fields and receipts
are identical after each import, and only the imported total row is replaced.
Imported summary rows always carry ``itemized`` false.
"""

from __future__ import annotations

from dataclasses import asdict
from decimal import Decimal

import boto3
from hypothesis import given, settings
from hypothesis import strategies as st
from moto import mock_aws

from logstead.models.transaction import TransactionInput

from tests.services.test_imported_marker_update_property import (
    BUCKET,
    REGION,
    TAX_YEAR,
    _amounts,
    _Env,
)

_entry = st.tuples(
    _amounts,
    st.integers(min_value=1, max_value=12),
    st.integers(min_value=1, max_value=28),
    # Itemized entries need a non-blank description of 1 to 200 characters.
    st.text(alphabet="abc xyz", min_size=1, max_size=20).filter(lambda s: s.strip()),
    st.booleans(),  # attach a receipt
)


@settings(deadline=None, max_examples=100)
@given(
    entries=st.lists(_entry, min_size=0, max_size=4),
    first_import=_amounts,
    second_import=_amounts,
)
# Feature: itemized-expenses, Property 16: Schedule E re-import leaves itemized entries unchanged
def test_reimport_leaves_itemized_entries_unchanged(
    entries, first_import, second_import
) -> None:
    with mock_aws():
        env = _Env()
        s3 = boto3.client("s3", region_name=REGION)
        for amount, month, day, description, with_receipt in entries:
            created = env.txns.create(
                TransactionInput(
                    property_id=env.property_id,
                    date=f"{TAX_YEAR}-{month:02d}-{day:02d}",
                    amount=Decimal(amount),
                    type="expense",
                    category_id="repairs",
                    description=description,
                    itemized=True,
                )
            )
            assert created.is_ok, created.error
            if with_receipt:
                upload = env.txns.attach_receipt(
                    env.property_id, created.value.id, "receipt.pdf", "application/pdf"
                )
                assert upload.is_ok, upload.error
                s3.put_object(
                    Bucket=BUCKET, Key=upload.value.document.s3_key, Body=b"%PDF-1.4"
                )

        def rows():
            listed = env.txns.list_for_property(env.property_id, TAX_YEAR)
            assert listed.is_ok
            return listed.value

        def itemized_state(current):
            state = {}
            for r in current:
                if not r.itemized:
                    continue
                receipts = env.txns.list_receipts(env.property_id, r.id)
                assert receipts.is_ok
                state[r.id] = (
                    asdict(r),
                    sorted(asdict(x.document)["id"] for x in receipts.value),
                )
            return state

        before = itemized_state(rows())
        assert len(before) == len(entries)
        assert sum(len(docs) for _, docs in before.values()) == sum(
            1 for e in entries if e[4]
        )

        previous_import_id = None
        for amount in (first_import, second_import):
            env.import_repairs(amount)
            current = rows()
            assert itemized_state(current) == before
            imported_rows = [r for r in current if r.imported]
            assert len(imported_rows) == 1
            assert imported_rows[0].itemized is False
            assert imported_rows[0].amount == Decimal(amount)
            assert imported_rows[0].id != previous_import_id
            previous_import_id = imported_rows[0].id
            # Nothing besides the itemized entries and the one imported total.
            assert len(current) == len(before) + 1
