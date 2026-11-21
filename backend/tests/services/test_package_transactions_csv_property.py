"""Property test for the package transactions CSV (accountant-package task 5.3).

Feature: accountant-package, Property 11: Transactions CSV round trip

**Validates: Requirements 9.1, 9.2, 9.3, 9.4, 9.5, 9.7**
"""

from __future__ import annotations

import csv
import io
import tempfile
import zipfile
from datetime import datetime, timezone
from decimal import Decimal

import boto3
from hypothesis import HealthCheck, given, settings
from hypothesis import strategies as st
from moto import mock_aws

from logstead.adapters.s3_files import S3FileAdapter
from logstead.models.property import PropertyInput
from logstead.models.transaction import TransactionInput
from logstead.repository.dynamo_repo import DynamoRepository
from logstead.services.accountant_package import TRANSACTION_COLUMNS, PackageBuilder
from logstead.services.category import CATEGORY_CATALOG
from logstead.services.depreciation import DepreciationService
from logstead.services.itemized import ItemizedExpenseService
from logstead.services.property import PropertyService
from logstead.services.report import ReportingService
from logstead.services.transaction import TransactionService

TABLE = "Logstead"
BUCKET = "logstead-files-test"
REGION = "us-east-1"
USER = "user-abc"
YEAR = 2024
LABELS = {c.id: c.label for c in CATEGORY_CATALOG}


def _create_table(ddb) -> None:
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


def _neutral(text: str) -> str:
    """The expected cell for already-trimmed stored text."""
    return "'" + text if text[:1] in ("=", "+", "-", "@", "\t", "\r") else text


# Commas, quotes, newlines, formula leaders, and non-ASCII; no control chars
# or surrogates that DynamoDB or the CSV dialect would not carry.
_text = st.text(
    alphabet=st.one_of(
        st.characters(blacklist_categories=("Cs", "Cc")),
        st.sampled_from(list(',"\n\r=+-@ ')),
    ),
    min_size=1,
    max_size=40,
).filter(lambda s: s.strip() != "")

_amount = st.integers(min_value=1, max_value=9_999_999).map(
    lambda cents: Decimal(cents) / Decimal(100)
)
_date = st.sampled_from(
    ["2023-12-31", "2024-01-01", "2024-03-15", "2024-03-16", "2024-12-31", "2025-01-01"]
)


@st.composite
def _txn_spec(draw):
    kind = draw(st.sampled_from(["income", "expense", "itemized"]))
    spec = {
        "date": draw(_date),
        "amount": draw(_amount),
        "imported": draw(st.booleans()),
        "receipts": draw(st.integers(min_value=0, max_value=2)),
    }
    if kind == "income":
        spec.update(type="income", category="rents-received", itemized=False)
        spec["description"] = draw(st.one_of(st.none(), _text))
        spec["notes"] = None
    elif kind == "expense":
        spec.update(type="expense", category="insurance", itemized=False)
        spec["description"] = draw(st.one_of(st.none(), _text))
        spec["notes"] = None
    else:
        spec.update(type="expense", category="repairs", itemized=True)
        spec["description"] = draw(_text.filter(lambda s: len(s.strip()) <= 200))
        spec["notes"] = draw(st.one_of(st.none(), _text))
    return spec


_properties = st.lists(
    st.tuples(_text.filter(lambda s: len(s.strip()) <= 60), st.lists(_txn_spec(), max_size=4)),
    min_size=1,
    max_size=3,
)


@settings(
    max_examples=100,
    deadline=None,
    suppress_health_check=[HealthCheck.function_scoped_fixture, HealthCheck.too_slow],
)
@given(spec=_properties)
def test_transactions_csv_round_trip(spec):
    with mock_aws(), tempfile.TemporaryDirectory() as tmp:
        ddb = boto3.client("dynamodb", region_name=REGION)
        _create_table(ddb)
        s3 = boto3.client("s3", region_name=REGION)
        s3.create_bucket(Bucket=BUCKET)
        repo = DynamoRepository(ddb, TABLE)
        files = S3FileAdapter(s3, BUCKET)
        props = PropertyService(repo, USER)
        txns = TransactionService(repo, files)
        reports = ReportingService(txns, DepreciationService(repo), props, files)
        builder = PackageBuilder(
            reports,
            ItemizedExpenseService(txns),
            txns,
            props,
            files,
            None,
            lambda: datetime(2025, 1, 15, 14, 3, 22, tzinfo=timezone.utc),
        )

        # expected: txn id -> expected row fields (before ordering)
        expected: dict[str, dict] = {}
        property_ids = []
        for name, txn_specs in spec:
            created = props.create(
                PropertyInput(name=name, address_text="1 Main St", property_type="single_family")
            )
            assert created.is_ok, created.error
            prop = created.value
            property_ids.append(prop.id)
            for t in txn_specs:
                made = txns.create(
                    TransactionInput(
                        property_id=prop.id,
                        date=t["date"],
                        amount=t["amount"],
                        type=t["type"],
                        category_id=t["category"],
                        description=t["description"],
                        imported=t["imported"],
                        itemized=t["itemized"],
                        notes=t["notes"],
                    )
                )
                assert made.is_ok, made.error
                txn = made.value
                for i in range(t["receipts"]):
                    att = txns.attach_receipt(prop.id, txn.id, f"r{i}.pdf", "application/pdf")
                    assert att.is_ok, att.error
                    s3.put_object(Bucket=BUCKET, Key=att.value.document.s3_key, Body=b"x")
                if not txn.date.startswith(str(YEAR)):
                    continue
                expected[txn.id] = {
                    "property": prop.name,
                    "date": txn.date,
                    "txn": txn,
                    "receipts": t["receipts"],
                }

        zip_path = f"{tmp}/pkg.zip"
        builder.build(YEAR, property_ids, zip_path)
        with zipfile.ZipFile(zip_path) as zf:
            raw = zf.read(f"transactions/transactions-{YEAR}.csv").decode("utf-8")
            names = set(zf.namelist())
        reader = csv.reader(io.StringIO(raw, newline=""))
        header = next(reader)
        rows = [dict(zip(header, r)) for r in reader]

        assert tuple(header) == TRANSACTION_COLUMNS
        # One row per in-year transaction, in (property, date, id) order.
        assert [r["transaction_id"] for r in rows] == [
            tid
            for tid, _ in sorted(
                expected.items(),
                key=lambda kv: (kv[1]["property"], kv[1]["date"], kv[0]),
            )
        ]
        for row in rows:
            exp = expected[row["transaction_id"]]
            txn = exp["txn"]
            assert row["property"] == _neutral(exp["property"])
            assert row["date"] == txn.date
            assert row["type"] == txn.type
            assert row["category"] == _neutral(LABELS[txn.category_id])
            assert row["schedule_e_line"] == str(txn.schedule_e_line)
            assert row["amount"] == f"{txn.amount:.2f}"
            assert row["description"] == _neutral(txn.description or "")
            assert row["notes"] == _neutral(txn.notes or "")
            assert row["imported"] == ("true" if txn.imported else "false")
            assert row["itemized"] == ("true" if txn.itemized else "false")
            assert row["document_count"] == str(exp["receipts"])
            paths = [p for p in row["document_paths"].split(";") if p]
            assert len(paths) == exp["receipts"]
            assert len(set(paths)) == len(paths)
            assert all(p in names for p in paths)
