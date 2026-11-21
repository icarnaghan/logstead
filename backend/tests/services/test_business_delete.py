"""Task 6.1: moto example/edge tests for the guarded delete + document cascade.

Exercises :meth:`BusinessService.delete` — the guarded delete with a document
cascade (Requirement 5) — against a ``moto``-backed single-table DynamoDB
(base + GSI1 + GSI2) **and** a moto S3 bucket, so no live AWS call is made and
both collaborators (the repository and the S3 adapter) are real. The business
and property services are wired *router-style* per the design's constructor
contract (design.md "Mutual dependency / wiring") so the delete-guard can call
``linked_properties`` (which lists the user's properties and filters by
``business_id``).

Covers the Requirement 5 example/edge behavior from the design's Testing
Strategy → delete-guard/cascade:

* delete with >=1 linked property -> ``conflict`` carrying the reassign/unlink
  message, and NOTHING mutated: the business's two rows, its document metadata
  rows, and the linked property's rows all remain intact (Req 5.2);
* delete after unlinking the property succeeds and removes the business
  (Req 5.1);
* cascade: deleting a business with documents removes every document metadata
  row and attempts best-effort S3 object deletion (Req 5.1, 5.4);
* cross-user / unknown business id -> ``not_found`` (Req 5.3).

The entity-CRUD example tests (task 2.1) live in ``test_business_service.py``,
the document surface (task 3.1) in ``test_business_documents.py``, and the
property-link/both-sides view (tasks 4.1, 5.1) in ``test_business_link.py``;
this module touches none of them — it exercises only ``delete``.
"""

from __future__ import annotations

import boto3
import pytest
from moto import mock_aws

from logstead.adapters.s3_files import S3FileAdapter
from logstead.models.business import BusinessInput
from logstead.models.property import PropertyInput
from logstead.models.user import UserContext
from logstead.repository import keys
from logstead.repository.dynamo_repo import DynamoRepository
from logstead.services.business import BusinessService
from logstead.services.property import PropertyService

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


def _wire(repo: DynamoRepository, files: S3FileAdapter, user_id: str):
    """Wire a Business/Property service pair router-style for one user.

    Mirrors the design's per-request wiring: build the business service (with
    the S3 adapter so ``delete`` can cascade to S3), build the property service
    with the business service injected, then back-fill the property-service
    reference onto the business service so ``linked_properties`` (and therefore
    the delete-guard) resolves (no import cycle).
    """
    user = UserContext(user_id=user_id)
    biz = BusinessService(repo, user, files=files)
    prop = PropertyService(repo, user, business_service=biz)
    biz._property_service = prop
    return biz, prop


@pytest.fixture
def services(repo, files):
    """A wired (business, property) pair scoped to user A."""
    return _wire(repo, files, USER_A)


@pytest.fixture
def services_b(repo, files):
    """A wired (business, property) pair scoped to user B (same repo + bucket)."""
    return _wire(repo, files, USER_B)


def _make_business(biz: BusinessService, legal_name: str = "Maple Holdings LLC"):
    created = biz.create(BusinessInput(legal_name=legal_name, entity_type="llc"))
    assert created.is_ok
    return created.value


def _make_property(prop: PropertyService, name: str = "Maple Duplex"):
    created = prop.create(PropertyInput(name=name, address_text="1 Maple St"))
    assert created.is_ok
    return created.value


def _business_rows_exist(repo: DynamoRepository, user_id: str, business_id: str):
    """Return (list_row, meta_row) for a business (either may be None)."""
    list_row = repo.get_item(
        keys.user_pk(user_id), keys.business_user_sk(business_id)
    )
    meta_row = repo.get_item(
        keys.business_scoped_pk(business_id), keys.business_meta_sk()
    )
    return list_row, meta_row


def _doc_items(repo: DynamoRepository, business_id: str) -> list:
    """Raw stored DOC# metadata rows for a business."""
    return repo.query(
        keys.business_scoped_pk(business_id),
        sk_begins_with=keys.business_document_list_prefix(),
    )


def _s3_keys(s3_client) -> set[str]:
    """The set of object keys currently in the bucket."""
    contents = s3_client.list_objects_v2(Bucket=BUCKET).get("Contents", [])
    return {obj["Key"] for obj in contents}


# =============================================================================
# Delete-guard: a linked property blocks deletion and mutates nothing (Req 5.2)
# =============================================================================


def test_delete_with_linked_property_is_conflict_with_message(services):
    """Deleting a business that still owns a property -> conflict + guidance."""
    biz, prop = services
    business = _make_business(biz)
    p = _make_property(prop, "Oak Cottage")
    assert prop.set_business(p.id, business.id).is_ok

    result = biz.delete(business.id)

    assert not result.is_ok
    assert result.error.kind == "conflict"
    # The message instructs the user to reassign or unlink first (Req 5.2).
    message = result.error.message.lower()
    assert "reassign" in message
    assert "unlink" in message


def test_delete_blocked_mutates_nothing(services, repo, s3_client):
    """A blocked delete leaves the business, its documents, and the link intact."""
    biz, prop = services
    business = _make_business(biz)
    # Attach a couple of documents so the cascade path is clearly not taken.
    doc_a = biz.request_document_upload(
        business.id, "articles.pdf", "application/pdf"
    ).value.document
    doc_b = biz.request_document_upload(
        business.id, "ein.png", "image/png"
    ).value.document
    # Simulate the browser having completed one upload so an S3 object exists.
    s3_client.put_object(
        Bucket=BUCKET, Key=doc_a.s3_key, Body=b"bytes", ContentType="application/pdf"
    )

    p = _make_property(prop, "Oak Cottage")
    assert prop.set_business(p.id, business.id).is_ok

    before_docs = {item["id"] for item in _doc_items(repo, business.id)}
    before_s3 = _s3_keys(s3_client)

    result = biz.delete(business.id)
    assert not result.is_ok
    assert result.error.kind == "conflict"

    # Business rows untouched.
    list_row, meta_row = _business_rows_exist(repo, USER_A, business.id)
    assert list_row is not None
    assert meta_row is not None
    assert biz.get(business.id).is_ok

    # Document metadata rows untouched.
    after_docs = {item["id"] for item in _doc_items(repo, business.id)}
    assert after_docs == before_docs == {doc_a.id, doc_b.id}

    # S3 object(s) untouched.
    assert _s3_keys(s3_client) == before_s3
    assert doc_a.s3_key in _s3_keys(s3_client)

    # The property's link is unchanged — still pointing at the business.
    assert prop.get(p.id).value.business_id == business.id
    assert [r.id for r in biz.linked_properties(business.id).value] == [p.id]


# =============================================================================
# Delete after unlinking succeeds (Req 5.1)
# =============================================================================


def test_delete_succeeds_after_unlinking_property(services, repo):
    """Clearing the link then deleting removes the business's two rows."""
    biz, prop = services
    business = _make_business(biz)
    p = _make_property(prop, "Pine Flat")
    assert prop.set_business(p.id, business.id).is_ok

    # Guard blocks while linked.
    assert biz.delete(business.id).error.kind == "conflict"

    # Unlink, then the delete goes through.
    assert prop.set_business(p.id, None).is_ok
    result = biz.delete(business.id)
    assert result.is_ok

    list_row, meta_row = _business_rows_exist(repo, USER_A, business.id)
    assert list_row is None
    assert meta_row is None
    assert biz.get(business.id).error.kind == "not_found"
    # The (now unlinked) property survives the business deletion.
    assert prop.get(p.id).is_ok
    assert prop.get(p.id).value.business_id is None


def test_delete_unlinked_business_with_no_properties_succeeds(services, repo):
    """A business that never owned a property deletes cleanly."""
    biz, _ = services
    business = _make_business(biz, "Lonely LLC")

    result = biz.delete(business.id)
    assert result.is_ok

    list_row, meta_row = _business_rows_exist(repo, USER_A, business.id)
    assert list_row is None
    assert meta_row is None
    assert biz.list() == []


# =============================================================================
# Cascade: delete removes all document rows + attempts S3 object deletion
# (Req 5.1, 5.4)
# =============================================================================


def test_delete_cascades_document_rows_and_s3_objects(services, repo, s3_client):
    """Deleting a business removes every doc row and its S3 objects."""
    biz, _ = services
    business = _make_business(biz)
    doc_a = biz.request_document_upload(
        business.id, "articles.pdf", "application/pdf"
    ).value.document
    doc_b = biz.request_document_upload(
        business.id, "ein.png", "image/png"
    ).value.document
    doc_c = biz.request_document_upload(
        business.id, "operating.pdf", "application/pdf"
    ).value.document
    # Simulate completed browser uploads for all three documents.
    for doc, ctype in (
        (doc_a, "application/pdf"),
        (doc_b, "image/png"),
        (doc_c, "application/pdf"),
    ):
        s3_client.put_object(
            Bucket=BUCKET, Key=doc.s3_key, Body=b"bytes", ContentType=ctype
        )

    assert len(_doc_items(repo, business.id)) == 3
    doc_keys = {doc_a.s3_key, doc_b.s3_key, doc_c.s3_key}
    assert doc_keys <= _s3_keys(s3_client)

    result = biz.delete(business.id)
    assert result.is_ok

    # Every document metadata row is gone (Req 5.4).
    assert _doc_items(repo, business.id) == []
    # The S3 objects were deleted best-effort (Req 5.4).
    assert _s3_keys(s3_client).isdisjoint(doc_keys)
    # The business's two rows are gone (Req 5.1).
    list_row, meta_row = _business_rows_exist(repo, USER_A, business.id)
    assert list_row is None
    assert meta_row is None


def test_delete_with_metadata_but_missing_s3_object_still_cascades(
    services, repo, s3_client
):
    """A document whose S3 object was never uploaded doesn't abort the cascade.

    Best-effort S3 deletion means a missing object is tolerated; the DynamoDB
    document rows and the business rows are still removed (Req 5.4).
    """
    biz, _ = services
    business = _make_business(biz)
    # Metadata exists, but no bytes were ever uploaded for this document.
    biz.request_document_upload(business.id, "never-uploaded.pdf", "application/pdf")
    assert len(_doc_items(repo, business.id)) == 1
    assert _s3_keys(s3_client) == set()

    result = biz.delete(business.id)
    assert result.is_ok

    assert _doc_items(repo, business.id) == []
    list_row, meta_row = _business_rows_exist(repo, USER_A, business.id)
    assert list_row is None
    assert meta_row is None


# =============================================================================
# Cross-user / unknown business id -> not_found (Req 5.3)
# =============================================================================


def test_delete_unknown_business_is_not_found(services):
    biz, _ = services
    result = biz.delete("does-not-exist")
    assert not result.is_ok
    assert result.error.kind == "not_found"
    assert result.error.field == "business_id"


def test_delete_cross_user_is_not_found_and_leaves_data(services, services_b, repo):
    """User A cannot delete user B's business; B's rows remain intact."""
    biz_a, _ = services
    biz_b, _ = services_b
    theirs = _make_business(biz_b, "Theirs LLC")
    biz_b.request_document_upload(theirs.id, "a.pdf", "application/pdf")

    before_docs = {item["id"] for item in _doc_items(repo, theirs.id)}

    result = biz_a.delete(theirs.id)
    assert not result.is_ok
    assert result.error.kind == "not_found"
    assert result.error.field == "business_id"

    # User B's business and its document row survive untouched.
    list_row, meta_row = _business_rows_exist(repo, USER_B, theirs.id)
    assert list_row is not None
    assert meta_row is not None
    assert {item["id"] for item in _doc_items(repo, theirs.id)} == before_docs
    assert biz_b.get(theirs.id).is_ok
