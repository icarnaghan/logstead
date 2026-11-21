"""Smoke test: PackageBuilder over moto (task 5.1)."""
from __future__ import annotations

import csv
import hashlib
import io
import json
import zipfile
from datetime import datetime, timezone
from decimal import Decimal

import boto3
import pytest
from moto import mock_aws

from logstead.adapters.s3_files import S3FileAdapter
from logstead.models.property import PropertyInput
from logstead.models.transaction import TransactionInput
from logstead.repository.dynamo_repo import DynamoRepository
from logstead.services import package_config
from logstead.services.accountant_package import (
    PackageBuilder,
    PackageTooLarge,
)
from logstead.services.depreciation import DepreciationService
from logstead.services.itemized import ItemizedExpenseService
from logstead.services.property import PropertyService
from logstead.services.report import ReportingService
from logstead.services.transaction import TransactionService

TABLE = "Logstead"
BUCKET = "logstead-files-test"
USER = "user-abc"
YEAR = 2024


@pytest.fixture
def env(tmp_path):
    with mock_aws():
        ddb = boto3.client("dynamodb", region_name="us-east-1")
        gsi = lambda n: {  # noqa: E731
            "IndexName": n,
            "KeySchema": [
                {"AttributeName": f"{n}PK", "KeyType": "HASH"},
                {"AttributeName": f"{n}SK", "KeyType": "RANGE"},
            ],
            "Projection": {"ProjectionType": "ALL"},
        }
        ddb.create_table(
            TableName=TABLE,
            AttributeDefinitions=[
                {"AttributeName": a, "AttributeType": "S"}
                for a in ("PK", "SK", "GSI1PK", "GSI1SK", "GSI2PK", "GSI2SK")
            ],
            KeySchema=[
                {"AttributeName": "PK", "KeyType": "HASH"},
                {"AttributeName": "SK", "KeyType": "RANGE"},
            ],
            GlobalSecondaryIndexes=[gsi("GSI1"), gsi("GSI2")],
            BillingMode="PAY_PER_REQUEST",
        )
        s3 = boto3.client("s3", region_name="us-east-1")
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
        yield builder, props, txns, s3, tmp_path


def _prop(props, name):
    r = props.create(PropertyInput(name=name, address_text="1 Main", property_type="single_family"))
    assert r.is_ok, r.error
    return r.value.id


def _txn(txns, pid, date, amount, type_, cat, desc=None):
    r = txns.create(
        TransactionInput(
            property_id=pid, date=date, amount=Decimal(amount), type=type_,
            category_id=cat, description=desc,
        )
    )
    assert r.is_ok, r.error
    return r.value


def _seed(props, txns, s3):
    a = _prop(props, "Oak Street")
    b = _prop(props, "Oak Street")  # duplicate name -> slug suffix
    _txn(txns, a, "2024-02-01", "1200.00", "income", "rents-received")
    t = _txn(txns, a, "2024-03-05", "=200.00".lstrip("="), "expense", "repairs", "=SUM(A1)")
    _txn(txns, b, "2024-04-01", "300.00", "income", "rents-received")
    up = txns.attach_receipt(a, t.id, "roof.pdf", "application/pdf").value
    s3.put_object(Bucket=BUCKET, Key=up.document.s3_key, Body=b"%PDF-receipt")
    gone = txns.attach_receipt(a, t.id, "gone.pdf", "application/pdf").value  # never uploaded
    return a, b, t, up, gone


def test_build_two_properties(env):
    builder, props, txns, s3, tmp = env
    a, b, t, up, gone = _seed(props, txns, s3)
    path = str(tmp / "out.zip")
    result = builder.build(YEAR, [a, b], path)

    with zipfile.ZipFile(path) as zf:
        names = zf.namelist()
        assert names[-1] == "manifest.json"
        assert names[:-1] == sorted(names[:-1])
        assert "reports/schedule-e-combined-2024.pdf" in names
        assert "transactions/transactions-2024.csv" in names
        receipts = [n for n in names if n.startswith("receipts/")]
        assert len(receipts) == 1 and receipts[0].endswith("_roof.pdf")
        assert zf.read(receipts[0]) == b"%PDF-receipt"
        manifest = json.loads(zf.read("manifest.json"))
        assert {f["path"] for f in manifest["files"]} | {"manifest.json"} == set(names)
        for f in manifest["files"]:
            data = zf.read(f["path"])
            assert hashlib.sha256(data).hexdigest() == f["sha256"]
            assert len(data) == f["size_bytes"]
        assert manifest["receipts_skipped"][0]["reason"] == "missing"
        assert manifest["sections"]["checklist"]["reason"] == "not available in this release"
        rows = list(csv.DictReader(io.StringIO(zf.read("transactions/transactions-2024.csv").decode())))
        assert len(rows) == 3
        repair = next(r for r in rows if r["category"] == "Repairs")
        assert repair["description"] == "'=SUM(A1)"
        assert repair["document_count"] == "2"
        assert repair["document_paths"] == receipts[0]
        assert "reports/schedule-e-oak-street-2024.pdf" in names
        assert any(n.startswith("reports/schedule-e-oak-street-") and n != "reports/schedule-e-oak-street-2024.pdf" for n in names)
    assert result.receipt_count == 1 and result.skipped_receipt_count == 1
    assert result.file_count == len(manifest["files"])
    assert result.sha256 == hashlib.sha256(open(path, "rb").read()).hexdigest()


def test_size_limit_fails(env, monkeypatch):
    builder, props, txns, s3, tmp = env
    a, b, *_ = _seed(props, txns, s3)
    monkeypatch.setattr(package_config, "PACKAGE_MAX_BYTES", 10)
    with pytest.raises(PackageTooLarge):
        builder.build(YEAR, [a], str(tmp / "o.zip"))
