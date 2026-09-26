"""Property-based test for the photo content-type allow-list (task 9.3).

Validates design Property 6 for the Photo Service: an upload is authorized
(a pre-signed URL issued *and* metadata persisted) if and only if the declared
content type — after trimming and lowercasing — is in the accepted image
allow-list; otherwise it is rejected as a ``validation`` failure identifying the
``content_type`` field and naming the accepted types, with nothing written.

The test drives the real :class:`PhotoService` against a ``moto``-backed S3
bucket and DynamoDB table (a fresh pair per example), so both collaborators are
exercised for real and no live AWS call is ever made.
"""

from __future__ import annotations

import boto3
from hypothesis import HealthCheck, given, settings
from hypothesis import strategies as st
from moto import mock_aws

from logstead.adapters.s3_files import S3FileAdapter
from logstead.repository import keys
from logstead.repository.dynamo_repo import DynamoRepository
from logstead.services.photo import ALLOWED_CONTENT_TYPES, PhotoService, _normalize

TABLE_NAME = "Logstead"
BUCKET = "logstead-files-test"
REGION = "us-east-1"
PROPERTY_ID = "prop-1"


def _make_service_context():
    """Create a fresh moto S3 + DynamoDB context and a wired PhotoService.

    Returns the ``mock_aws`` context manager (kept alive by the caller for the
    duration of one example), the repository, and the service.
    """
    ctx = mock_aws()
    ctx.start()
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
    repo = DynamoRepository(ddb, TABLE_NAME)
    service = PhotoService(repo, S3FileAdapter(s3, BUCKET))
    return ctx, repo, service


def _photo_items(repo: DynamoRepository) -> list:
    """Query the raw stored PHOTO# metadata items for the property."""
    return repo.query(
        keys.property_scoped_pk(PROPERTY_ID),
        sk_begins_with=keys.photo_list_prefix(),
    )


# Case/whitespace variants of an allowed type keep it *effectively* allowed,
# so we can assert the normalization (trim + lowercase) contract too.
def _cased_variants(base: str) -> st.SearchStrategy[str]:
    return st.sampled_from(
        [
            base,
            base.upper(),
            base.title(),
            f"  {base}  ",
            f"\t{base.upper()}\n",
        ]
    )


# A mix of: free-form text, plausible ``image/<subtype>`` strings (mostly not in
# the allow-list), the exact allowed types, and case/whitespace variants of the
# allowed types. This spans both sides of the allow-list boundary.
content_types = st.one_of(
    st.text(max_size=40),
    st.builds(lambda sub: f"image/{sub}", st.text(alphabet="abcdefghijklmnop+-", min_size=0, max_size=12)),
    st.sampled_from(sorted(ALLOWED_CONTENT_TYPES)),
    st.sampled_from(sorted(ALLOWED_CONTENT_TYPES)).flatmap(_cased_variants),
)


# Feature: logstead, Property 6: Photo upload accepts exactly the allowed image types
# Validates: Requirements 4.2
@settings(deadline=None, max_examples=200, suppress_health_check=[HealthCheck.too_slow])
@given(content_type=content_types, filename=st.text(min_size=1, max_size=20))
def test_photo_upload_accepts_exactly_allowed_types(content_type: str, filename: str):
    """Upload authorized iff normalized content type is in the allow-list."""
    ctx, repo, service = _make_service_context()
    try:
        allowed = _normalize(content_type) in ALLOWED_CONTENT_TYPES
        result = service.request_upload(PROPERTY_ID, filename, content_type)

        if allowed:
            # Accepted: a URL is issued AND metadata is persisted.
            assert result.is_ok, f"expected accept for {content_type!r}"
            upload = result.value
            assert upload.upload_url.startswith("https://")
            # Stored content type is the normalized (trim + lowercase) form.
            assert upload.photo.content_type == _normalize(content_type)

            stored = repo.get_item(
                keys.property_scoped_pk(PROPERTY_ID),
                keys.photo_sk(upload.photo.id),
            )
            assert stored is not None
            assert stored["contentType"] == _normalize(content_type)
            # Exactly one metadata row was written.
            assert len(_photo_items(repo)) == 1
        else:
            # Rejected: validation failure on content_type, naming accepted types.
            assert not result.is_ok, f"expected reject for {content_type!r}"
            assert result.error.kind == "validation"
            assert result.error.field == "content_type"
            for accepted in ALLOWED_CONTENT_TYPES:
                assert accepted in result.error.message
            # Nothing was written.
            assert _photo_items(repo) == []
    finally:
        ctx.stop()
