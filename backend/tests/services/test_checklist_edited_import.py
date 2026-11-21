"""Edited-after-import detection through the real services over moto
(year-end checklist task 4.8; Requirements 14.3, 14.4, 15.4).
"""
from __future__ import annotations

from decimal import Decimal

import pytest
from moto import mock_aws

from logstead.models.transaction import TransactionInput
from logstead.router.handler import _transaction_input
from logstead.services.backup import BackupService
from logstead.services.itemized import ItemizedExpenseService
from tests.services.test_checklist_service import _real
from tests.services.test_imported_marker_update_property import (
    TAX_YEAR,
    USER_ID,
    _Env,
)
from logstead.models.user import UserContext
from logstead.router.handler import _to_jsonable


@pytest.fixture
def env():
    with mock_aws():
        yield _Env()


def _status(service, env) -> str:
    result = service.checklist_for(env.property_id, TAX_YEAR)
    assert result.is_ok, result.error
    return next(
        i.status for i in result.value.items if i.id == "imported_values_edited"
    )


def _imported_row(env):
    rows = [t for t in env.repairs_rows() if t.imported]
    assert len(rows) == 1
    return rows[0]


def _update_amount(env, row, amount: str):
    return env.txns.update(
        env.property_id,
        row.id,
        TransactionInput(
            property_id=env.property_id,
            date=row.date,
            amount=Decimal(amount),
            type=row.type,
            category_id=row.category_id,
            description=row.description,
        ),
    )


def test_import_is_done(env):
    service, _ = _real(env)
    env.import_repairs("500.00")
    assert _status(service, env) == "done"


def test_transaction_update_marks_needs_attention_and_stays(env):
    service, _ = _real(env)
    env.import_repairs("500.00")
    row = _imported_row(env)
    assert _update_amount(env, row, "650.00").is_ok
    assert _status(service, env) == "needs_attention"
    # Setting the amount back does not clear it: the filed figure is not stored.
    assert _update_amount(env, row, "500.00").is_ok
    assert _status(service, env) == "needs_attention"
    # Re-import replaces the rows and clears it.
    env.import_repairs("500.00")
    assert _status(service, env) == "done"


def test_set_total_marks_needs_attention(env):
    service, _ = _real(env)
    env.import_repairs("500.00")
    done = ItemizedExpenseService(env.txns).set_total(
        env.property_id, "repairs", TAX_YEAR, Decimal("700.00")
    )
    assert done.is_ok, done.error
    assert _imported_row(env).imported is True
    assert _status(service, env) == "needs_attention"


def test_attaching_receipt_does_not_change_status(env):
    service, _ = _real(env)
    env.import_repairs("500.00")
    row = _imported_row(env)
    assert _status(service, env) == "done"
    attached = env.txns.attach_receipt(
        env.property_id, row.id, "r.pdf", "application/pdf"
    )
    assert attached.is_ok, attached.error
    assert _status(service, env) == "done"


def _round_trip(env):
    backup = BackupService(env.repo, env.files, UserContext(user_id=USER_ID))
    doc = _to_jsonable(backup.export())
    assert backup.restore(doc).is_ok
    return backup, doc


def test_backup_restore_keeps_classification(env):
    service, _ = _real(env)
    env.import_repairs("500.00")
    row = _imported_row(env)
    assert _update_amount(env, row, "650.00").is_ok
    _round_trip(env)
    assert _status(service, env) == "needs_attention"

    env.import_repairs("500.00")
    assert _status(service, env) == "done"
    _round_trip(env)
    assert _status(service, env) == "done"


def test_restored_row_without_timestamps_is_not_edited(env):
    service, _ = _real(env)
    env.import_repairs("500.00")
    row = _imported_row(env)
    assert _update_amount(env, row, "650.00").is_ok
    backup = BackupService(env.repo, env.files, UserContext(user_id=USER_ID))
    doc = _to_jsonable(backup.export())
    for prop in doc["properties"]:
        for txn in prop["transactions"]:
            txn.pop("created_at", None)
            txn.pop("updated_at", None)
    assert backup.restore(doc).is_ok
    assert _status(service, env) == "done"


def test_generic_create_route_is_not_imported(env):
    body = {
        "date": f"{TAX_YEAR}-12-31",
        "amount": "10.00",
        "type": "expense",
        "category_id": "repairs",
        "imported": True,
    }
    created = env.txns.create(_transaction_input(body, env.property_id))
    assert created.is_ok, created.error
    assert created.value.imported is False
