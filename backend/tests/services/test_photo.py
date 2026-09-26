"""Unit tests for the Photo Service (task 9.2, Requirement 4).

Exercises the service against a ``moto``-backed S3 bucket **and** DynamoDB table
so no live AWS call is ever made and both collaborators are real:

* allow-list rejection: an unaccepted content type is rejected with a
  ``validation`` failure identifying ``content_type`` and naming the accepted
  types, and neither an S3 URL nor a metadata item is produced (Requirement 4.2);
* upload-url issuance + metadata persisted: an accepted type yields a pre-signed
  PUT URL and a stored ``PropertyPhoto`` metadata item (Requirement 4.1);
* list: all photos for a property are returned, each with a display GET URL
  (Requirement 4.3);
* delete: removes **both** the S3 object and the metadata item, and reports
  ``not_found`` for an unknown photo (Requirement 4.4).

The Property 6 allow-list property-based test (task 9.3) and the broader S3
integration tests (task 9.4) are intentionally not implemented here.
"""

from __future__ import annotations

import boto3
import pytest
from moto import mock_aws

from logstead.adapters.s3_files import S3FileAdapter
from logstead.repository import keys
from logstead.repository.dynamo_repo import DynamoRepository
from logstead.services.photo import ALLOWED_CONTENT_TYPES, PhotoService

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
def repo(aws):
    ddb, _ = aws
    return DynamoRepository(ddb, TABLE_NAME)


@pytest.fixture
def s3_client(aws):
    _, s3 = aws
    return s3


@pytest.fixture
def service(repo, s3_client):
    return PhotoService(repo, S3FileAdapter(s3_client, BUCKET))


def _photo_items(repo: DynamoRepository) -> list:
    """Query the raw stored PHOTO# items for the property."""
    return repo.query(
        keys.property_scoped_pk(PROPERTY_ID),
        sk_begins_with=keys.photo_list_prefix(),
    )


# --- Allow-list rejection (Requirement 4.2) ----------------------------------


@pytest.mark.parametrize(
    "bad_type",
    ["application/pdf", "text/plain", "image/gif", "image/svg+xml", "", "image/"],
)
def test_request_upload_rejects_disallowed_content_type(service, repo, bad_type):
    result = service.request_upload(PROPERTY_ID, "front.jpg", bad_type)

    assert not result.is_ok
    assert result.error.kind == "validation"
    assert result.error.field == "content_type"
    # Message names the accepted types.
    for accepted in ALLOWED_CONTENT_TYPES:
        assert accepted in result.error.message

    # Rejection is a no-op: no metadata item was written.
    assert _photo_items(repo) == []


def test_rejection_writes_nothing_and_lists_empty(service, repo):
    service.request_upload(PROPERTY_ID, "bad.txt", "text/plain")
    listed = service.list_photos(PROPERTY_ID)
    assert listed.is_ok
    assert listed.value == []


# --- Upload URL issuance + metadata persisted (Requirement 4.1) --------------


@pytest.mark.parametrize("good_type", sorted(ALLOWED_CONTENT_TYPES))
def test_request_upload_accepts_each_allowed_type(service, good_type):
    result = service.request_upload(PROPERTY_ID, "front.jpg", good_type)
    assert result.is_ok
    assert result.value.photo.content_type == good_type


def test_request_upload_normalizes_case_and_whitespace(service):
    result = service.request_upload(PROPERTY_ID, "front.jpg", "  IMAGE/JPEG  ")
    assert result.is_ok
    assert result.value.photo.content_type == "image/jpeg"


def test_request_upload_issues_put_url_and_persists_metadata(service, repo):
    result = service.request_upload(PROPERTY_ID, "front.jpg", "image/jpeg")

    assert result.is_ok
    upload = result.value
    # Pre-signed PUT URL targets the bucket and the photo's filename.
    assert upload.upload_url.startswith("https://")
    assert BUCKET in upload.upload_url
    assert "front.jpg" in upload.upload_url

    photo = upload.photo
    assert photo.id
    assert photo.property_id == PROPERTY_ID
    assert photo.original_filename == "front.jpg"
    assert photo.content_type == "image/jpeg"
    assert photo.s3_key.startswith(f"photos/{PROPERTY_ID}/")
    assert photo.uploaded_at is not None

    # Metadata was persisted under the property partition with the design's keys.
    stored = repo.get_item(
        keys.property_scoped_pk(PROPERTY_ID), keys.photo_sk(photo.id)
    )
    assert stored is not None
    assert stored["s3Key"] == photo.s3_key
    assert stored["contentType"] == "image/jpeg"
    assert stored["originalFilename"] == "front.jpg"
    assert stored["propertyId"] == PROPERTY_ID


def test_distinct_uploads_get_distinct_keys(service):
    a = service.request_upload(PROPERTY_ID, "same.jpg", "image/jpeg")
    b = service.request_upload(PROPERTY_ID, "same.jpg", "image/jpeg")
    assert a.value.photo.id != b.value.photo.id
    assert a.value.photo.s3_key != b.value.photo.s3_key


# --- List (Requirement 4.3) --------------------------------------------------


def test_list_photos_returns_all_with_display_urls(service):
    service.request_upload(PROPERTY_ID, "front.jpg", "image/jpeg")
    service.request_upload(PROPERTY_ID, "back.png", "image/png")

    listed = service.list_photos(PROPERTY_ID)
    assert listed.is_ok
    assert len(listed.value) == 2

    filenames = {pw.photo.original_filename for pw in listed.value}
    assert filenames == {"front.jpg", "back.png"}

    for pw in listed.value:
        assert pw.display_url.startswith("https://")
        assert BUCKET in pw.display_url


def test_list_photos_empty_for_property_without_photos(service):
    listed = service.list_photos("no-such-property")
    assert listed.is_ok
    assert listed.value == []


def test_list_is_scoped_to_the_property(service):
    service.request_upload(PROPERTY_ID, "front.jpg", "image/jpeg")
    service.request_upload("prop-2", "other.jpg", "image/jpeg")

    listed = service.list_photos(PROPERTY_ID)
    assert listed.is_ok
    assert len(listed.value) == 1
    assert listed.value[0].photo.property_id == PROPERTY_ID


# --- Delete (Requirement 4.4) ------------------------------------------------


def test_delete_removes_both_object_and_metadata(service, repo, s3_client):
    result = service.request_upload(PROPERTY_ID, "front.jpg", "image/jpeg")
    photo = result.value.photo

    # Simulate the browser having completed the upload: put the object in S3.
    s3_client.put_object(
        Bucket=BUCKET, Key=photo.s3_key, Body=b"bytes", ContentType="image/jpeg"
    )
    contents = s3_client.list_objects_v2(Bucket=BUCKET).get("Contents", [])
    assert any(obj["Key"] == photo.s3_key for obj in contents)

    deleted = service.delete_photo(PROPERTY_ID, photo.id)
    assert deleted.is_ok

    # S3 object is gone.
    contents_after = s3_client.list_objects_v2(Bucket=BUCKET).get("Contents", [])
    assert not any(obj["Key"] == photo.s3_key for obj in contents_after)

    # Metadata item is gone.
    assert (
        repo.get_item(
            keys.property_scoped_pk(PROPERTY_ID), keys.photo_sk(photo.id)
        )
        is None
    )
    # And it no longer appears in the listing.
    listed = service.list_photos(PROPERTY_ID)
    assert listed.value == []


def test_delete_unknown_photo_is_not_found(service):
    result = service.delete_photo(PROPERTY_ID, "does-not-exist")
    assert not result.is_ok
    assert result.error.kind == "not_found"
    assert result.error.field == "photo_id"


def test_delete_without_uploaded_object_still_removes_metadata(service, repo):
    # Metadata written at request time, but the browser never completed the PUT.
    result = service.request_upload(PROPERTY_ID, "front.jpg", "image/jpeg")
    photo = result.value.photo

    deleted = service.delete_photo(PROPERTY_ID, photo.id)
    assert deleted.is_ok  # S3 delete is idempotent for a missing object.
    assert (
        repo.get_item(
            keys.property_scoped_pk(PROPERTY_ID), keys.photo_sk(photo.id)
        )
        is None
    )
