"""Integration tests for S3 file operations (Task 9.4, Requirements 4.1, 4.3, 4.4).

These are **integration** tests: they exercise the S3 file adapter and the Photo
Service against a real ``moto``-backed S3 bucket (and, where the Photo Service is
involved, a real ``moto``-backed DynamoDB table), and they drive the pre-signed
URLs the way a browser would — with an actual HTTP client — so the full
issue-then-use round-trip is verified, not just the shape of the signed URL.

They are distinct from, and complement:

* ``tests/adapters/test_s3_files.py`` — unit tests asserting URL *structure*
  (bucket/key present) and key-prefix construction, and object delete;
* ``tests/services/test_photo.py`` — Photo Service unit tests for the allow-list
  and the metadata lifecycle;
* the Property 6 allow-list property-based test (task 9.3).

What these integration tests add on top of the above:

* **Pre-signed PUT issuance is usable end to end** — an object PUT through the
  issued URL actually lands in the bucket at the right key (Requirement 4.1).
* **Pre-signed GET issuance is usable end to end** — the object's bytes are
  retrievable through the issued download URL (Requirements 4.1, 4.3).
* **Cross-store deletion** — deleting through the Photo Service removes **both**
  the S3 object and the DynamoDB metadata item, and the object delete is
  idempotent (Requirement 4.4).
* **Prefix/key correctness across all four categories** — photos, receipts,
  imports, exports each land under their own prefix and round-trip through S3.

moto's ``generate_presigned_url`` produces URLs that its in-memory S3 backend
accepts over HTTP, so a ``requests`` round-trip against them is genuine within
the mock.
"""

from __future__ import annotations

import boto3
import pytest
import requests
from moto import mock_aws

from logstead.adapters.s3_files import (
    S3FileAdapter,
    export_key,
    import_key,
    photo_key,
    receipt_key,
)
from logstead.repository import keys
from logstead.repository.dynamo_repo import DynamoRepository
from logstead.services.photo import PhotoService

TABLE_NAME = "Logstead"
BUCKET = "logstead-files-test"
REGION = "us-east-1"
PROPERTY_ID = "prop-1"


@pytest.fixture
def aws():
    """A moto context with the DynamoDB table and S3 bucket pre-created."""
    with mock_aws():
        ddb = boto3.client("dynamodb", region_name=REGION)
        ddb.create_table(
            TableName=TABLE_NAME,
            AttributeDefinitions=[
                {"AttributeName": "PK", "AttributeType": "S"},
                {"AttributeName": "SK", "AttributeType": "S"},
            ],
            KeySchema=[
                {"AttributeName": "PK", "KeyType": "HASH"},
                {"AttributeName": "SK", "KeyType": "RANGE"},
            ],
            BillingMode="PAY_PER_REQUEST",
        )
        s3 = boto3.client("s3", region_name=REGION)
        s3.create_bucket(Bucket=BUCKET)
        yield ddb, s3


@pytest.fixture
def s3_client(aws):
    _, s3 = aws
    return s3


@pytest.fixture
def adapter(s3_client):
    return S3FileAdapter(s3_client, BUCKET)


@pytest.fixture
def repo(aws):
    ddb, _ = aws
    return DynamoRepository(ddb, TABLE_NAME)


@pytest.fixture
def service(repo, adapter):
    return PhotoService(repo, adapter)


def _object_keys(s3_client) -> set[str]:
    """Every object key currently in the bucket."""
    listed = s3_client.list_objects_v2(Bucket=BUCKET)
    return {obj["Key"] for obj in listed.get("Contents", [])}


# --- Pre-signed PUT issuance: usable upload round-trip (Requirement 4.1) -----


def test_presigned_put_url_uploads_object_to_right_bucket_and_key(adapter, s3_client):
    """A PUT through the issued URL lands the bytes at the exact bucket+key."""
    key = photo_key(PROPERTY_ID, "front.jpg")
    body = b"\xff\xd8\xff\xe0 pretend-jpeg-bytes"

    url = adapter.presigned_put_url(key, "image/jpeg")
    resp = requests.put(url, data=body, headers={"Content-Type": "image/jpeg"})
    assert resp.status_code == 200

    # The object actually landed in the bucket at the signed key.
    assert key in _object_keys(s3_client)
    stored = s3_client.get_object(Bucket=BUCKET, Key=key)
    assert stored["Body"].read() == body


def test_presigned_put_url_targets_the_adapter_bucket(adapter):
    """The signed URL host/path references the adapter's bucket and key."""
    key = photo_key(PROPERTY_ID, "front.jpg")
    url = adapter.presigned_put_url(key, "image/jpeg")

    assert url.startswith("https://")
    assert BUCKET in url
    assert "front.jpg" in url


# --- Pre-signed GET issuance: usable download round-trip (Req 4.1, 4.3) ------


def test_presigned_get_url_downloads_existing_object(adapter, s3_client):
    """A GET through the issued URL returns the stored object's bytes."""
    key = photo_key(PROPERTY_ID, "back.png")
    body = b"\x89PNG pretend-png-bytes"
    s3_client.put_object(Bucket=BUCKET, Key=key, Body=body, ContentType="image/png")

    url = adapter.presigned_get_url(key)
    resp = requests.get(url)

    assert resp.status_code == 200
    assert resp.content == body


def test_presigned_put_then_get_round_trip(adapter):
    """Issue PUT, upload, then issue GET and read the same bytes back."""
    key = photo_key(PROPERTY_ID, "roundtrip.jpg")
    body = b"round-trip-payload"

    put_url = adapter.presigned_put_url(key, "image/jpeg")
    put_resp = requests.put(put_url, data=body, headers={"Content-Type": "image/jpeg"})
    assert put_resp.status_code == 200

    get_url = adapter.presigned_get_url(key)
    get_resp = requests.get(get_url)
    assert get_resp.status_code == 200
    assert get_resp.content == body


# --- Prefix/key correctness across all four categories -----------------------


@pytest.mark.parametrize(
    ("key", "prefix"),
    [
        (photo_key(PROPERTY_ID, "pic.jpg"), "photos/"),
        (receipt_key("txn-9", "receipt.pdf"), "receipts/"),
        (import_key("session-2", "summary.pdf"), "imports/"),
        (export_key("2024", "report.csv"), "exports/"),
    ],
)
def test_each_category_prefix_round_trips_through_s3(adapter, s3_client, key, prefix):
    """Objects for each file category upload/download under their own prefix."""
    assert key.startswith(prefix)
    body = f"payload-for-{prefix}".encode()
    content_type = "application/octet-stream"

    put_url = adapter.presigned_put_url(key, content_type)
    # The content type is bound into the signature, so the upload must declare
    # the same type it was authorized for.
    put_resp = requests.put(put_url, data=body, headers={"Content-Type": content_type})
    assert put_resp.status_code == 200
    assert key in _object_keys(s3_client)

    get_url = adapter.presigned_get_url(key)
    get_resp = requests.get(get_url)
    assert get_resp.status_code == 200
    assert get_resp.content == body


def test_distinct_category_keys_do_not_collide(s3_client, adapter):
    """The four category keys occupy four distinct objects in the bucket."""
    category_keys = [
        photo_key(PROPERTY_ID, "same.bin"),
        receipt_key("same", "same.bin"),
        import_key("same", "same.bin"),
        export_key("same", "same.bin"),
    ]
    for key in category_keys:
        s3_client.put_object(Bucket=BUCKET, Key=key, Body=b"x")

    assert _object_keys(s3_client) == set(category_keys)
    assert len(set(category_keys)) == 4


# --- Cross-store deletion via the Photo Service (Requirement 4.4) ------------


def test_photo_service_delete_removes_object_and_metadata(service, repo, s3_client):
    """Deleting through the service clears BOTH S3 and DynamoDB (integration)."""
    # Request an upload (writes metadata + issues a PUT URL), then actually
    # upload the object through that URL so both stores hold state.
    upload = service.request_upload(PROPERTY_ID, "front.jpg", "image/jpeg").value
    put_resp = requests.put(
        upload.upload_url,
        data=b"pretend-jpeg",
        headers={"Content-Type": "image/jpeg"},
    )
    assert put_resp.status_code == 200

    pk = keys.property_scoped_pk(PROPERTY_ID)
    sk = keys.photo_sk(upload.photo.id)
    # Preconditions: object in S3 and metadata in DynamoDB.
    assert upload.photo.s3_key in _object_keys(s3_client)
    assert repo.get_item(pk, sk) is not None

    deleted = service.delete_photo(PROPERTY_ID, upload.photo.id)
    assert deleted.is_ok

    # Both stores are now clear of the photo.
    assert upload.photo.s3_key not in _object_keys(s3_client)
    assert repo.get_item(pk, sk) is None
    assert service.list_photos(PROPERTY_ID).value == []


def test_photo_service_delete_is_idempotent_when_object_never_uploaded(
    service, repo, s3_client
):
    """Metadata written but object never PUT: delete still succeeds (idempotent)."""
    upload = service.request_upload(PROPERTY_ID, "front.jpg", "image/jpeg").value
    # The browser never completed the PUT, so no S3 object exists.
    assert upload.photo.s3_key not in _object_keys(s3_client)

    deleted = service.delete_photo(PROPERTY_ID, upload.photo.id)
    assert deleted.is_ok
    assert (
        repo.get_item(
            keys.property_scoped_pk(PROPERTY_ID), keys.photo_sk(upload.photo.id)
        )
        is None
    )


def test_adapter_delete_object_is_idempotent_over_http_uploaded_object(
    adapter, s3_client
):
    """Delete removes an uploaded object and a repeat delete is a no-op."""
    key = photo_key(PROPERTY_ID, "front.jpg")
    put_url = adapter.presigned_put_url(key, "image/jpeg")
    requests.put(put_url, data=b"bytes", headers={"Content-Type": "image/jpeg"})
    assert key in _object_keys(s3_client)

    adapter.delete_object(key)
    assert key not in _object_keys(s3_client)

    # Deleting again must not raise (S3 delete is idempotent).
    adapter.delete_object(key)
    assert key not in _object_keys(s3_client)
