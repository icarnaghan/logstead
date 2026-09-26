"""Unit tests for the S3 file adapter (Requirements 4.1, 5.8).

Exercises pre-signed PUT/GET URL issuance and object delete against a
``moto``-backed S3 bucket so no live AWS call is ever made. moto supports
``generate_presigned_url`` and object put/get/delete, which is all this adapter
needs.
"""

from __future__ import annotations

import boto3
import pytest
from moto import mock_aws

from logstead.adapters.s3_files import (
    S3FileAdapter,
    build_key,
    export_key,
    import_key,
    photo_key,
    receipt_key,
)

BUCKET = "logstead-files-test"
REGION = "us-east-1"


@pytest.fixture
def s3_client():
    """A moto-backed S3 client with the bucket pre-created."""
    with mock_aws():
        client = boto3.client("s3", region_name=REGION)
        client.create_bucket(Bucket=BUCKET)
        yield client


@pytest.fixture
def adapter(s3_client):
    return S3FileAdapter(s3_client, BUCKET)


# --- Key building -----------------------------------------------------------


def test_build_key_joins_and_trims_segments():
    assert build_key("photos", " abc ", "/pic.jpg/") == "photos/abc/pic.jpg"


def test_build_key_drops_empty_segments():
    assert build_key("photos", "", "  ", "file.png") == "photos/file.png"


def test_build_key_rejects_all_empty():
    with pytest.raises(ValueError):
        build_key("", "  ", "/")


def test_prefix_helpers_use_expected_prefixes():
    assert photo_key("prop-1", "front.jpg") == "photos/prop-1/front.jpg"
    assert receipt_key("txn-9", "receipt.pdf") == "receipts/txn-9/receipt.pdf"
    assert import_key("session-2", "summary.pdf") == "imports/session-2/summary.pdf"
    assert export_key("2024", "report.csv") == "exports/2024/report.csv"


# --- Pre-signed URL issuance ------------------------------------------------


def test_presigned_put_url_targets_bucket_and_key(adapter):
    key = photo_key("prop-1", "front.jpg")
    url = adapter.presigned_put_url(key, "image/jpeg")

    assert isinstance(url, str)
    assert url.startswith("https://")
    assert BUCKET in url
    assert "front.jpg" in url


def test_presigned_get_url_targets_bucket_and_key(adapter):
    key = receipt_key("txn-9", "receipt.pdf")
    url = adapter.presigned_get_url(key)

    assert url.startswith("https://")
    assert BUCKET in url
    assert "receipt.pdf" in url


def test_presigned_get_and_put_urls_differ(adapter):
    key = photo_key("prop-1", "front.jpg")
    put_url = adapter.presigned_put_url(key, "image/jpeg")
    get_url = adapter.presigned_get_url(key)

    assert put_url != get_url


# --- Object delete ----------------------------------------------------------


def test_delete_removes_object(adapter, s3_client):
    key = photo_key("prop-1", "front.jpg")
    s3_client.put_object(Bucket=BUCKET, Key=key, Body=b"bytes", ContentType="image/jpeg")

    # Sanity: the object exists before delete.
    listed = s3_client.list_objects_v2(Bucket=BUCKET)
    assert any(obj["Key"] == key for obj in listed.get("Contents", []))

    adapter.delete_object(key)

    listed_after = s3_client.list_objects_v2(Bucket=BUCKET)
    assert not any(obj["Key"] == key for obj in listed_after.get("Contents", []))


def test_delete_missing_object_is_idempotent(adapter):
    # Deleting a key that was never written must not raise.
    adapter.delete_object(photo_key("prop-1", "does-not-exist.jpg"))


def test_constructor_rejects_empty_bucket(s3_client):
    with pytest.raises(ValueError):
        S3FileAdapter(s3_client, "")
