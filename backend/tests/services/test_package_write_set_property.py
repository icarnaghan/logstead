"""Property test for the package build write set (accountant-package task 6.5).

Feature: accountant-package, Property 13: The build writes only the ZIP and the job
**Validates: Requirements 10.7, 10.8, 15.7**
"""
from __future__ import annotations

from datetime import datetime, timezone
from decimal import Decimal

import boto3
from hypothesis import HealthCheck, given, settings
from hypothesis import strategies as st
from moto import mock_aws

from logstead.adapters.s3_files import S3FileAdapter
from logstead.models.property import PropertyInput
from logstead.models.transaction import TransactionInput
from logstead.repository import keys
from logstead.repository.dynamo_repo import DynamoRepository
from logstead.router import handler as router
from logstead.services.property import PropertyService
from logstead.services.transaction import TransactionService
from logstead.worker import package_worker

TABLE = "Logstead"
BUCKET = "logstead-files-test"
REGION = "us-east-1"
USER = "user-abc"
OTHER_USER = "user-other"
JOB_ID = "job-write-set"
YEAR = 2024


class RecordingRepo:
    """Delegates to a real repository and records every write call."""

    WRITES = {"put_item", "delete_item", "transact_write"}

    def __init__(self, inner):
        self._inner = inner
        self.writes: list[tuple[str, tuple, dict]] = []

    def __getattr__(self, name):
        attr = getattr(self._inner, name)
        if name in self.WRITES:
            def recorded(*args, **kwargs):
                self.writes.append((name, args, kwargs))
                return attr(*args, **kwargs)

            return recorded
        return attr


class RecordingFiles:
    """Delegates to a real S3 adapter and records every write call."""

    WRITES = {"put_object", "upload_file", "delete_object", "purge_if_oversized"}

    def __init__(self, inner):
        self._inner = inner
        self.writes: list[tuple[str, tuple, dict]] = []

    def __getattr__(self, name):
        attr = getattr(self._inner, name)
        if name in self.WRITES:
            def recorded(*args, **kwargs):
                self.writes.append((name, args, kwargs))
                return attr(*args, **kwargs)

            return recorded
        return attr


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


def _table_snapshot(ddb) -> dict:
    items = {}
    for page in ddb.get_paginator("scan").paginate(TableName=TABLE):
        for item in page["Items"]:
            items[(item["PK"]["S"], item["SK"]["S"])] = item
    return items


def _bucket_snapshot(s3) -> dict:
    out = {}
    for page in s3.get_paginator("list_objects_v2").paginate(Bucket=BUCKET):
        for obj in page.get("Contents", []):
            body = s3.get_object(Bucket=BUCKET, Key=obj["Key"])["Body"].read()
            out[obj["Key"]] = body
    return out


_amount = st.integers(min_value=1, max_value=999_999).map(lambda c: Decimal(c) / 100)
_receipt = st.one_of(st.none(), st.integers(min_value=0, max_value=80))


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
        "date": draw(st.sampled_from(["2023-12-31", "2024-03-01", "2024-12-31"])),
        "receipts": draw(st.lists(_receipt, max_size=2)),
    }


_properties = st.lists(st.lists(_txn_spec(), max_size=3), min_size=1, max_size=2)


@settings(
    max_examples=25,
    deadline=None,
    suppress_health_check=[HealthCheck.function_scoped_fixture, HealthCheck.too_slow],
)
@given(
    spec=_properties,
    include_missing_property=st.booleans(),
    other_user_object=st.booleans(),
)
def test_build_writes_only_zip_and_job(spec, include_missing_property, other_user_object):
    """Property 13: reads plus the job puts and exactly one ZIP object."""
    with mock_aws():
        ddb = boto3.client("dynamodb", region_name=REGION)
        _create_table(ddb)
        s3 = boto3.client("s3", region_name=REGION)
        s3.create_bucket(Bucket=BUCKET)
        raw_repo = DynamoRepository(ddb, TABLE)
        raw_files = S3FileAdapter(s3, BUCKET)
        props = PropertyService(raw_repo, USER)
        txns = TransactionService(raw_repo, raw_files)

        ids = []
        for n, txn_specs in enumerate(spec):
            created = props.create(
                PropertyInput(
                    name=f"Prop {n}", address_text="1 Main St", property_type="single_family"
                )
            )
            assert created.is_ok, created.error
            ids.append(created.value.id)
            for t in txn_specs:
                made = txns.create(
                    TransactionInput(
                        property_id=created.value.id, date=t["date"], amount=t["amount"],
                        type=t["type"], category_id=t["category"],
                        description="repair" if t["itemized"] else None,
                        itemized=t["itemized"],
                    )
                )
                assert made.is_ok, made.error
                for i, size in enumerate(t["receipts"]):
                    att = txns.attach_receipt(
                        created.value.id, made.value.id, f"r{i}.bin", "application/pdf"
                    )
                    assert att.is_ok, att.error
                    if size is not None:
                        s3.put_object(
                            Bucket=BUCKET, Key=att.value.document.s3_key,
                            Body=bytes(j % 256 for j in range(size)),
                        )
        if other_user_object:
            s3.put_object(
                Bucket=BUCKET,
                Key=f"exports/packages/{OTHER_USER}/old/package.zip",
                Body=b"other",
            )
        job_ids = ids + (["missing-property-id"] if include_missing_property else [])
        raw_repo.put_item(
            {
                "PK": keys.user_pk(USER),
                "SK": keys.package_job_sk(JOB_ID),
                "userId": USER,
                "id": JOB_ID,
                "taxYear": YEAR,
                "propertyIds": job_ids,
                "status": "queued",
                "createdAt": datetime(2025, 1, 1, tzinfo=timezone.utc).isoformat(),
                "ttl": 2_000_000_000,
            }
        )

        repo = RecordingRepo(raw_repo)
        files = RecordingFiles(raw_files)
        router.configure(repo=repo, files=files)
        try:
            before_table = _table_snapshot(ddb)
            before_bucket = _bucket_snapshot(s3)
            result = package_worker.handler({"user_id": USER, "job_id": JOB_ID})
            after_table = _table_snapshot(ddb)
            after_bucket = _bucket_snapshot(s3)
        finally:
            router.reset_wiring()

        expected_status = "failed" if include_missing_property else "complete"
        assert result == {"status": expected_status}

        # Recorded writes: only puts of the one job item.
        job_sk = keys.package_job_sk(JOB_ID)
        assert repo.writes, "the job must be written"
        for name, args, _kwargs in repo.writes:
            assert name == "put_item"
            item = args[0]
            assert item["PK"] == keys.user_pk(USER)
            assert item["SK"] == job_sk

        # S3: one upload on success under the user's package prefix; none on failure.
        prefix = f"exports/packages/{USER}/{JOB_ID}/"
        if expected_status == "complete":
            assert [w[0] for w in files.writes] == ["upload_file"]
            assert files.writes[0][1][1].startswith(prefix)
        else:
            assert files.writes == []

        # Real state: only the job item differs; no receipt object removed or changed.
        changed = {k for k in set(before_table) | set(after_table) if before_table.get(k) != after_table.get(k)}
        assert changed == {(keys.user_pk(USER), job_sk)}
        for key, body in before_bucket.items():
            assert after_bucket.get(key) == body
        new_keys = set(after_bucket) - set(before_bucket)
        if expected_status == "complete":
            assert len(new_keys) == 1 and next(iter(new_keys)).startswith(prefix)
        else:
            assert new_keys == set()
