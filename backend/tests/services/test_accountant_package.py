"""Example tests for PackageBuilder (accountant-package task 5.6)."""
from __future__ import annotations

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
from logstead.models.result import Result
from logstead.models.transaction import TransactionInput
from logstead.repository.dynamo_repo import DynamoRepository
from logstead.services import accountant_package as ap
from logstead.services import package_config
from logstead.services.accountant_package import PackageBuilder, PackageTooLarge
from logstead.services.depreciation import DepreciationService
from logstead.services.itemized import ItemizedExpenseService
from logstead.services.property import PropertyService
from logstead.services.report import ReportingService
from logstead.services.transaction import TransactionService

TABLE = "Logstead"
BUCKET = "logstead-files-test"
USER = "user-abc"
YEAR = 2024
NOW = datetime(2025, 1, 15, 14, 3, 22, tzinfo=timezone.utc)


class _RecordingStream:
    def __init__(self, data: bytes, reads: list[int]) -> None:
        self._buf = io.BytesIO(data)
        self._reads = reads

    def read(self, n: int = -1) -> bytes:
        self._reads.append(n)
        return self._buf.read(n)

    def close(self) -> None:
        pass


class _SpyFiles:
    """Delegates to the real adapter; records stream reads."""

    def __init__(self, inner: S3FileAdapter) -> None:
        self._inner = inner
        self.reads: list[int] = []
        self.record = False

    def open_stream(self, key):
        opened = self._inner.open_stream(key)
        if opened is None or not self.record:
            return opened
        body, length = opened
        data = body.read()
        return _RecordingStream(data, self.reads), length

    def __getattr__(self, name):
        return getattr(self._inner, name)


class _Provider:
    def __init__(self, result=None, exc=None) -> None:
        self._result, self._exc = result, exc

    def checklist_for(self, property_id, tax_year):
        if self._exc:
            raise self._exc
        return self._result


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
        spy = _SpyFiles(files)
        props = PropertyService(repo, USER)
        txns = TransactionService(repo, files)
        reports = ReportingService(txns, DepreciationService(repo), props, files)

        def make(checklist=None):
            return PackageBuilder(
                reports, ItemizedExpenseService(txns), txns, props, spy, checklist,
                lambda: NOW,
            )

        yield make, props, txns, s3, spy, tmp_path


def _prop(props, name="Oak Street"):
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


def _receipt(txns, s3, pid, txn, name, body: bytes | None):
    doc = txns.attach_receipt(pid, txn.id, name, "application/pdf").value.document
    if body is not None:
        s3.put_object(Bucket=BUCKET, Key=doc.s3_key, Body=body)
    return doc


def _keys(s3):
    resp = s3.list_objects_v2(Bucket=BUCKET)
    return {o["Key"] for o in resp.get("Contents", [])}


def _one(env_):
    make, props, txns, s3, spy, tmp = env_
    pid = _prop(props)
    _txn(txns, pid, "2024-02-01", "1200.00", "income", "rents-received")
    t = _txn(txns, pid, "2024-03-05", "200.00", "expense", "repairs", "roof")
    return pid, t


def test_single_property_entry_set(env):
    make, props, txns, s3, spy, tmp = env
    pid, _ = _one(env)
    path = str(tmp / "o.zip")
    result = make().build(YEAR, [pid], path)
    with zipfile.ZipFile(path) as zf:
        names = zf.namelist()
    assert names[-1] == "manifest.json"
    assert set(names) == {
        "README.txt",
        "reports/schedule-e-oak-street-2024.csv",
        "reports/schedule-e-oak-street-2024.json",
        "reports/schedule-e-oak-street-2024.pdf",
        "transactions/transactions-2024.csv",
        "manifest.json",
    }
    assert not any("combined" in n for n in names)
    assert result.file_count == len(names) - 1


def test_several_properties_add_combined(env):
    make, props, txns, s3, spy, tmp = env
    a = _prop(props, "Alpha")
    b = _prop(props, "Beta")
    path = str(tmp / "o.zip")
    make().build(YEAR, [a, b], path)
    with zipfile.ZipFile(path) as zf:
        names = set(zf.namelist())
    for ext in ("pdf", "csv", "json"):
        assert f"reports/schedule-e-alpha-2024.{ext}" in names
        assert f"reports/schedule-e-beta-2024.{ext}" in names
        assert f"reports/schedule-e-combined-2024.{ext}" in names


def test_receipt_layout_missing_and_oversized(env, monkeypatch):
    make, props, txns, s3, spy, tmp = env
    pid, t = _one(env)
    ok = _receipt(txns, s3, pid, t, "roof.pdf", b"%PDF-ok")
    gone = _receipt(txns, s3, pid, t, "gone.pdf", None)
    big = _receipt(txns, s3, pid, t, "big.pdf", b"x" * 50)
    monkeypatch.setattr(ap, "MAX_DOCUMENT_BYTES", 20)
    path = str(tmp / "o.zip")
    result = make().build(YEAR, [pid], path)
    with zipfile.ZipFile(path) as zf:
        receipts = [n for n in zf.namelist() if n.startswith("receipts/")]
        assert receipts == [f"receipts/oak-street/repairs/2024-03-05_{t.id[:8]}_roof.pdf"]
        assert zf.read(receipts[0]) == b"%PDF-ok"
        manifest = json.loads(zf.read("manifest.json"))
    skipped = {s["document_id"]: s for s in manifest["receipts_skipped"]}
    assert skipped[gone.id]["reason"] == "missing"
    assert skipped[big.id]["reason"] == "oversized"
    assert skipped[big.id]["original_filename"] == "big.pdf"
    assert skipped[big.id]["transaction_id"] == t.id
    assert (result.receipt_count, result.skipped_receipt_count) == (1, 2)
    assert ok.id not in skipped


def test_receipt_count_limit_fails_and_leaves_no_object(env, monkeypatch):
    make, props, txns, s3, spy, tmp = env
    pid, t = _one(env)
    for i in range(3):
        _receipt(txns, s3, pid, t, f"r{i}.pdf", b"x")
    before = _keys(s3)
    monkeypatch.setattr(package_config, "PACKAGE_MAX_RECEIPTS", 2)
    with pytest.raises(PackageTooLarge) as exc:
        make().build(YEAR, [pid], str(tmp / "o.zip"))
    assert "2" in str(exc.value) and "fewer properties" in str(exc.value)
    assert _keys(s3) == before


def test_size_limit_fails_and_leaves_no_object(env, monkeypatch):
    make, props, txns, s3, spy, tmp = env
    pid, t = _one(env)
    _receipt(txns, s3, pid, t, "r.pdf", b"x" * 1000)
    before = _keys(s3)
    monkeypatch.setattr(package_config, "PACKAGE_MAX_BYTES", 500)
    with pytest.raises(PackageTooLarge) as exc:
        make().build(YEAR, [pid], str(tmp / "o.zip"))
    assert "fewer properties" in str(exc.value)
    assert _keys(s3) == before


def _manifest_checklist(env_, provider):
    make, props, txns, s3, spy, tmp = env_
    pid, _ = _one(env_)
    path = str(tmp / "o.zip")
    make(provider).build(YEAR, [pid], path)
    with zipfile.ZipFile(path) as zf:
        return json.loads(zf.read("manifest.json")), zf.namelist()


def test_checklist_absent(env):
    manifest, names = _manifest_checklist(env, None)
    assert manifest["sections"]["checklist"] == {
        "included": False, "reason": "not available in this release",
    }
    assert not any(n.startswith("checklist/") for n in names)


def test_checklist_failing_result_and_raising(env):
    failure = Result.failure("unavailable", "boom")
    manifest, names = _manifest_checklist(env, _Provider(result=failure))
    assert manifest["sections"]["checklist"]["reason"] == "could not be generated"
    assert not any(n.startswith("checklist/") for n in names)


def test_checklist_raising_provider(env):
    manifest, names = _manifest_checklist(env, _Provider(exc=RuntimeError("x")))
    assert manifest["sections"]["checklist"]["reason"] == "could not be generated"
    assert not any(n.startswith("checklist/") for n in names)


def test_checklist_present(env):
    manifest, names = _manifest_checklist(
        env, _Provider(result=Result.success({"items": [{"amount": Decimal("1.5")}]}))
    )
    assert manifest["sections"]["checklist"]["included"] is True
    assert "checklist/year-end-checklist-2024.json" in names
    kinds = {f["path"]: f["kind"] for f in manifest["files"]}
    assert kinds["checklist/year-end-checklist-2024.json"] == "checklist"


def test_fixed_clock_gives_identical_output(env):
    make, props, txns, s3, spy, tmp = env
    pid, t = _one(env)
    _receipt(txns, s3, pid, t, "r.pdf", b"abc")
    p1, p2 = str(tmp / "a.zip"), str(tmp / "b.zip")
    r1 = make().build(YEAR, [pid], p1)
    r2 = make().build(YEAR, [pid], p2)
    assert open(p1, "rb").read() == open(p2, "rb").read()
    assert r1 == r2
    with zipfile.ZipFile(p1) as zf:
        assert json.loads(zf.read("manifest.json"))["generated_at"] == "2025-01-15T14:03:22+00:00"
        assert {i.date_time for i in zf.infolist()} == {(2025, 1, 15, 14, 3, 22)}


def test_entry_order_and_compression(env):
    make, props, txns, s3, spy, tmp = env
    pid, t = _one(env)
    _receipt(txns, s3, pid, t, "r.pdf", b"abc")
    path = str(tmp / "o.zip")
    make().build(YEAR, [pid], path)
    with zipfile.ZipFile(path) as zf:
        infos = zf.infolist()
    body = [i.filename for i in infos[:-1]]
    assert body == sorted(body)
    assert infos[-1].filename == "manifest.json"
    for i in infos:
        expected = zipfile.ZIP_STORED if i.filename.startswith("receipts/") else zipfile.ZIP_DEFLATED
        assert i.compress_type == expected, i.filename


def test_receipt_is_copied_in_chunks(env, monkeypatch):
    make, props, txns, s3, spy, tmp = env
    pid, t = _one(env)
    _receipt(txns, s3, pid, t, "r.pdf", b"y" * 25)
    monkeypatch.setattr(package_config, "COPY_CHUNK_BYTES", 10)
    spy.record = True
    path = str(tmp / "o.zip")
    make().build(YEAR, [pid], path)
    assert spy.reads == [10, 10, 10, 10]  # 25 bytes: 10, 10, 5, then EOF
    with zipfile.ZipFile(path) as zf:
        name = next(n for n in zf.namelist() if n.startswith("receipts/"))
        assert zf.read(name) == b"y" * 25


def test_readme_text(env):
    make, props, txns, s3, spy, tmp = env
    pid, _ = _one(env)
    path = str(tmp / "o.zip")
    make().build(YEAR, [pid], path)
    with zipfile.ZipFile(path) as zf:
        readme = zf.read("README.txt").decode()
    assert "tax year 2024" in readme
    assert "2025-01-15T14:03:22+00:00" in readme
    assert ap.DISCLAIMER in readme
    assert "not tax advice" in readme
    assert "shasum -a 256" in readme
    assert "can differ from a report line" in readme
    assert "entered-total and loan-interest rules" in readme


def test_build_writes_nothing_to_s3_or_combined_prefix(env):
    make, props, txns, s3, spy, tmp = env
    a = _prop(props, "Alpha")
    b = _prop(props, "Beta")
    t = _txn(txns, a, "2024-03-05", "200.00", "expense", "repairs", "roof")
    _receipt(txns, s3, a, t, "r.pdf", b"abc")
    before = _keys(s3)
    make().build(YEAR, [a, b], str(tmp / "o.zip"))
    after = _keys(s3)
    assert after == before
    assert not any(k.startswith("exports/") for k in after)
