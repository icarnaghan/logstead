"""Read seams added for the year-end checklist, over moto.

Covers ``LoanService.year_facts``, ``TransactionService.has_receipt`` and
``resolve_category_rows`` (Requirements 2.4, 4.2, 4.4, 12.7).
"""
from __future__ import annotations

from datetime import date
from decimal import Decimal

import boto3
import pytest
from moto import mock_aws

from logstead.models.loan import LoanInput
from logstead.models.transaction import TransactionInput
from logstead.repository import keys
from logstead.services.itemized import (
    EntryInput,
    ItemizedExpenseService,
    resolve_category_rows,
)
from logstead.services.loan import LoanService, StoredLoanError
from tests.services.test_imported_marker_update_property import (
    REGION,
    TAX_YEAR,
    _Env,
)


@pytest.fixture
def env():
    with mock_aws():
        yield _Env()


def _loan(pid: str, **kw) -> LoanInput:
    base = dict(
        property_id=pid,
        description="Mortgage",
        annual_interest_rate=Decimal("0"),
        monthly_payment=Decimal("1000.00"),
        anchor_balance=Decimal("5000.00"),
        anchor_date="2025-06-01",
        original_principal=None,
        closing_date=None,
    )
    base.update(kw)
    return LoanInput(**base)


def _txn(env: _Env, **kw):
    base = dict(
        property_id=env.property_id,
        date=f"{TAX_YEAR}-03-05",
        amount=Decimal("300.00"),
        type="expense",
        category_id="repairs",
        description="Fix",
    )
    base.update(kw)
    created = env.txns.create(TransactionInput(**base))
    assert created.is_ok, created.error
    return created.value


# --- LoanService.year_facts -------------------------------------------------


def test_year_facts_overrides_excluded_and_late_anchor(env):
    svc = LoanService(env.repo, today=lambda: date(2025, 6, 1))
    pid = env.property_id
    plain = svc.create_loan(_loan(pid, description="Plain")).value
    overridden = svc.create_loan(_loan(pid, description="Overridden")).value
    excluded = svc.create_loan(
        _loan(pid, description="Excluded", include_in_report=False)
    ).value
    late = svc.create_loan(
        _loan(pid, description="Late", anchor_date="2027-01-01")
    ).value
    assert svc.set_interest_override(pid, overridden.id, 2025, "123.45").is_ok

    facts = {f.loan_id: f for f in svc.year_facts(pid, 2025)}

    assert set(facts) == {plain.id, overridden.id, excluded.id, late.id}
    assert facts[plain.id].description == "Plain"
    assert facts[plain.id].anchor_date == "2025-06-01"
    assert facts[plain.id].include_in_report is True
    assert facts[plain.id].has_override is False
    assert facts[plain.id].interest == Decimal("0.00")
    assert facts[overridden.id].has_override is True
    assert facts[overridden.id].interest == Decimal("123.45")
    assert facts[excluded.id].include_in_report is False
    assert facts[late.id].anchor_date == "2027-01-01"
    assert facts[late.id].interest == Decimal("0.00")
    assert facts[late.id].has_override is False


def test_year_facts_empty_property_and_other_year(env):
    svc = LoanService(env.repo, today=lambda: date(2025, 6, 1))
    assert svc.year_facts(env.property_id, 2025) == []
    loan = svc.create_loan(_loan(env.property_id)).value
    (fact,) = svc.year_facts(env.property_id, 2019)
    assert fact.loan_id == loan.id
    assert fact.interest == Decimal("0.00")


def test_year_facts_writes_nothing(env):
    svc = LoanService(env.repo, today=lambda: date(2025, 6, 1))
    svc.create_loan(_loan(env.property_id))
    ddb = boto3.client("dynamodb", region_name=REGION)

    def snapshot():
        return sorted(
            repr(sorted(i.items())) for i in ddb.scan(TableName="Logstead")["Items"]
        )

    before = snapshot()
    svc.year_facts(env.property_id, 2025)
    assert snapshot() == before


def test_year_facts_corrupt_loan_raises(env):
    svc = LoanService(env.repo, today=lambda: date(2025, 6, 1))
    pid = env.property_id
    loan = svc.create_loan(_loan(pid)).value
    item = env.repo.get_item(
        keys.property_scoped_pk(pid), keys.loan_sk(loan.id), money_attrs=set()
    )
    item["anchorDate"] = "bad"
    env.repo.put_item(item, money_attrs=set())
    with pytest.raises(StoredLoanError):
        svc.year_facts(pid, 2025)


# --- TransactionService.has_receipt ----------------------------------------


def test_has_receipt_with_without_and_other_transaction(env):
    with_receipt = _txn(env, description="With")
    without = _txn(env, description="Without")
    other_day = _txn(env, description="Other", date=f"{TAX_YEAR}-03-06")
    upload = env.txns.attach_receipt(
        env.property_id, with_receipt.id, "r.pdf", "application/pdf"
    )
    assert upload.is_ok, upload.error

    assert env.txns.has_receipt(env.property_id, with_receipt) is True
    assert env.txns.has_receipt(env.property_id, without) is False
    assert env.txns.has_receipt(env.property_id, other_day) is False


def test_has_receipt_makes_no_s3_call(env, monkeypatch):
    txn = _txn(env)
    assert env.txns.attach_receipt(
        env.property_id, txn.id, "r.pdf", "application/pdf"
    ).is_ok

    def boom(*a, **k):
        raise AssertionError("S3 must not be called")

    for name in ("presigned_get_url", "purge_if_oversized", "delete_object"):
        monkeypatch.setattr(env.files, name, boom)
    assert env.txns.has_receipt(env.property_id, txn) is True


# --- resolve_category_rows --------------------------------------------------


def test_resolve_category_rows_matches_summary(env):
    itemized = ItemizedExpenseService(env.txns)
    env.import_repairs("1000.00")
    for amount, day in (("400.00", 10), ("700.00", 11)):
        created = itemized.create_entry(
            env.property_id,
            "repairs",
            EntryInput(
                date=f"{TAX_YEAR}-04-{day}",
                amount=Decimal(amount),
                description="Entry",
                tax_year=TAX_YEAR,
            ),
        )
        assert created.is_ok, created.error
    _txn(env, category_id="utilities", description="Elec")  # other category

    listed = env.txns.list_for_property(env.property_id, TAX_YEAR).value
    rows = resolve_category_rows(listed, "repairs")
    summary = itemized.summary(env.property_id, "repairs", TAX_YEAR).value

    res = rows.resolution
    assert res.entered_total == summary.entered_total == Decimal("1000.00")
    assert res.itemized_sum == summary.itemized_sum == Decimal("1100.00")
    assert res.itemized_count == summary.itemized_count == 2
    assert res.remainder == summary.remainder == Decimal("-100.00")
    assert res.line_total == summary.line_total
    assert res.source == summary.line_source
    assert [t.id for t in rows.entries] == [t.id for t in summary.entries]
    assert [t.id for t in rows.total_rows] == [
        t.id for t in summary.entered_total_rows
    ]
    assert all(t.category_id == "repairs" for t in rows.entries + rows.total_rows)


def test_resolve_category_rows_empty():
    rows = resolve_category_rows([], "repairs")
    assert rows.entries == () and rows.total_rows == ()
    assert rows.resolution.entered_total is None
    assert rows.resolution.itemized_count == 0
