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


# --- Presigned upload audit (S8) ---------------------------------------------


@pytest.mark.parametrize(
    "raw",
    [
        "../../etc/passwd",
        "..\\..\\windows\\system32\\cmd.exe",
        "a/b/c.jpg",
        "bad\x00name\n.jpg",
        "  ..hidden  ",
        "",
        None,
        "x" * 500 + ".jpg",
        "na<me>|:*?\".pdf",
    ],
)
def test_sanitize_filename_is_safe(raw):
    from logstead.adapters.s3_files import sanitize_filename

    name = sanitize_filename(raw)
    assert name
    assert len(name) <= 100
    assert "/" not in name and "\\" not in name
    assert all(ch.isprintable() for ch in name)
    assert not name.startswith(".")


def test_sanitize_filename_keeps_extension_when_truncating():
    from logstead.adapters.s3_files import sanitize_filename

    assert sanitize_filename("x" * 500 + ".jpg").endswith(".jpg")
    assert sanitize_filename("receipt (1).pdf") == "receipt (1).pdf"
    assert sanitize_filename("../../etc/passwd") == "passwd"


def test_presigned_put_url_has_short_expiry_and_binds_content_type(adapter):
    url = adapter.presigned_put_url(photo_key("p", "a.jpg"), "image/jpeg")

    assert "X-Amz-Expires=600" in url or "Expires=" in url
    assert "content-type" in url.lower()


def test_purge_if_oversized_deletes_only_large_objects(adapter, s3_client):
    s3_client.put_object(Bucket=BUCKET, Key="photos/p/big", Body=b"x" * 20)
    s3_client.put_object(Bucket=BUCKET, Key="photos/p/small", Body=b"x" * 5)

    assert adapter.purge_if_oversized("photos/p/big", 10) is True
    assert adapter.purge_if_oversized("photos/p/small", 10) is False
    assert adapter.purge_if_oversized("photos/p/missing", 10) is False
    assert adapter.object_size("photos/p/big") is None
    assert adapter.object_size("photos/p/small") == 5


# --- Accountant package additions (Requirements 1.1, 10.5, 14.1) -------------


def test_presigned_get_url_without_download_filename_has_no_disposition(adapter):
    url = adapter.presigned_get_url("exports/a.csv")
    assert "response-content-disposition" not in url.lower()


def test_presigned_get_url_with_download_filename_sets_quoted_attachment(adapter):
    from urllib.parse import parse_qs, urlparse

    url = adapter.presigned_get_url(
        "exports/a.csv", download_filename="../my report.csv"
    )
    query = parse_qs(urlparse(url).query)
    disposition = query["response-content-disposition"][0]
    assert disposition == 'attachment; filename="my report.csv"'


def test_open_stream_present_returns_body_and_length(adapter, s3_client):
    s3_client.put_object(Bucket=BUCKET, Key="receipts/t/r.pdf", Body=b"hello")
    result = adapter.open_stream("receipts/t/r.pdf")
    assert result is not None
    stream, length = result
    assert length == 5
    assert stream.read() == b"hello"


def test_open_stream_absent_returns_none(adapter):
    assert adapter.open_stream("receipts/missing") is None


def test_upload_file_stores_bytes_and_content_type(adapter, s3_client, tmp_path):
    path = tmp_path / "pkg.zip"
    path.write_bytes(b"zipbytes")
    adapter.upload_file(str(path), "exports/packages/u/j/pkg.zip", "application/zip")
    obj = s3_client.get_object(Bucket=BUCKET, Key="exports/packages/u/j/pkg.zip")
    assert obj["Body"].read() == b"zipbytes"
    assert obj["ContentType"] == "application/zip"


def test_package_key_and_pdf_key_shapes():
    from logstead.adapters.s3_files import package_key, pdf_key

    assert (
        package_key("user-1", "job-9", 2024)
        == "exports/packages/user-1/job-9/logstead-accountant-package-2024.zip"
    )
    assert pdf_key("user-1", "rand", "r.pdf") == "exports/pdf/user-1/rand/r.pdf"
