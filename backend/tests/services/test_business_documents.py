"""Task 3.1: moto S3 example tests for ``BusinessService`` document operations.

Exercises the document surface
(``request_document_upload``/``list_documents``/``delete_document``) against a
``moto``-backed single-table DynamoDB (base + GSI1 + GSI2) **and** a moto S3
bucket, so no live AWS call is made and both collaborators are real. Covers the
Requirement 6-8 behavior from the design's Testing Strategy:

* ``request_document_upload`` with ``application/pdf`` -> success + a persisted
  metadata row + a pre-signed PUT URL (Req 6.1, 6.2);
* an unsupported ``content_type`` (e.g. ``text/plain``) -> ``validation`` (field
  ``content_type``) with NO S3 URL issued and NO metadata written — the stored
  document count is unchanged (mirrors ``PhotoService`` ordering, Req 6 / design
  "Document content-type allow-list");
* ``list_documents`` returns each document with a download URL and is empty when
  none (Req 7.1-7.3);
* ``delete_document`` removes the S3 object and the metadata row, and a re-delete
  of the same id is ``not_found`` (Req 8.1, 8.2);
* every op on a cross-user / unknown business -> ``not_found`` (Req 6.3, 7.4,
  8 ownership check).

The entity CRUD tests (task 2.1) live in ``test_business_service.py`` and the
create->get property (task 2.2) in ``test_business_service_property.py``.
"""

from __future__ import annotations

import boto3
import pytest
from moto import mock_aws

from logstead.adapters.s3_files import S3FileAdapter
from logstead.models.business import BusinessInput
from logstead.models.user import UserContext
from logstead.repository import keys
from logstead.repository.dynamo_repo import DynamoRepository
from logstead.services.business import ALLOWED_DOCUMENT_TYPES, BusinessService

TABLE_NAME = "Logstead"
BUCKET = "logstead-files-test"
REGION = "us-east-1"
USER_A = "user-a"
USER_B = "user-b"


@pytest.fixture
def aws():
    """A moto context with the table (base + GSI1 + GSI2) and S3 bucket."""
    with mock_aws():
        ddb = boto3.client("dynamodb", region_name=REGION)
        ddb.create_table(
            TableName=TABLE_NAME,
            AttributeDefinitions=[
                {"AttributeName": "PK", "AttributeType": "S"},
                {"AttributeName": "SK", "AttributeType": "S"},
                {"AttributeName": "GSI1PK", "AttributeType": "S"},
                {"AttributeName": "GSI1SK", "AttributeType": "S"},
                {"AttributeName": "GSI2PK", "AttributeType": "S"},
                {"AttributeName": "GSI2SK", "AttributeType": "S"},
            ],
            KeySchema=[
                {"AttributeName": "PK", "KeyType": "HASH"},
                {"AttributeName": "SK", "KeyType": "RANGE"},
            ],
            GlobalSecondaryIndexes=[
                {
                    "IndexName": "GSI1",
                    "KeySchema": [
                        {"AttributeName": "GSI1PK", "KeyType": "HASH"},
                        {"AttributeName": "GSI1SK", "KeyType": "RANGE"},
                    ],
                    "Projection": {"ProjectionType": "ALL"},
                },
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
def files(s3_client):
    return S3FileAdapter(s3_client, BUCKET)


@pytest.fixture
def service(repo, files):
    """A ``BusinessService`` scoped to user A with the S3 adapter wired."""
    return BusinessService(repo, UserContext(user_id=USER_A), files=files)


@pytest.fixture
def service_b(repo, files):
    """A ``BusinessService`` scoped to user B (same repo + bucket)."""
    return BusinessService(repo, UserContext(user_id=USER_B), files=files)


@pytest.fixture
def business(service):
    """An owned business under user A to attach documents to."""
    created = service.create(
        BusinessInput(legal_name="Maple Holdings LLC", entity_type="llc")
    )
    assert created.is_ok
    return created.value


def _doc_items(repo: DynamoRepository, business_id: str) -> list:
    """Raw stored DOC# metadata rows for a business."""
    return repo.query(
        keys.business_scoped_pk(business_id),
        sk_begins_with=keys.business_document_list_prefix(),
    )


# --- request_document_upload: happy path (Req 6.1, 6.2) ----------------------


def test_request_upload_pdf_succeeds_with_url_and_metadata(service, repo, business):
    result = service.request_document_upload(
        business.id, "articles.pdf", "application/pdf"
    )

    assert result.is_ok
    upload = result.value

    # Pre-signed PUT URL targets the bucket and the document's filename.
    assert upload.upload_url.startswith("https://")
    assert BUCKET in upload.upload_url
    assert "articles.pdf" in upload.upload_url

    doc = upload.document
    assert doc.id
    assert doc.business_id == business.id
    assert doc.original_filename == "articles.pdf"
    assert doc.content_type == "application/pdf"
    assert doc.s3_key.startswith(f"business-docs/{business.id}/")
    assert doc.uploaded_at is not None

    # Metadata persisted under the business partition with the design's keys.
    stored = repo.get_item(
        keys.business_scoped_pk(business.id), keys.business_document_sk(doc.id)
    )
    assert stored is not None
    assert stored["s3Key"] == doc.s3_key
    assert stored["contentType"] == "application/pdf"
    assert stored["originalFilename"] == "articles.pdf"
    assert stored["businessId"] == business.id


@pytest.mark.parametrize("good_type", sorted(ALLOWED_DOCUMENT_TYPES))
def test_request_upload_accepts_each_allowed_type(service, business, good_type):
    result = service.request_document_upload(business.id, "f.bin", good_type)
    assert result.is_ok
    assert result.value.document.content_type == good_type


def test_distinct_uploads_get_distinct_keys(service, business):
    a = service.request_document_upload(business.id, "same.pdf", "application/pdf")
    b = service.request_document_upload(business.id, "same.pdf", "application/pdf")
    assert a.value.document.id != b.value.document.id
    assert a.value.document.s3_key != b.value.document.s3_key


# --- request_document_upload: unsupported content_type (Req 6, allow-list) ---


@pytest.mark.parametrize(
    "bad_type", ["text/plain", "image/gif", "image/svg+xml", "", "application/zip"]
)
def test_request_upload_rejects_unsupported_type_without_side_effects(
    service, repo, s3_client, business, bad_type
):
    before = len(_doc_items(repo, business.id))

    result = service.request_document_upload(business.id, "notes.txt", bad_type)

    assert not result.is_ok
    assert result.error.kind == "validation"
    assert result.error.field == "content_type"
    # The message names the accepted types.
    for accepted in ALLOWED_DOCUMENT_TYPES:
        assert accepted in result.error.message

    # No metadata row written: count is unchanged.
    assert len(_doc_items(repo, business.id)) == before
    # No S3 object was created by the rejected request.
    contents = s3_client.list_objects_v2(Bucket=BUCKET).get("Contents", [])
    assert contents == []


# --- request_document_upload: cross-user / unknown business (Req 6.3) --------


def test_request_upload_unknown_business_is_not_found(service):
    result = service.request_document_upload(
        "does-not-exist", "a.pdf", "application/pdf"
    )
    assert not result.is_ok
    assert result.error.kind == "not_found"
    assert result.error.field == "business_id"


def test_request_upload_cross_user_is_not_found(service, service_b, repo):
    theirs = service_b.create(
        BusinessInput(legal_name="Theirs LLC", entity_type="llc")
    ).value
    before = len(_doc_items(repo, theirs.id))

    result = service.request_document_upload(theirs.id, "a.pdf", "application/pdf")
    assert not result.is_ok
    assert result.error.kind == "not_found"
    assert result.error.field == "business_id"
    # Nothing written to user B's business.
    assert len(_doc_items(repo, theirs.id)) == before


# --- list_documents (Req 7.1-7.4) --------------------------------------------


def test_list_documents_empty_when_none(service, business):
    listed = service.list_documents(business.id)
    assert listed.is_ok
    assert listed.value == []


def test_list_documents_returns_each_with_download_url(service, business):
    service.request_document_upload(business.id, "articles.pdf", "application/pdf")
    service.request_document_upload(business.id, "ein.png", "image/png")

    listed = service.list_documents(business.id)
    assert listed.is_ok
    assert len(listed.value) == 2

    filenames = {d.document.original_filename for d in listed.value}
    assert filenames == {"articles.pdf", "ein.png"}

    for d in listed.value:
        assert d.download_url.startswith("https://")
        assert BUCKET in d.download_url


def test_list_documents_scoped_to_business(service, business):
    other = service.create(
        BusinessInput(legal_name="Other LLC", entity_type="llc")
    ).value
    service.request_document_upload(business.id, "mine.pdf", "application/pdf")
    service.request_document_upload(other.id, "theirs.pdf", "application/pdf")

    listed = service.list_documents(business.id)
    assert listed.is_ok
    assert len(listed.value) == 1
    assert listed.value[0].document.original_filename == "mine.pdf"
    assert listed.value[0].document.business_id == business.id


def test_list_documents_unknown_business_is_not_found(service):
    result = service.list_documents("does-not-exist")
    assert not result.is_ok
    assert result.error.kind == "not_found"
    assert result.error.field == "business_id"


def test_list_documents_cross_user_is_not_found(service, service_b):
    theirs = service_b.create(
        BusinessInput(legal_name="Theirs LLC", entity_type="llc")
    ).value
    service_b.request_document_upload(theirs.id, "a.pdf", "application/pdf")

    result = service.list_documents(theirs.id)
    assert not result.is_ok
    assert result.error.kind == "not_found"
    assert result.error.field == "business_id"


# --- delete_document (Req 8.1, 8.2) ------------------------------------------


def test_delete_document_removes_object_and_row(service, repo, s3_client, business):
    doc = service.request_document_upload(
        business.id, "articles.pdf", "application/pdf"
    ).value.document

    # Simulate the browser having completed the upload.
    s3_client.put_object(
        Bucket=BUCKET, Key=doc.s3_key, Body=b"bytes", ContentType="application/pdf"
    )
    contents = s3_client.list_objects_v2(Bucket=BUCKET).get("Contents", [])
    assert any(obj["Key"] == doc.s3_key for obj in contents)

    deleted = service.delete_document(business.id, doc.id)
    assert deleted.is_ok

    # S3 object gone.
    contents_after = s3_client.list_objects_v2(Bucket=BUCKET).get("Contents", [])
    assert not any(obj["Key"] == doc.s3_key for obj in contents_after)

    # Metadata row gone, and the listing is empty.
    assert (
        repo.get_item(
            keys.business_scoped_pk(business.id),
            keys.business_document_sk(doc.id),
        )
        is None
    )
    assert service.list_documents(business.id).value == []


def test_delete_document_then_redelete_is_not_found(service, business):
    doc = service.request_document_upload(
        business.id, "articles.pdf", "application/pdf"
    ).value.document

    first = service.delete_document(business.id, doc.id)
    assert first.is_ok

    second = service.delete_document(business.id, doc.id)
    assert not second.is_ok
    assert second.error.kind == "not_found"
    assert second.error.field == "document_id"


def test_delete_unknown_document_is_not_found(service, business):
    result = service.delete_document(business.id, "no-such-doc")
    assert not result.is_ok
    assert result.error.kind == "not_found"
    assert result.error.field == "document_id"


def test_delete_document_unknown_business_is_not_found(service):
    result = service.delete_document("does-not-exist", "any-doc")
    assert not result.is_ok
    assert result.error.kind == "not_found"
    assert result.error.field == "business_id"


def test_delete_document_cross_user_is_not_found(service, service_b, repo):
    theirs = service_b.create(
        BusinessInput(legal_name="Theirs LLC", entity_type="llc")
    ).value
    doc = service_b.request_document_upload(
        theirs.id, "a.pdf", "application/pdf"
    ).value.document

    result = service.delete_document(theirs.id, doc.id)
    assert not result.is_ok
    assert result.error.kind == "not_found"
    assert result.error.field == "business_id"
    # User B's document row survives.
    assert (
        repo.get_item(
            keys.business_scoped_pk(theirs.id),
            keys.business_document_sk(doc.id),
        )
        is not None
    )


# --- Presigned upload audit (S8) ----------------------------------------------


def test_request_upload_sanitizes_filename_in_key_and_metadata(service, business):
    result = service.request_document_upload(
        business.id, "../../evil\x00/name.pdf", "application/pdf"
    )

    assert result.is_ok
    document = result.value.document
    assert document.original_filename == "name.pdf"
    assert ".." not in document.s3_key
    assert document.s3_key.startswith(f"business-docs/{business.id}/")


def test_list_documents_purges_oversized_upload(
    service, repo, files, s3_client, business, monkeypatch
):
    import logstead.adapters.s3_files as s3_mod

    monkeypatch.setattr(s3_mod, "MAX_DOCUMENT_BYTES", 10)
    ok = service.request_document_upload(business.id, "ok.pdf", "application/pdf").value
    big = service.request_document_upload(business.id, "big.pdf", "application/pdf").value
    s3_client.put_object(Bucket=BUCKET, Key=ok.document.s3_key, Body=b"x" * 5)
    s3_client.put_object(Bucket=BUCKET, Key=big.document.s3_key, Body=b"x" * 50)

    listed = service.list_documents(business.id).value

    assert [d.document.id for d in listed] == [ok.document.id]
    assert files.object_size(big.document.s3_key) is None
    assert len(_doc_items(repo, business.id)) == 1
