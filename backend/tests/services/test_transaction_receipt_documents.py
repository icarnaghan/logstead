"""Example tests for ``TransactionService.receipt_documents`` (Requirements 10.1, 10.7)."""
from __future__ import annotations

from decimal import Decimal

import boto3
import pytest
from moto import mock_aws

from logstead.adapters.s3_files import S3FileAdapter
from logstead.models.transaction import TransactionInput
from logstead.repository.dynamo_repo import DynamoRepository
from logstead.services.transaction import TransactionService

TABLE_NAME = "Logstead"
BUCKET = "logstead-files-test"
REGION = "us-east-1"
PROPERTY_ID = "prop-1"


class _RecordingFiles(S3FileAdapter):
    """Real adapter that records every call made through it."""

    def __init__(self, *args, **kwargs):
        super().__init__(*args, **kwargs)
        self.calls: list[str] = []

    def presigned_get_url(self, *a, **k):
        self.calls.append("presigned_get_url")
        return super().presigned_get_url(*a, **k)

    def purge_if_oversized(self, *a, **k):
        self.calls.append("purge_if_oversized")
        return super().purge_if_oversized(*a, **k)

    def object_size(self, *a, **k):
        self.calls.append("object_size")
        return super().object_size(*a, **k)

    def delete_object(self, *a, **k):
        self.calls.append("delete_object")
        return super().delete_object(*a, **k)

    def put_object(self, *a, **k):
        self.calls.append("put_object")
        return super().put_object(*a, **k)

    def open_stream(self, *a, **k):
        self.calls.append("open_stream")
        return super().open_stream(*a, **k)


@pytest.fixture
def env():
    with mock_aws():
        ddb = boto3.client("dynamodb", region_name=REGION)
        ddb.create_table(
            TableName=TABLE_NAME,
            AttributeDefinitions=[
                {"AttributeName": "PK", "AttributeType": "S"},
                {"AttributeName": "SK", "AttributeType": "S"},
                {"AttributeName": "GSI2PK", "AttributeType": "S"},
                {"AttributeName": "GSI2SK", "AttributeType": "S"},
            ],
            KeySchema=[
                {"AttributeName": "PK", "KeyType": "HASH"},
                {"AttributeName": "SK", "KeyType": "RANGE"},
            ],
            GlobalSecondaryIndexes=[
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
        s3 = boto3.client("s3", region_name=REGION)
        s3.create_bucket(Bucket=BUCKET)
        repo = DynamoRepository(ddb, TABLE_NAME)
        files = _RecordingFiles(s3, BUCKET)
        yield TransactionService(repo, files), files, s3


def _income(date_str: str) -> TransactionInput:
    return TransactionInput(
        property_id=PROPERTY_ID,
        date=date_str,
        amount=Decimal("100.00"),
        type="income",
        category_id="rents-received",
        description=None,
    )


def test_receipt_documents_returns_rows_without_touching_s3(env):
    service, files, s3 = env
    txn = service.create(_income("2024-03-07")).value
    a = service.attach_receipt(PROPERTY_ID, txn.id, "a.pdf", "application/pdf").value
    b = service.attach_receipt(PROPERTY_ID, txn.id, "b.pdf", "application/pdf").value
    # Object deliberately absent from S3: the read must not care.
    files.calls.clear()

    docs = service.receipt_documents(PROPERTY_ID, txn)

    assert {d.id for d in docs} == {a.document.id, b.document.id}
    assert {d.s3_key for d in docs} == {a.document.s3_key, b.document.s3_key}
    assert files.calls == []
    assert s3.list_objects_v2(Bucket=BUCKET).get("Contents", []) == []


def test_receipt_documents_excludes_other_transactions_receipts(env):
    service, _files, _s3 = env
    first = service.create(_income("2024-03-07")).value
    second = service.create(_income("2024-03-07")).value
    mine = service.attach_receipt(
        PROPERTY_ID, first.id, "mine.pdf", "application/pdf"
    ).value
    service.attach_receipt(PROPERTY_ID, second.id, "other.pdf", "application/pdf")

    docs = service.receipt_documents(PROPERTY_ID, first)

    assert [d.id for d in docs] == [mine.document.id]


def test_receipt_documents_empty_when_no_receipts(env):
    service, _files, _s3 = env
    txn = service.create(_income("2024-03-07")).value
    assert service.receipt_documents(PROPERTY_ID, txn) == []
