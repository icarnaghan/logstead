"""Marker preservation on generic updates and the re-import-after-edit regression.

# Feature: itemized-expenses, Property 19: Updates preserve the stored markers and re-import never duplicates a total

Validates: Requirements 19.1, 19.2, 19.3, 19.4

* Property: for any stored transaction (an imported total or an itemized
  entry) and any generic ``TransactionService.update`` whose input carries any
  ``imported`` value, the stored ``imported`` and ``itemized`` markers are
  unchanged afterwards. After an imported total is edited, a Schedule E
  re-import leaves exactly one repairs total row, carrying the re-imported
  amount.
* Example: the regression described in the task (import, edit, re-import).
* Router: the generic create and update bodies cannot set or clear
  ``imported`` or ``itemized``.
"""

from __future__ import annotations

import json
from decimal import Decimal

import boto3
import pytest
from hypothesis import given, settings
from hypothesis import strategies as st
from moto import mock_aws

from logstead.adapters.s3_files import S3FileAdapter
from logstead.models.property import PropertyInput
from logstead.models.schedule_e_import import (
    ImportSubmission,
    LineAmountInput,
    PropertyEntryInput,
)
from logstead.models.transaction import TransactionInput
from logstead.models.user import UserContext
from logstead.repository.dynamo_repo import DynamoRepository
from logstead.router import handler as handler_module
from logstead.router.handler import handler
from logstead.services.property import PropertyService
from logstead.services.schedule_e_import import ImportService
from logstead.services.transaction import TransactionService

TABLE_NAME = "Logstead"
BUCKET = "logstead-files-test"
REGION = "us-east-1"
USER_ID = "user-sub-1"
TAX_YEAR = 2023
REPAIRS_LINE = 14


def _create_table(ddb) -> None:
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
                "IndexName": "GSI1",
                "KeySchema": [
                    {"AttributeName": "GSI1PK", "KeyType": "HASH"},
                    {"AttributeName": "GSI1SK", "KeyType": "RANGE"},
                ],
                "Projection": {"ProjectionType": "ALL"},
            },
            {
                "IndexName": "GSI2",
                "KeySchema": [
                    {"AttributeName": "GSI2PK", "KeyType": "HASH"},
                    {"AttributeName": "GSI2SK", "KeyType": "RANGE"},
                ],
                "Projection": {"ProjectionType": "ALL"},
            },
        ],
        BillingMode="PAY_PER_REQUEST",
    )


class _Env:
    def __init__(self) -> None:
        ddb = boto3.client("dynamodb", region_name=REGION)
        _create_table(ddb)
        s3 = boto3.client("s3", region_name=REGION)
        s3.create_bucket(Bucket=BUCKET)
        self.repo = DynamoRepository(ddb, TABLE_NAME)
        self.files = S3FileAdapter(s3, BUCKET)
        user = UserContext(user_id=USER_ID)
        self.txns = TransactionService(self.repo, self.files)
        self.importer = ImportService(self.repo, user, self.files)
        created = PropertyService(self.repo, user).create(
            PropertyInput(name="Cedar", address_text="500 Cedar Ave")
        )
        assert created.is_ok
        self.property_id = created.value.id

    def import_repairs(self, amount: str) -> None:
        result = self.importer.import_schedule_e(
            ImportSubmission(
                tax_year=TAX_YEAR,
                entries=[
                    PropertyEntryInput(
                        property_id=self.property_id,
                        lines=[
                            LineAmountInput(
                                schedule_e_line=REPAIRS_LINE,
                                amount=amount,
                                description=None,
                            )
                        ],
                    )
                ],
            )
        )
        assert result.is_ok

    def repairs_rows(self):
        listed = self.txns.list_for_property(self.property_id, TAX_YEAR)
        assert listed.is_ok
        return [t for t in listed.value if t.category_id == "repairs"]


def _cents(value: int) -> str:
    return f"{Decimal(value) / 100:.2f}"


_amounts = st.integers(min_value=1, max_value=9_999_999).map(_cents)
_days = st.integers(min_value=1, max_value=28)
_months = st.integers(min_value=1, max_value=12)
_descriptions = st.one_of(st.none(), st.text(alphabet="abc xyz", min_size=1, max_size=20))


@settings(deadline=None, max_examples=100)
@given(
    imported_amount=_amounts,
    edit_amount=_amounts,
    reimport_amount=_amounts,
    month=_months,
    day=_days,
    description=_descriptions,
    claimed_imported=st.booleans(),
    kind=st.sampled_from(["imported_total", "itemized_entry"]),
)
# Feature: itemized-expenses, Property 19: Updates preserve the stored markers and re-import never duplicates a total
def test_update_preserves_markers_and_reimport_never_duplicates(
    imported_amount,
    edit_amount,
    reimport_amount,
    month,
    day,
    description,
    claimed_imported,
    kind,
) -> None:
    with mock_aws():
        env = _Env()
        new_date = f"{TAX_YEAR}-{month:02d}-{day:02d}"

        if kind == "imported_total":
            env.import_repairs(imported_amount)
            (stored,) = env.repairs_rows()
            assert stored.imported is True and stored.itemized is False
            update_input = TransactionInput(
                property_id=env.property_id,
                date=new_date,
                amount=Decimal(edit_amount),
                type="expense",
                category_id="repairs",
                description=description,
                imported=claimed_imported,
            )
        else:
            created = env.txns.create(
                TransactionInput(
                    property_id=env.property_id,
                    date=f"{TAX_YEAR}-06-15",
                    amount=Decimal(imported_amount),
                    type="expense",
                    category_id="repairs",
                    description="Roof patch",
                    itemized=True,
                )
            )
            assert created.is_ok
            stored = created.value
            assert stored.imported is False and stored.itemized is True
            update_input = TransactionInput(
                property_id=env.property_id,
                date=new_date,
                amount=Decimal(edit_amount),
                type="expense",
                category_id="repairs",
                description="Roof patch edited",
                itemized=True,
                imported=claimed_imported,
            )

        updated = env.txns.update(env.property_id, stored.id, update_input)
        assert updated.is_ok, updated.error
        assert updated.value.imported is stored.imported
        assert updated.value.itemized is stored.itemized

        reread = env.txns.get(env.property_id, stored.id)
        assert reread.is_ok
        assert reread.value.imported is stored.imported
        assert reread.value.itemized is stored.itemized
        assert reread.value.amount == Decimal(edit_amount)

        env.import_repairs(reimport_amount)
        rows = env.repairs_rows()
        totals = [r for r in rows if not r.itemized]
        if kind == "imported_total":
            # The edited total was still recognised as imported and replaced.
            assert len(totals) == 1
            assert totals[0].imported is True
            assert totals[0].amount == Decimal(reimport_amount)
            assert totals[0].id != stored.id
        else:
            # The itemized entry survives and one imported total is added.
            assert len(totals) == 1
            assert totals[0].amount == Decimal(reimport_amount)
            itemized = [r for r in rows if r.itemized]
            assert [r.id for r in itemized] == [stored.id]
            assert itemized[0].amount == Decimal(edit_amount)


def test_regression_edit_imported_total_then_reimport_leaves_one_total() -> None:
    with mock_aws():
        env = _Env()
        env.import_repairs("1200.00")
        (total,) = env.repairs_rows()

        edited = env.txns.update(
            env.property_id,
            total.id,
            TransactionInput(
                property_id=env.property_id,
                date=f"{TAX_YEAR}-12-31",
                amount=Decimal("1500.00"),
                type="expense",
                category_id="repairs",
                description="Edited by hand",
                imported=False,
            ),
        )
        assert edited.is_ok
        assert edited.value.imported is True

        env.import_repairs("900.00")
        rows = env.repairs_rows()
        assert len(rows) == 1
        assert rows[0].amount == Decimal("900.00")
        assert rows[0].imported is True


# --- Router: generic bodies cannot set or clear the markers ------------------


@pytest.fixture
def wired():
    with mock_aws():
        env = _Env()
        handler_module.configure(repo=env.repo, files=env.files)
        yield env
        handler_module.reset_wiring()


def _event(method, path, body=None):
    event = {
        "requestContext": {
            "http": {"method": method, "path": path},
            "authorizer": {
                "jwt": {"claims": {"sub": USER_ID, "cognito:username": "u@example.com"}}
            },
        },
        "rawPath": path,
    }
    if body is not None:
        event["body"] = json.dumps(body)
    return event


def _body(resp):
    return json.loads(resp["body"])


def test_generic_create_body_cannot_set_markers(wired) -> None:
    base = f"/properties/{wired.property_id}/transactions"
    resp = handler(
        _event(
            "POST",
            base,
            {
                "date": f"{TAX_YEAR}-05-01",
                "amount": "50.00",
                "type": "expense",
                "category_id": "repairs",
                "description": "Faucet",
                "imported": True,
                "itemized": True,
                "notes": "sneaky",
            },
        )
    )
    assert resp["statusCode"] == 201, resp["body"]
    stored = wired.txns.get(wired.property_id, _body(resp)["id"]).value
    assert stored.imported is False
    assert stored.itemized is False
    assert stored.notes is None


def test_generic_update_body_cannot_set_or_clear_markers(wired) -> None:
    # An imported total: a body claiming imported=false / itemized=true changes nothing.
    wired.import_repairs("700.00")
    (total,) = wired.repairs_rows()
    path = f"/properties/{wired.property_id}/transactions/{total.id}"
    resp = handler(
        _event(
            "PUT",
            path,
            {
                "date": f"{TAX_YEAR}-12-31",
                "amount": "710.00",
                "type": "expense",
                "category_id": "repairs",
                "imported": False,
                "itemized": True,
            },
        )
    )
    assert resp["statusCode"] == 200, resp["body"]
    stored = wired.txns.get(wired.property_id, total.id).value
    assert stored.imported is True
    assert stored.itemized is False
    assert stored.amount == Decimal("710.00")

    # A plain row: a body claiming imported=true / itemized=true changes nothing.
    created = wired.txns.create(
        TransactionInput(
            property_id=wired.property_id,
            date=f"{TAX_YEAR}-03-03",
            amount=Decimal("20.00"),
            type="expense",
            category_id="supplies",
        )
    )
    assert created.is_ok
    resp = handler(
        _event(
            "PUT",
            f"/properties/{wired.property_id}/transactions/{created.value.id}",
            {
                "date": f"{TAX_YEAR}-03-03",
                "amount": "21.00",
                "type": "expense",
                "category_id": "supplies",
                "imported": True,
                "itemized": True,
            },
        )
    )
    assert resp["statusCode"] == 200, resp["body"]
    stored = wired.txns.get(wired.property_id, created.value.id).value
    assert stored.imported is False
    assert stored.itemized is False
