"""Property-based tests for anchor-shape Loans in backup/restore.

* Property 20: Backup round trip preserves anchor-shape Loans and overrides.

Plus examples: an unknown property reference rejects the restore, a document
without ``loans`` restores as zero loans, and the export carries no rollup or
payment rows.

**Validates: Requirements 9.1, 9.2, 9.3, 9.5**
"""

from __future__ import annotations

import re
import uuid
from datetime import date, datetime, timedelta, timezone
from decimal import Decimal
from typing import Any

import boto3
import pytest
from hypothesis import given, settings
from hypothesis import strategies as st
from moto import mock_aws

from logstead.adapters.s3_files import S3FileAdapter
from logstead.models.loan import Loan
from logstead.repository import keys
from logstead.repository.dynamo_repo import DynamoRepository
from logstead.router.handler import _to_jsonable
from logstead.services.backup import BackupService
from logstead.services.loan import (
    _rollup_from_item,
    build_yearly_rollups,
    compute_payment_rows,
)

REGION = "us-east-1"
TABLE_NAME = "logstead-backup-loan-test"
BUCKET = "logstead-backup-loan-test-files"
USER_ID = "user-loan-backup"
_MAX_EXAMPLES = 20
_TWO_DP = re.compile(r"^\d+\.\d{2}$")


# ---------------------------------------------------------------------------
# Fixtures and helpers
# ---------------------------------------------------------------------------


class Env:
    def __init__(self, ddb: Any, s3: Any) -> None:
        self.ddb = ddb
        self.repo = DynamoRepository(ddb, TABLE_NAME)
        self.files = S3FileAdapter(s3, BUCKET)
        self.backup = BackupService(self.repo, self.files, USER_ID)


@pytest.fixture(scope="module")
def env():
    with mock_aws():
        ddb = boto3.client("dynamodb", region_name=REGION)
        ddb.create_table(
            TableName=TABLE_NAME,
            AttributeDefinitions=[
                {"AttributeName": "PK", "AttributeType": "S"},
                {"AttributeName": "SK", "AttributeType": "S"},
                {"AttributeName": "GSI1PK", "AttributeType": "S"},
                {"AttributeName": "GSI1SK", "AttributeType": "S"},
                {"AttributeName": "GSI2PK", "AttributeType": "S"},
                {"AttributeName": "GSI2SK", "AttributeType": "S"},
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
        yield Env(ddb, s3)


def _purge(env: Env) -> None:
    """Empty the shared table so every example starts from an empty account."""
    kwargs: dict[str, Any] = {"TableName": TABLE_NAME, "ProjectionExpression": "PK, SK"}
    while True:
        page = env.ddb.scan(**kwargs)
        for item in page["Items"]:
            env.ddb.delete_item(TableName=TABLE_NAME, Key=item)
        if "LastEvaluatedKey" not in page:
            break
        kwargs["ExclusiveStartKey"] = page["LastEvaluatedKey"]


def _snapshot(env: Env) -> list[dict[str, Any]]:
    """Every stored item, in a deterministic order."""
    items: list[dict[str, Any]] = []
    kwargs: dict[str, Any] = {"TableName": TABLE_NAME}
    while True:
        page = env.ddb.scan(**kwargs)
        items.extend(page["Items"])
        if "LastEvaluatedKey" not in page:
            break
        kwargs["ExclusiveStartKey"] = page["LastEvaluatedKey"]
    return sorted(items, key=lambda i: (i["PK"]["S"], i["SK"]["S"]))


def _money(cents: int) -> str:
    return f"{Decimal(cents).scaleb(-2):.2f}"


def _loan_of(raw: dict[str, Any], overrides: dict[int, Decimal] | None = None) -> Loan:
    return Loan(
        id=raw["id"],
        property_id=raw["property_id"],
        description=raw["description"],
        annual_interest_rate=Decimal(raw["annual_interest_rate"]),
        monthly_payment=Decimal(raw["monthly_payment"]),
        anchor_balance=Decimal(raw["anchor_balance"]),
        anchor_date=raw["anchor_date"],
        extra_principal=Decimal(raw.get("extra_principal") or "0.00"),
        payoff_date=raw.get("payoff_date"),
        original_principal=(
            Decimal(raw["original_principal"])
            if raw.get("original_principal")
            else None
        ),
        closing_date=raw.get("closing_date"),
        include_in_report=raw.get("include_in_report", True),
        interest_overrides=overrides or {},
        created_at=raw["created_at"],
        updated_at=raw["updated_at"],
    )


def _override_candidates(raw: dict[str, Any]) -> list[int]:
    """Years an override may target: 1900..anchor year plus generated years."""
    loan = _loan_of(raw)
    rows, _ = compute_payment_rows(loan)
    anchor_year = int(raw["anchor_date"][0:4])
    generated = {int(r.date[0:4]) for r in rows}
    pre_anchor = range(max(1900, anchor_year - 10), anchor_year + 1)
    return sorted(generated | set(pre_anchor))


def _property_doc(prop_id: str, loans: list[dict[str, Any]] | None) -> dict[str, Any]:
    prop: dict[str, Any] = {
        "id": prop_id,
        "name": "Loan backup property",
        "address_text": "1 Test St",
        "created_at": "2024-01-01T00:00:00+00:00",
        "updated_at": "2024-01-02T00:00:00+00:00",
    }
    if loans is not None:
        prop["loans"] = loans
    return {
        "schema_version": "1",
        "exported_at": "2025-01-01T00:00:00+00:00",
        "properties": [prop],
    }


def _stored_rollups(env: Env, prop_id: str, loan_id: str):
    items = env.repo.query(
        keys.property_scoped_pk(prop_id),
        sk_begins_with=keys.loan_year_list_prefix(loan_id),
        money_attrs=set(),
    )
    return sorted(
        (_rollup_from_item(i) for i in items), key=lambda r: r.tax_year
    )


# ---------------------------------------------------------------------------
# Strategies
# ---------------------------------------------------------------------------

_ts = st.integers(1_500_000_000, 1_900_000_000).map(
    lambda s: datetime.fromtimestamp(s, tz=timezone.utc).isoformat()
)


@st.composite
def _raw_loan(draw: st.DrawFn, prop_id: str) -> dict[str, Any]:
    """A valid raw anchor-shape backup loan (no overrides yet)."""
    balance_cents = draw(st.integers(100_000, 100_000_000))
    # Payment is 1.1%-5% of the balance; with rate <= 12% this exceeds the
    # first month's interest and keeps the schedule well under 600 rows.
    payment_cents = balance_cents * draw(st.integers(110, 500)) // 10_000
    rate = Decimal(draw(st.integers(0, 120_000))).scaleb(-4)
    anchor = draw(st.dates(date(2000, 1, 1), date(2040, 12, 31)))
    raw: dict[str, Any] = {
        "id": str(uuid.uuid4()),
        "property_id": prop_id,
        "description": draw(st.text(min_size=1, max_size=40).map(str.strip).filter(bool)),
        "annual_interest_rate": str(rate),
        "monthly_payment": _money(payment_cents),
        "anchor_balance": _money(balance_cents),
        "anchor_date": anchor.isoformat(),
        "extra_principal": _money(draw(st.integers(0, 50_000))),
        "include_in_report": draw(st.booleans()),
        "created_at": draw(_ts),
        "updated_at": draw(_ts),
    }
    if draw(st.booleans()):
        raw["original_principal"] = _money(draw(st.integers(100_000, 200_000_000)))
    if draw(st.booleans()):
        raw["closing_date"] = (
            anchor - timedelta(days=draw(st.integers(0, 4000)))
        ).isoformat()
    if draw(st.booleans()):
        # At least a month and a day after the anchor, so >= next payment date.
        raw["payoff_date"] = (
            anchor + timedelta(days=draw(st.integers(32, 3000)))
        ).isoformat()
    return raw


@st.composite
def _loans_with_overrides(
    draw: st.DrawFn, prop_id: str, min_size: int = 1, max_size: int = 3
) -> list[dict[str, Any]]:
    loans = draw(st.lists(_raw_loan(prop_id), min_size=min_size, max_size=max_size))
    for raw in loans:
        years = _override_candidates(raw)
        chosen = draw(st.lists(st.sampled_from(years), unique=True, max_size=len(years)))
        raw["interest_overrides"] = {
            str(y): _money(draw(st.integers(0, 10_000_000))) for y in chosen
        }
    return loans


# ---------------------------------------------------------------------------
# Property 20
# ---------------------------------------------------------------------------

_LOAN_KEYS = {
    "id", "property_id", "description", "annual_interest_rate",
    "monthly_payment", "anchor_balance", "anchor_date", "extra_principal",
    "payoff_date", "original_principal", "closing_date", "include_in_report",
    "interest_overrides", "created_at", "updated_at",
}
_MONEY_KEYS = ("monthly_payment", "anchor_balance", "extra_principal")


def _exported_loans(doc: dict[str, Any]) -> list[dict[str, Any]]:
    return sorted(
        (loan for p in doc["properties"] for loan in p["loans"]),
        key=lambda loan: loan["id"],
    )


@settings(deadline=None, max_examples=_MAX_EXAMPLES)
@given(data=st.data())
def test_backup_round_trip_preserves_loans(env: Env, data: st.DataObject) -> None:
    """Property 20."""
    _purge(env)
    prop_id = str(uuid.uuid4())
    loans = data.draw(_loans_with_overrides(prop_id))
    doc = _property_doc(prop_id, loans)

    summary = env.backup.restore(doc)
    assert summary.is_ok, summary.error
    assert summary.value.loans == len(loans)  # restore summary count

    first = _to_jsonable(env.backup.export())
    exported = _exported_loans(first)

    # Loan content matches what was put in: ids, timestamps, inputs, overrides.
    assert len(exported) == len(loans)
    for out, src in zip(exported, sorted(loans, key=lambda x: x["id"])):
        assert set(out) == _LOAN_KEYS  # no rollup or payment fields
        for k in ("id", "property_id", "description", "anchor_date",
                  "include_in_report", "created_at", "updated_at",
                  "closing_date", "payoff_date", "original_principal"):
            assert out[k] == src.get(k), k
        assert Decimal(out["annual_interest_rate"]) == Decimal(src["annual_interest_rate"])
        for k in _MONEY_KEYS:
            assert out[k] == src[k], k
        assert out["interest_overrides"] == src["interest_overrides"]
        # Every money value has exactly two decimals.
        for k in _MONEY_KEYS:
            assert _TWO_DP.match(out[k]), out[k]
        if out["original_principal"] is not None:
            assert _TWO_DP.match(out["original_principal"])
        assert all(_TWO_DP.match(v) for v in out["interest_overrides"].values())

    # No rollup or payment rows leak into the document anywhere.
    assert "rollups" not in str(first) and "payments" not in str(first)

    # Restored rollups equal the engine output for each restored loan,
    # including override-only years.
    for out in exported:
        overrides = {int(y): Decimal(v) for y, v in out["interest_overrides"].items()}
        restored = _loan_of(out, overrides)
        rows, _ = compute_payment_rows(restored)
        expected = sorted(build_yearly_rollups(restored, rows), key=lambda r: r.tax_year)
        assert _stored_rollups(env, prop_id, out["id"]) == expected

    # Restoring the export into an empty account and exporting again is identical.
    _purge(env)
    again = env.backup.restore(first)
    assert again.is_ok, again.error
    assert again.value.loans == len(loans)
    second = _to_jsonable(env.backup.export())
    assert _exported_loans(second) == exported


def test_unknown_property_reference_rejects_whole_restore(env: Env) -> None:
    """A loan pointing at another property id fails validation, store untouched."""
    _purge(env)
    old_prop = str(uuid.uuid4())
    assert env.backup.restore(_property_doc(old_prop, [])).is_ok
    before = _snapshot(env)

    prop_id = str(uuid.uuid4())
    loan = {
        "id": "loan-1", "property_id": "someone-else", "description": "L",
        "annual_interest_rate": "5", "monthly_payment": "1000.00",
        "anchor_balance": "100000.00", "anchor_date": "2024-01-01",
    }
    result = env.backup.restore(_property_doc(prop_id, [loan]))
    assert not result.is_ok and result.error.kind == "validation"
    assert result.error.field == "property_id"
    assert _snapshot(env) == before


# ---------------------------------------------------------------------------
# Examples: no-loans document (11.4)
# ---------------------------------------------------------------------------


def test_document_without_loans_restores_as_zero_loans(env: Env) -> None:
    """A document with no ``loans`` key restores with loan count 0 (11.4)."""
    _purge(env)
    prop_id = str(uuid.uuid4())
    result = env.backup.restore(_property_doc(prop_id, None))
    assert result.is_ok, result.error
    assert result.value.properties == 1
    assert result.value.loans == 0

    rows = env.repo.query(
        keys.property_scoped_pk(prop_id),
        sk_begins_with=keys.loan_list_prefix(),
        money_attrs=set(),
    )
    assert rows == []
    exported = _to_jsonable(env.backup.export())
    assert exported["properties"][0]["loans"] == []


# ---------------------------------------------------------------------------
# Property 21
# ---------------------------------------------------------------------------

_REQUIRED_ANCHOR_FIELDS = ("monthly_payment", "anchor_balance", "anchor_date")


@st.composite
def _invalid_loan_case(
    draw: st.DrawFn, prop_id: str
) -> tuple[dict[str, Any], str]:
    """A valid loan broken in one way; returns (loan, expected failing field)."""
    raw = draw(_raw_loan(prop_id))
    kind = draw(
        st.sampled_from(
            ["missing", "origination_shape", "override_early", "override_late"]
        )
    )
    if kind == "missing":
        field_name = draw(st.sampled_from(_REQUIRED_ANCHOR_FIELDS))
        if draw(st.booleans()):
            del raw[field_name]
        else:
            raw[field_name] = None
        return raw, field_name
    if kind == "origination_shape":
        # The discarded shape: origination fields instead of the anchor fields.
        for k in _REQUIRED_ANCHOR_FIELDS:
            raw.pop(k, None)
        raw["original_principal"] = _money(draw(st.integers(100_000, 200_000_000)))
        raw["origination_date"] = "2020-01-01"
        raw["term_months"] = 360
        return raw, "monthly_payment"  # first missing field checked
    rows, _ = compute_payment_rows(_loan_of(raw))
    anchor_year = int(raw["anchor_date"][0:4])
    generated = {int(r.date[0:4]) for r in rows}
    if kind == "override_early":
        year = draw(st.integers(0, 1899))
    else:
        year = max(generated | {anchor_year}) + draw(st.integers(1, 20))
    raw["interest_overrides"] = {str(year): _money(draw(st.integers(0, 1_000_000)))}
    return raw, f"interest_overrides.{year}"


@settings(deadline=None, max_examples=_MAX_EXAMPLES)
@given(data=st.data())
def test_invalid_loan_rejects_whole_restore(env: Env, data: st.DataObject) -> None:
    """Property 21."""
    _purge(env)
    # Pre-existing account data that a rejected restore must leave untouched.
    old_prop = str(uuid.uuid4())
    old_loans = data.draw(_loans_with_overrides(old_prop, max_size=2))
    assert env.backup.restore(_property_doc(old_prop, old_loans)).is_ok
    before = _snapshot(env)

    prop_id = str(uuid.uuid4())
    good = data.draw(_loans_with_overrides(prop_id, min_size=0, max_size=2))
    bad, expected_field = data.draw(_invalid_loan_case(prop_id))
    loans = good + [bad]
    # Position of the invalid loan must not matter.
    if data.draw(st.booleans()):
        loans.reverse()

    result = env.backup.restore(_property_doc(prop_id, loans))

    assert not result.is_ok
    assert result.error.kind == "validation"
    assert result.error.field == expected_field
    assert prop_id in result.error.message  # names the property
    assert bad["id"] in result.error.message  # names the loan
    assert _snapshot(env) == before  # nothing persisted, nothing cleared
