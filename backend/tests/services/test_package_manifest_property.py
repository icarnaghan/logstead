"""Property tests for the package manifest and wire forms (accountant-package task 5.4).

Feature: accountant-package, Property 12: Manifest matches the ZIP
Feature: accountant-package, Property 15: Wire form of money and counts

**Validates: Requirements 12.1, 12.2, 12.3, 12.4, 12.5, 12.7, 12.8, 16.1, 9.4**
"""

from __future__ import annotations

import csv
import hashlib
import io
import json
import re
import tempfile
import zipfile
from dataclasses import dataclass
from datetime import datetime, timezone
from decimal import Decimal
from unittest import mock

import boto3
from hypothesis import HealthCheck, given, settings
from hypothesis import strategies as st
from moto import mock_aws

from logstead.adapters.s3_files import S3FileAdapter
from logstead.models.property import PropertyInput
from logstead.models.result import Result
from logstead.models.transaction import TransactionInput
from logstead.repository.dynamo_repo import DynamoRepository
from logstead.services import accountant_package as ap
from logstead.services import package_config
from logstead.services.accountant_package import PackageBuilder
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
SMALL_LIMIT = 60  # lowered per-receipt limit so "oversized" is cheap to hit
MONEY = re.compile(r"^-?\d+\.\d{2}$")
DECIMAL_LIKE = re.compile(r"^-?\d+\.\d+$")
KINDS = {
    "report_pdf", "report_csv", "report_json", "transactions_csv",
    "receipt", "checklist", "readme",
}


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


@dataclass
class _Item:
    label: str
    amount: Decimal
    count: int


class _FakeChecklist:
    """Checklist provider whose result holds money and counts."""

    def checklist_for(self, property_id, tax_year):
        return Result.success(
            {"tax_year": tax_year, "items": [_Item("Insurance", Decimal("12.5"), 3)]}
        )


# --- strategies ---------------------------------------------------------------

_amount = st.integers(min_value=1, max_value=9_999_999).map(
    lambda cents: Decimal(cents) / Decimal(100)
)
# size in bytes, or None for a receipt that was never uploaded (missing)
_receipt = st.one_of(st.none(), st.integers(min_value=0, max_value=140))


@st.composite
def _txn_spec(draw):
    kind = draw(st.sampled_from(["income", "expense", "itemized"]))
    category, type_ = {
        "income": ("rents-received", "income"),
        "expense": ("insurance", "expense"),
        "itemized": ("repairs", "expense"),
    }[kind]
    return {
        "type": type_,
        "category": category,
        "itemized": kind == "itemized",
        "amount": draw(_amount),
        "date": draw(st.sampled_from(["2023-12-31", "2024-01-01", "2024-07-04", "2024-12-31"])),
        "description": "repair" if kind == "itemized" else None,
        "receipts": draw(st.lists(_receipt, max_size=3)),
        "imported": draw(st.booleans()),
    }


_properties = st.lists(
    st.tuples(
        st.text(alphabet="abcdefgh XYZ-", min_size=1, max_size=12).filter(lambda s: s.strip()),
        st.lists(_txn_spec(), max_size=3),
    ),
    min_size=1,
    max_size=3,
)


def _build(spec, with_checklist, chunk, tmp):
    """Seed moto, build a real ZIP, and return what the test needs to inspect."""
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
        _FakeChecklist() if with_checklist else None,
        lambda: datetime(2025, 1, 15, 14, 3, 22, tzinfo=timezone.utc),
    )
    ids = []
    expected_skipped = set()  # (document_id, reason)
    expected_included = 0
    for name, txn_specs in spec:
        created = props.create(
            PropertyInput(name=name, address_text="1 Main St", property_type="single_family")
        )
        assert created.is_ok, created.error
        ids.append(created.value.id)
        for t in txn_specs:
            made = txns.create(
                TransactionInput(
                    property_id=created.value.id, date=t["date"], amount=t["amount"],
                    type=t["type"], category_id=t["category"], description=t["description"],
                    itemized=t["itemized"], imported=t["imported"],
                )
            )
            assert made.is_ok, made.error
            for i, size in enumerate(t["receipts"]):
                att = txns.attach_receipt(
                    created.value.id, made.value.id, f"r{i}.bin", "application/pdf"
                )
                assert att.is_ok, att.error
                doc = att.value.document
                if size is not None:
                    body = bytes((j * 7 + i) % 256 for j in range(size))
                    s3.put_object(Bucket=BUCKET, Key=doc.s3_key, Body=body)
                if not t["date"].startswith(str(YEAR)):
                    continue
                if size is None:
                    expected_skipped.add((doc.id, "missing"))
                elif size > SMALL_LIMIT:
                    expected_skipped.add((doc.id, "oversized"))
                else:
                    expected_included += 1

    zip_path = f"{tmp}/pkg.zip"
    with mock.patch.object(ap, "MAX_DOCUMENT_BYTES", SMALL_LIMIT), mock.patch.object(
        package_config, "COPY_CHUNK_BYTES", chunk
    ):
        result = builder.build(YEAR, ids, zip_path)
    # Upload the finished file the way the worker does.
    s3.upload_file(zip_path, BUCKET, "exports/package.zip")
    uploaded = s3.get_object(Bucket=BUCKET, Key="exports/package.zip")["Body"].read()
    return result, zip_path, uploaded, expected_skipped, expected_included, ids


_settings = settings(
    max_examples=50,
    deadline=None,
    suppress_health_check=[HealthCheck.function_scoped_fixture, HealthCheck.too_slow],
)


@_settings
@given(spec=_properties, with_checklist=st.booleans(), chunk=st.sampled_from([7, 64, 4096]))
def test_manifest_matches_zip(spec, with_checklist, chunk):
    """Property 12: Manifest matches the ZIP."""
    with mock_aws(), tempfile.TemporaryDirectory() as tmp:
        result, zip_path, uploaded, skipped, included, ids = _build(
            spec, with_checklist, chunk, tmp
        )
        with zipfile.ZipFile(zip_path) as zf:
            names = zf.namelist()
            assert len(names) == len(set(names))
            assert names[-1] == "manifest.json"
            manifest = json.loads(zf.read("manifest.json"))
            files = manifest["files"]

            # Entry set equals manifest files plus manifest.json.
            assert {f["path"] for f in files} | {"manifest.json"} == set(names)
            assert len(files) == len(names) - 1
            assert "manifest.json" not in {f["path"] for f in files}

            # Header fields (12.1).
            assert manifest["schema_version"] == 1
            assert manifest["app"] == "Logstead"
            assert manifest["tax_year"] == YEAR
            assert manifest["generated_at"] == "2025-01-15T14:03:22+00:00"
            assert manifest["disclaimer"] == ap.DISCLAIMER
            assert [p["property_id"] for p in manifest["properties"]] == ids

            # Checksums and sizes from the exact bytes (12.2, 12.3, 12.7).
            for f in files:
                assert set(f) == {"path", "kind", "size_bytes", "sha256"}
                assert f["kind"] in KINDS
                data = zf.read(f["path"])
                assert hashlib.sha256(data).hexdigest() == f["sha256"]
                assert re.fullmatch(r"[0-9a-f]{64}", f["sha256"])
                assert len(data) == f["size_bytes"]
            receipts = [f for f in files if f["kind"] == "receipt"]
            assert all(f["path"].startswith("receipts/") for f in receipts)

            # Skipped receipts listed exactly (12.4).
            listed = manifest["receipts_skipped"]
            assert {(s["document_id"], s["reason"]) for s in listed} == skipped
            assert len(listed) == len(skipped)
            for s in listed:
                assert set(s) == {
                    "transaction_id", "document_id", "original_filename", "reason"
                }

            # Totals equal counts and sums of the lists (12.5).
            totals = manifest["totals"]
            assert totals == {
                "files": len(files),
                "receipts_included": len(receipts),
                "receipts_skipped": len(listed),
                "bytes": sum(f["size_bytes"] for f in files),
            }
            assert len(receipts) == included

            # Checklist section matches presence of the file.
            section = manifest["sections"]["checklist"]
            has_file = any(f["kind"] == "checklist" for f in files)
            assert section["included"] is with_checklist
            assert has_file is with_checklist
            if not with_checklist:
                assert section["reason"] == ap.CHECKLIST_NOT_AVAILABLE

        # Result and job sha256 equal the uploaded object's digest (12.8).
        assert result.sha256 == hashlib.sha256(uploaded).hexdigest()
        assert result.size_bytes == len(uploaded)
        assert result.file_count == len(files)
        assert result.receipt_count == len(receipts)
        assert result.skipped_receipt_count == len(listed)


def _walk(node, path=""):
    """Yield (path, key, value) for every leaf of a JSON document."""
    if isinstance(node, dict):
        for k, v in node.items():
            yield from _walk(v, f"{path}/{k}")
            if not isinstance(v, (dict, list)):
                yield path, k, v
    elif isinstance(node, list):
        for i, v in enumerate(node):
            yield from _walk(v, f"{path}[{i}]")
            if not isinstance(v, (dict, list)):
                yield path, None, v


def _check_json_wire(doc):
    for _path, key, value in _walk(doc):
        assert not isinstance(value, float), (key, value)
        if isinstance(value, str) and DECIMAL_LIKE.match(value):
            assert MONEY.match(value), (key, value)
        if key in {"amount", "total", "entered_total", "itemized_sum", "line_total"} and (
            value is not None
        ):
            assert isinstance(value, str) and MONEY.match(value), (key, value)


@_settings
@given(spec=_properties, with_checklist=st.booleans(), chunk=st.sampled_from([7, 4096]))
def test_wire_form_of_money_and_counts(spec, with_checklist, chunk):
    """Property 15: money is a two-decimal string; counts and sizes are integers."""
    with mock_aws(), tempfile.TemporaryDirectory() as tmp:
        _result, zip_path, _up, _skipped, _included, _ids = _build(
            spec, with_checklist, chunk, tmp
        )
        with zipfile.ZipFile(zip_path) as zf:
            manifest = json.loads(zf.read("manifest.json"))
            _check_json_wire(manifest)
            for key in ("files", "receipts_included", "receipts_skipped", "bytes"):
                v = manifest["totals"][key]
                assert type(v) is int, (key, v)
            for f in manifest["files"]:
                assert type(f["size_bytes"]) is int
            assert type(manifest["tax_year"]) is int
            assert type(manifest["schema_version"]) is int

            json_names = [
                n for n in zf.namelist()
                if n.endswith(".json") and n != "manifest.json"
            ]
            assert any(n.startswith("reports/") for n in json_names)
            for n in json_names:
                _check_json_wire(json.loads(zf.read(n)))
            if with_checklist:
                check = json.loads(zf.read(f"checklist/year-end-checklist-{YEAR}.json"))
                items = check["properties"][0]["checklist"]["items"]
                assert items[0]["amount"] == "12.50"
                assert type(items[0]["count"]) is int

            rows = list(
                csv.DictReader(
                    io.StringIO(
                        zf.read(f"transactions/transactions-{YEAR}.csv").decode("utf-8"),
                        newline="",
                    )
                )
            )
            for row in rows:
                assert MONEY.match(row["amount"]), row["amount"]
                assert row["document_count"].isdigit()
