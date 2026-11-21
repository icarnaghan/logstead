"""Restore property tests over moto (ui-polish task 9.7).

Property 22  Restore round trip          Requirements 17.4, 17.9, 17.12
Property 23  Restore is claimed once     Requirements 17.5, 17.6

Every Hypothesis example provisions its own moto table and bucket. Records are
created and deleted through the real services, the delete event is built with
the router's own recording helpers (``_crud_event``), and restore runs through
``ActivityService.restore``.
"""

from __future__ import annotations

import contextlib
from datetime import date, datetime, timedelta, timezone
from decimal import Decimal
from typing import Any

import boto3
from hypothesis import Phase, given, settings
from hypothesis import strategies as st
from moto import mock_aws

from logstead.adapters.s3_files import S3FileAdapter
from logstead.models.depreciation import AssetInput
from logstead.models.loan import LoanInput
from logstead.models.property import PropertyInput
from logstead.models.transaction import TransactionInput
from logstead.repository import keys
from logstead.repository.dynamo_repo import DynamoRepository
from logstead.router.handler import _crud_event, _to_jsonable
from logstead.services import activity_events as ev
from logstead.services.activity import PENDING, ActivityRecorder, ActivityService, NewEvent
from logstead.services.depreciation import DepreciationService
from logstead.services.itemized import EntryInput, ItemizedExpenseService
from logstead.services.loan import LoanService
from logstead.services.property import PropertyService
from logstead.services.transaction import TransactionService

TABLE = "Logstead"
BUCKET = "logstead-files-test"
REGION = "us-east-1"
USER = "user-a"
NOW = datetime(2025, 6, 1, 12, 0, 0, tzinfo=timezone.utc)

_SETTINGS = settings(
    deadline=None,
    max_examples=12,
    phases=[Phase.explicit, Phase.reuse, Phase.generate, Phase.shrink],
)

_PROPERTY_NOT_FOUND = "Property not found."
_EVENT_NOT_FOUND = "Activity event not found."


# --- Environment -------------------------------------------------------------


@contextlib.contextmanager
def _moto_env():
    with mock_aws():
        ddb = boto3.client("dynamodb", region_name=REGION)
        ddb.create_table(
            TableName=TABLE,
            AttributeDefinitions=[
                {"AttributeName": n, "AttributeType": "S"}
                for n in ("PK", "SK", "GSI1PK", "GSI1SK", "GSI2PK", "GSI2SK")
            ],
            KeySchema=[
                {"AttributeName": "PK", "KeyType": "HASH"},
                {"AttributeName": "SK", "KeyType": "RANGE"},
            ],
            GlobalSecondaryIndexes=[
                {
                    "IndexName": name,
                    "KeySchema": [
                        {"AttributeName": f"{name}PK", "KeyType": "HASH"},
                        {"AttributeName": f"{name}SK", "KeyType": "RANGE"},
                    ],
                    "Projection": {"ProjectionType": "ALL"},
                }
                for name in ("GSI1", "GSI2")
            ],
            BillingMode="PAY_PER_REQUEST",
        )
        s3 = boto3.client("s3", region_name=REGION)
        s3.create_bucket(Bucket=BUCKET)
        yield DynamoRepository(ddb, TABLE), S3FileAdapter(s3, BUCKET)


class Stack:
    def __init__(self, repo: DynamoRepository, files: S3FileAdapter, user: str = USER) -> None:
        self.repo = repo
        self.user = user
        self.props = PropertyService(repo, user)
        self.txns = TransactionService(repo, files)
        self.itemized = ItemizedExpenseService(self.txns)
        self.assets = DepreciationService(repo)
        self.loans = LoanService(repo, today=lambda: date(2025, 6, 1))
        self.recorder = ActivityRecorder(repo, user, clock=lambda: NOW)
        self.clock = lambda: NOW
        self.svc = self.service()
        pid = self.props.create(
            PropertyInput(name="Main St", address_text="1 Main St", property_type="single_family")
        )
        assert pid.is_ok, pid.error
        self.pid = pid.value.id

    def service(self, clock: Any = None) -> ActivityService:
        return ActivityService(
            self.repo, self.user, self.txns, self.itemized, self.assets, self.loans,
            self.recorder, clock=clock or self.clock,
        )

    # --- records -------------------------------------------------------------

    def create(self, kind: str, spec: dict[str, Any]) -> Any:
        if kind == "transaction":
            r = self.txns.create(
                TransactionInput(
                    property_id=self.pid, date=spec["date"], amount=spec["amount"],
                    type=spec["type"],
                    category_id="rents-received" if spec["type"] == "income" else "insurance",
                    description=spec["desc"], notes=None,
                )
            )
        elif kind == "itemized_entry":
            r = self.itemized.create_entry(
                self.pid, "repairs",
                EntryInput(
                    date=spec["date"], amount=spec["amount"], description=spec["desc"] or "x",
                    notes=spec["notes"], tax_year=int(spec["date"][:4]),
                ),
            )
        elif kind == "asset":
            r = self.assets.create_asset(
                AssetInput(
                    property_id=self.pid, description=spec["desc"] or "x",
                    cost_basis=spec["cost"], placed_in_service_date="2020" + spec["date"][4:],
                    recovery_period_years=spec["period"],
                    depreciation_overrides=spec["overrides"] or None,
                )
            )
        else:
            r = self.loans.create_loan(
                LoanInput(
                    property_id=self.pid, description=spec["desc"] or "x",
                    annual_interest_rate=spec["rate"], monthly_payment=spec["payment"],
                    anchor_balance=spec["balance"], anchor_date="2024-01-15",
                    extra_principal=spec["extra"], original_principal=spec["original"],
                    closing_date=spec["closing"], include_in_report=spec["include"],
                )
            )
        assert r.is_ok, r.error
        return r.value

    def delete(self, kind: str, record: Any) -> None:
        if kind == "transaction":
            r = self.txns.delete(self.pid, record.id)
        elif kind == "itemized_entry":
            r = self.itemized.delete_entry(self.pid, "repairs", record.id)
        elif kind == "asset":
            r = self.assets.delete_asset(self.pid, record.id)
        else:
            r = self.loans.delete_loan(self.pid, record.id)
        assert r.is_ok, r.error

    def record_delete(self, kind: str, record: Any, receipts: int = 0) -> None:
        """Record the delete event exactly as the router does."""
        for event in _crud_event(
            None, None, "delete", kind, self.pid, before=_to_jsonable(record),
            receipts=receipts, property_name="Main St",
        ):
            self.recorder.record(event)

    def delete_and_record(self, kind: str, record: Any) -> str:
        self.delete(kind, record)
        self.record_delete(kind, record)
        return self.events("delete")[0].event_id

    def events(self, action: str | None = None) -> list[Any]:
        page = self.svc.list_property(self.pid, action=action, limit=100)
        assert page.is_ok, page.error
        return list(page.value.events)

    def count(self, kind: str) -> int:
        if kind in ("transaction", "itemized_entry"):
            listed = self.txns.list_for_property(self.pid)
            assert listed.is_ok
            return len(listed.value)
        if kind == "asset":
            return len(self.assets.list_assets(self.pid))
        listed = self.loans.list_loans(self.pid)
        assert listed.is_ok
        return len(listed.value)

    def fetch(self, kind: str, record_id: str) -> Any:
        if kind in ("transaction", "itemized_entry"):
            r = self.txns.get(self.pid, record_id)
        elif kind == "asset":
            r = self.assets.get_asset(self.pid, record_id)
        else:
            r = self.loans.get_loan(self.pid, record_id)
        assert r.is_ok, r.error
        return r.value

    def raw_event(self, event_id: str) -> dict[str, Any]:
        item = self.repo.get_item(
            keys.user_pk(self.user), keys.ACT_PREFIX + event_id.replace(".", "#", 1)
        )
        assert item is not None
        return item


# --- Strategies --------------------------------------------------------------

_text = st.text(alphabet="abAB é.*%-", min_size=1, max_size=10).filter(lambda s: bool(s.strip()) and s == s.strip())
_opt_text = st.none() | _text
_money = st.decimals(
    min_value=Decimal("0.01"), max_value=Decimal("99999.99"), places=2,
    allow_nan=False, allow_infinity=False,
)
_date = st.builds(
    lambda y, m, d: f"{y:04d}-{m:02d}-{d:02d}",
    st.integers(2018, 2024), st.integers(1, 12), st.integers(1, 28),
)
_kind = st.sampled_from(["transaction", "itemized_entry", "asset", "loan"])

_spec = st.fixed_dictionaries(
    {
        "date": _date,
        "amount": _money,
        "cost": st.decimals(Decimal("1000.00"), Decimal("99999.99"), places=2),
        "type": st.sampled_from(["income", "expense"]),
        "desc": _text,
        "notes": _opt_text,
        "period": st.sampled_from([Decimal("27.5"), Decimal("15")]),
        "overrides": st.dictionaries(
            st.integers(2021, 2026), st.decimals(Decimal("0.01"), Decimal("5.00"), places=2),
            max_size=2,
        ),
        "rate": st.decimals(Decimal("1.0"), Decimal("9.0"), places=2),
        "balance": st.decimals(Decimal("10000"), Decimal("200000"), places=2),
        "payment": st.decimals(Decimal("3000"), Decimal("5000"), places=2),
        "extra": st.none() | st.decimals(Decimal("1.00"), Decimal("100.00"), places=2),
        "original": st.none() | st.decimals(Decimal("200000"), Decimal("300000"), places=2),
        "closing": st.none() | _date,
        "include": st.booleans(),
    }
)

_EXTRA_FIELDS = {
    "transaction": (),
    "itemized_entry": (),
    "asset": ("depreciation_overrides",),
    "loan": ("extra_principal", "original_principal", "closing_date", "payoff_date"),
}


def _comparable(kind: str, record: Any) -> dict[str, Any]:
    data = _to_jsonable(record)
    out: dict[str, Any] = dict(ev.project(kind, data))
    for name in _EXTRA_FIELDS[kind]:
        out[name] = data.get(name)
    return out


# --- Property 22 -------------------------------------------------------------


@_SETTINGS
@given(kind=_kind, spec=_spec)
def test_restore_round_trip(kind: str, spec: dict[str, Any]) -> None:
    """**Property 22: Restore round trip**

    **Validates: Requirements 17.4, 17.9, 17.12**
    """
    with _moto_env() as (repo, files):
        s = Stack(repo, files)
        original = s.create(kind, spec)
        before = _comparable(kind, original)
        event_id = s.delete_and_record(kind, original)
        assert s.count(kind) == 0
        assert s.events("delete")[0].restorable is True

        result = s.svc.restore(s.pid, event_id)
        assert result.is_ok, result.error
        outcome = result.value

        restored = s.fetch(kind, outcome.record_id)
        assert outcome.record_id != original.id
        assert restored.id == outcome.record_id
        assert _comparable(kind, restored) == before
        assert s.count(kind) == 1

        marked = next(e for e in s.events() if e.event_id == event_id)
        assert marked.restored_as == outcome.record_id
        assert marked.restored_at == outcome.restored_at

        restores = s.events("restore")
        assert len(restores) == 1
        assert restores[0].record_id == outcome.record_id
        assert restores[0].entity == kind


# --- Property 23 -------------------------------------------------------------


@_SETTINGS
@given(kind=_kind, spec=_spec, requests=st.integers(1, 5))
def test_restore_is_claimed_once(kind: str, spec: dict[str, Any], requests: int) -> None:
    """**Property 23: Restore is claimed once**

    **Validates: Requirements 17.5, 17.6**
    """
    with _moto_env() as (repo, files):
        s = Stack(repo, files)
        event_id = s.delete_and_record(kind, s.create(kind, spec))

        results = [s.svc.restore(s.pid, event_id) for _ in range(requests)]

        assert [r.is_ok for r in results] == [True] + [False] * (requests - 1)
        for r in results[1:]:
            assert r.error.kind == "conflict"
            assert r.error.message == "This event was already restored."
        assert s.count(kind) == 1
        assert len(s.events("restore")) == 1


# --- Examples ----------------------------------------------------------------

_TX = {
    "date": "2024-03-04", "amount": Decimal("12.50"), "type": "expense", "desc": "Filter",
    "notes": None, "period": Decimal("27.5"), "overrides": {}, "rate": Decimal("5.00"),
    "balance": Decimal("100000.00"), "payment": Decimal("4000.00"), "extra": None,
    "original": None, "closing": None, "include": True,
}


def test_failed_recreate_releases_the_claim() -> None:
    with _moto_env() as (repo, files):
        s = Stack(repo, files)
        # The category no longer exists, so the re-create fails validation.
        s.recorder.record(
            NewEvent(
                action="delete", entity="itemized_entry", summary="Deleted itemized entry: x",
                record_id="gone", property_id=s.pid, restorable=True,
                restore_payload={
                    "date": "2024-03-04", "amount": "5.00", "type": "expense",
                    "category_id": "no-such-category", "description": "x", "tax_year": 2024,
                },
            )
        )
        event_id = s.events("delete")[0].event_id

        first = s.svc.restore(s.pid, event_id)
        assert not first.is_ok
        assert first.error.kind in ("validation", "not_found")
        raw = s.raw_event(event_id)
        assert "restoredAt" not in raw and "restoredAs" not in raw
        assert s.count("transaction") == 0
        assert s.events("restore") == []
        # The claim is free again: a second attempt reaches the create path (same error).
        again = s.svc.restore(s.pid, event_id)
        assert not again.is_ok and again.error.kind == first.error.kind


def test_stale_pending_claim_is_free_and_fresh_one_is_not() -> None:
    with _moto_env() as (repo, files):
        s = Stack(repo, files)
        event_id = s.delete_and_record("transaction", s.create("transaction", _TX))
        raw = s.raw_event(event_id)

        fresh = {**raw, "restoredAt": "2025-06-01T11:58:00.000Z", "restoredAs": PENDING}
        repo.put_item(fresh)
        blocked = s.svc.restore(s.pid, event_id)
        assert not blocked.is_ok and blocked.error.kind == "conflict"
        assert s.count("transaction") == 0

        stale = {**raw, "restoredAt": "2025-06-01T11:50:00.000Z", "restoredAs": PENDING}
        repo.put_item(stale)
        result = s.svc.restore(s.pid, event_id)
        assert result.is_ok, result.error
        assert s.count("transaction") == 1
        assert s.raw_event(event_id)["restoredAs"] == result.value.record_id
        assert s.svc.restore(s.pid, event_id).error.kind == "conflict"


def test_non_restorable_events_return_conflict_and_create_nothing() -> None:
    with _moto_env() as (repo, files):
        s = Stack(repo, files)
        rec = s.create("transaction", _TX)
        s.delete("transaction", rec)
        s.record_delete("transaction", rec, receipts=1)  # has a receipt: not restorable
        s.recorder.record(
            NewEvent(action="update", entity="transaction", summary="Updated", property_id=s.pid,
                     restorable=True, restore_payload={"amount": "1.00"})
        )
        ids = [e.event_id for e in s.events()]
        assert len(ids) == 2
        for event_id in ids:
            r = s.svc.restore(s.pid, event_id)
            assert not r.is_ok and r.error.kind == "conflict"
        assert s.count("transaction") == 0
        assert s.events("restore") == []


def test_unknown_event_and_foreign_property_are_not_found() -> None:
    with _moto_env() as (repo, files):
        s = Stack(repo, files)
        other = Stack(repo, files, user="user-b")
        event_id = s.delete_and_record("transaction", s.create("transaction", _TX))

        unknown = s.svc.restore(s.pid, "99999999999999.00000000-0000-0000-0000-000000000000")
        assert unknown.error.kind == "not_found" and unknown.error.message == _EVENT_NOT_FOUND
        malformed = s.svc.restore(s.pid, "not-an-event")
        assert malformed.error.message == _EVENT_NOT_FOUND

        # Another user's property and a missing property give the same error.
        foreign = other.svc.restore(s.pid, event_id)
        missing = other.svc.restore("no-such-property", event_id)
        assert foreign.error.kind == missing.error.kind == "not_found"
        assert foreign.error.message == missing.error.message == _PROPERTY_NOT_FOUND
        # An event of this property named through the other user's property is unknown.
        crossed = other.svc.restore(other.pid, event_id)
        assert crossed.error.message == _EVENT_NOT_FOUND
        assert s.count("transaction") == 0 and other.count("transaction") == 0
