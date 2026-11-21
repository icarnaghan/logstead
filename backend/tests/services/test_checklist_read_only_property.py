"""Property 19: the checklist is read-only.

# Feature: year-end-checklist, Property 19: The checklist is read-only

**Validates: Requirements 2.1, 2.4**

For generated stored data, running the Checklist, the property summary and the
dashboard summary performs zero repository writes (``put_item``,
``delete_item``, ``transact_write``) and zero S3 calls, and the stored items
are identical before and after.
"""

from __future__ import annotations

from decimal import Decimal

import boto3
from hypothesis import given, settings
from hypothesis import strategies as st
from moto import mock_aws

from logstead.adapters.s3_files import S3FileAdapter
from logstead.models.loan import LoanInput
from logstead.models.transaction import TransactionInput
from logstead.services.carryforward import CarryforwardService
from logstead.services.checklist import ChecklistService
from logstead.services.depreciation import DepreciationService
from logstead.services.itemized import EntryInput, ItemizedExpenseService
from logstead.services.loan import LoanService
from logstead.services.property import PropertyService
from logstead.services.report import ReportingService
from logstead.services.transaction import TransactionService
from tests.services.test_imported_marker_update_property import (
    BUCKET,
    REGION,
    TABLE_NAME,
    TAX_YEAR,
    USER_ID,
    _Env,
)

WRITE_METHODS = {"put_item", "delete_item", "transact_write"}


class _RecordingRepo:
    """Delegates to the real repository and records every write call."""

    def __init__(self, inner) -> None:
        self._inner = inner
        self.writes: list[str] = []

    def __getattr__(self, name):
        attr = getattr(self._inner, name)
        if name in WRITE_METHODS or name.startswith(("batch", "update")):
            def recorded(*args, **kwargs):
                self.writes.append(name)
                return attr(*args, **kwargs)

            return recorded
        return attr


class _RecordingFiles:
    """Records any S3 adapter call (the checklist must make none)."""

    def __init__(self, inner) -> None:
        self._inner = inner
        self.calls: list[str] = []

    def __getattr__(self, name):
        attr = getattr(self._inner, name)
        if callable(attr):
            def recorded(*args, **kwargs):
                self.calls.append(name)
                return attr(*args, **kwargs)

            return recorded
        self.calls.append(name)
        return attr


def _scan_all(ddb) -> list[dict]:
    items: list[dict] = []
    kwargs: dict = {"TableName": TABLE_NAME}
    while True:
        resp = ddb.scan(**kwargs)
        items.extend(resp.get("Items", []))
        last = resp.get("LastEvaluatedKey")
        if not last:
            break
        kwargs["ExclusiveStartKey"] = last
    return sorted(items, key=lambda i: (i["PK"]["S"], i["SK"]["S"]))


def _s3_state(s3) -> list[tuple[str, int]]:
    resp = s3.list_objects_v2(Bucket=BUCKET)
    return sorted((o["Key"], o["Size"]) for o in resp.get("Contents", []))


_amounts = st.decimals(
    min_value=Decimal("1.00"), max_value=Decimal("5000.00"), places=2
)
_txn_specs = st.lists(
    st.tuples(
        st.sampled_from(["rents-received", "repairs", "insurance", "supplies"]),
        _amounts,
        st.booleans(),  # attach a receipt
    ),
    max_size=5,
)


@settings(deadline=None, max_examples=100)
@given(
    txn_specs=_txn_specs,
    import_total=st.one_of(st.none(), _amounts),
    entry_amounts=st.lists(_amounts, max_size=3),
    with_loan=st.booleans(),
    override=st.one_of(st.none(), _amounts),
    year_arg=st.sampled_from([None, TAX_YEAR]),
)
def test_checklist_is_read_only(
    txn_specs, import_total, entry_amounts, with_loan, override, year_arg
) -> None:
    """Feature: year-end-checklist, Property 19: The checklist is read-only.

    **Validates: Requirements 2.1, 2.4**
    """
    with mock_aws():
        env = _Env()
        pid = env.property_id
        ddb = env.repo._client  # raw client for before/after scans
        s3 = boto3.client("s3", region_name=REGION)

        # --- Seed with the unwrapped services -------------------------------
        for category, amount, receipt in txn_specs:
            kind = "income" if category == "rents-received" else "expense"
            created = env.txns.create(
                TransactionInput(
                    property_id=pid,
                    date=f"{TAX_YEAR}-03-05",
                    amount=amount,
                    type=kind,
                    category_id=category,
                    description="seed",
                )
            )
            assert created.is_ok, created.error
            if receipt:
                attached = env.txns.attach_receipt(
                    pid, created.value.id, "r.pdf", "application/pdf"
                )
                assert attached.is_ok, attached.error
        if import_total is not None:
            env.import_repairs(str(import_total))
        itemized = ItemizedExpenseService(env.txns)
        for amount in entry_amounts:
            made = itemized.create_entry(
                pid,
                "repairs",
                EntryInput(
                    date=f"{TAX_YEAR}-04-01", amount=amount, description="e"
                ),
            )
            assert made.is_ok, made.error
        loan_svc = LoanService(env.repo)
        if with_loan:
            loan = loan_svc.create_loan(
                LoanInput(
                    property_id=pid,
                    description="Mortgage",
                    annual_interest_rate=Decimal("5"),
                    monthly_payment=Decimal("1000.00"),
                    anchor_balance=Decimal("100000.00"),
                    anchor_date=f"{TAX_YEAR}-01-01",
                    original_principal=None,
                    closing_date=None,
                )
            )
            assert loan.is_ok, loan.error
            if override is not None:
                assert loan_svc.set_interest_override(
                    pid, loan.value.id, TAX_YEAR, str(override)
                ).is_ok

        # --- Wrap and run the three entry points ----------------------------
        repo = _RecordingRepo(env.repo)
        files = _RecordingFiles(env.files)
        user = USER_ID
        txns = TransactionService(repo, files)
        deps = DepreciationService(repo)
        loans = LoanService(repo)
        props = PropertyService(repo, user)
        reports = ReportingService(txns, deps, props, loans=loans)
        carry = CarryforwardService(
            repo, user, reports, props, txns, deps, loans=loans
        )
        service = ChecklistService(reports, txns, deps, loans, props, carry)

        before_items = _scan_all(ddb)
        before_s3 = _s3_state(s3)

        year = year_arg or TAX_YEAR
        assert service.checklist_for(pid, year).is_ok
        assert service.property_summary(pid).is_ok
        assert service.portfolio_summary(year).is_ok

        assert repo.writes == []
        assert files.calls == []
        assert _scan_all(ddb) == before_items
        assert _s3_state(s3) == before_s3
