"""Task 4.2: router tests for the Schedule E PDF routes (moto-backed)."""
from __future__ import annotations

import json
import re

import boto3
import pytest
from moto import mock_aws

from logstead.adapters.s3_files import S3FileAdapter
from logstead.models.result import Result
from logstead.repository.dynamo_repo import DynamoRepository
from logstead.router import handler as handler_module
from logstead.router.handler import _dispatch, handler
from logstead.services.package_config import DOWNLOAD_LINK_SECONDS
from logstead.services.report import ReportingService

TABLE_NAME = "Logstead"
BUCKET = "logstead-files-pdf-routes"
REGION = "us-east-1"
USER = "pdf-routes-user-sub"
OTHER = "pdf-routes-other-sub"


def _create_table():
    ddb = boto3.client("dynamodb", region_name=REGION)
    ddb.create_table(
        TableName=TABLE_NAME,
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
                "IndexName": f"GSI{i}",
                "KeySchema": [
                    {"AttributeName": f"GSI{i}PK", "KeyType": "HASH"},
                    {"AttributeName": f"GSI{i}SK", "KeyType": "RANGE"},
                ],
                "Projection": {"ProjectionType": "ALL"},
            }
            for i in (1, 2)
        ],
        BillingMode="PAY_PER_REQUEST",
    )
    return ddb


@pytest.fixture
def s3():
    with mock_aws():
        ddb = _create_table()
        client = boto3.client("s3", region_name=REGION)
        client.create_bucket(Bucket=BUCKET)
        handler_module.configure(
            repo=DynamoRepository(ddb, TABLE_NAME), files=S3FileAdapter(client, BUCKET)
        )
        yield client
        handler_module.reset_wiring()


@pytest.fixture
def no_bucket():
    with mock_aws():
        ddb = _create_table()
        handler_module.configure(repo=DynamoRepository(ddb, TABLE_NAME), files=None)
        yield
        handler_module.reset_wiring()


def _call(method, path, *, query=None, sub=USER, body=None):
    event = {
        "requestContext": {
            "http": {"method": method, "path": path},
            "authorizer": {"jwt": {"claims": {"sub": sub}}},
        },
        "rawPath": path,
    }
    if body is not None:
        event["body"] = json.dumps(body)
    if query is not None:
        event["queryStringParameters"] = {k: str(v) for k, v in query.items()}
    resp = handler(event)
    return resp["statusCode"], (json.loads(resp["body"]) if resp["body"] else None)


def _make_property(name="Oak House", sub=USER):
    status, prop = _call(
        "POST", "/properties", body={"name": name, "address_text": "1 St"}, sub=sub
    )
    assert status in (200, 201), prop
    return prop["id"]


def _keys(s3):
    resp = s3.list_objects_v2(Bucket=BUCKET)
    return [o["Key"] for o in resp.get("Contents", [])]


def _assert_link_body(body, filename):
    assert body["filename"] == filename
    assert body["content_type"] == "application/pdf"
    assert body["expires_in_seconds"] == DOWNLOAD_LINK_SECONDS
    assert body["size_bytes"] > 0
    assert body["download_url"].startswith("http")
    assert "attachment" in body["download_url"].lower()


# --- success ----------------------------------------------------------------


def test_property_pdf_success_stores_object_and_links(s3):
    pid = _make_property("Oak House")
    status, body = _call(
        "POST", f"/properties/{pid}/report/pdf", query={"taxYear": 2023}
    )
    assert status == 200, body
    _assert_link_body(body, "schedule-e-oak-house-2023.pdf")
    keys = _keys(s3)
    assert len(keys) == 1
    assert re.fullmatch(
        rf"exports/pdf/{USER}/[0-9a-f]+/schedule-e-oak-house-2023\.pdf", keys[0]
    )
    obj = s3.get_object(Bucket=BUCKET, Key=keys[0])["Body"].read()
    assert obj.startswith(b"%PDF")
    assert len(obj) == body["size_bytes"]


def test_combined_pdf_success_stores_object_and_links(s3):
    _make_property("A")
    _make_property("B")
    status, body = _call("POST", "/reports/combined/pdf", query={"taxYear": 2023})
    assert status == 200, body
    _assert_link_body(body, "schedule-e-combined-2023.pdf")
    keys = _keys(s3)
    assert len(keys) == 1
    assert re.fullmatch(
        rf"exports/pdf/{USER}/[0-9a-f]+/schedule-e-combined-2023\.pdf", keys[0]
    )
    assert s3.get_object(Bucket=BUCKET, Key=keys[0])["Body"].read().startswith(b"%PDF")


def test_combined_pdf_with_property_ids_subset(s3):
    a = _make_property("A")
    _make_property("B")
    status, body = _call(
        "POST", "/reports/combined/pdf", query={"taxYear": 2023, "propertyIds": a}
    )
    assert status == 200, body
    assert len(_keys(s3)) == 1


def test_each_request_uses_a_fresh_random_segment(s3):
    pid = _make_property()
    for _ in range(2):
        assert _call("POST", f"/properties/{pid}/report/pdf", query={"taxYear": 2023})[0] == 200
    assert len(set(_keys(s3))) == 2


def test_filename_slug_for_unusual_property_name(s3):
    pid = _make_property("  Élan / 12th St. #3 ")
    status, body = _call(
        "POST", f"/properties/{pid}/report/pdf", query={"taxYear": 2022}
    )
    assert status == 200, body
    assert re.fullmatch(r"schedule-e-[a-z0-9-]+-2022\.pdf", body["filename"])
    assert "/" not in body["filename"]


# --- validation -------------------------------------------------------------


@pytest.mark.parametrize("year", ["abc", "1899", "2201", ""])
def test_bad_tax_year_is_400(s3, year):
    pid = _make_property()
    for path in (f"/properties/{pid}/report/pdf", "/reports/combined/pdf"):
        status, body = _call("POST", path, query={"taxYear": year})
        assert status == 400, (path, body)
        assert body["field"] == "taxYear"
    assert _keys(s3) == []


def test_missing_tax_year_is_400(s3):
    pid = _make_property()
    status, body = _call("POST", f"/properties/{pid}/report/pdf")
    assert status == 400
    assert body["field"] == "taxYear"


@pytest.mark.parametrize("ids", ["bad id!", "../x", ",".join(["a"] * 101)])
def test_bad_property_ids_is_400(s3, ids):
    _make_property()
    status, body = _call(
        "POST", "/reports/combined/pdf", query={"taxYear": 2023, "propertyIds": ids}
    )
    assert status == 400, body
    assert body["field"] == "propertyIds"
    assert _keys(s3) == []


def test_no_property_is_400_on_propertyids(s3):
    status, body = _call("POST", "/reports/combined/pdf", query={"taxYear": 2023})
    assert status == 400, body
    assert body["field"] == "propertyIds"
    assert _keys(s3) == []


# --- storage / conflicts ----------------------------------------------------


def test_no_bucket_is_503(no_bucket):
    pid = _make_property()
    for path in (f"/properties/{pid}/report/pdf", "/reports/combined/pdf"):
        status, body = _call("POST", path, query={"taxYear": 2023})
        assert status == 503, (path, body)
        assert "download_url" not in body


def test_report_conflict_passes_through_without_link(s3, monkeypatch):
    pid = _make_property()

    def fail(self, *a, **k):
        return Result.failure("conflict", "Stored loan has an invalid rate value.", "rate")

    monkeypatch.setattr(ReportingService, "report_for", fail)
    status, body = _call(
        "POST", f"/properties/{pid}/report/pdf", query={"taxYear": 2023}
    )
    assert status == 409, body
    assert "download_url" not in body
    assert _keys(s3) == []


def test_combined_report_conflict_passes_through_without_link(s3, monkeypatch):
    _make_property()

    def fail(self, *a, **k):
        return Result.failure("conflict", "Stored loan has an invalid rate value.", "rate")

    monkeypatch.setattr(ReportingService, "combined_report", fail)
    status, body = _call("POST", "/reports/combined/pdf", query={"taxYear": 2023})
    assert status == 409, body
    assert "download_url" not in body
    assert _keys(s3) == []


# --- route resolution -------------------------------------------------------


def test_get_on_pdf_paths_resolves_to_no_route():
    assert _dispatch("GET", "/properties/p1/report/pdf") is None
    assert _dispatch("GET", "/reports/combined/pdf") is None


def test_post_pdf_paths_resolve():
    assert _dispatch("POST", "/properties/p1/report/pdf") is not None
    assert _dispatch("POST", "/reports/combined/pdf") is not None


def test_existing_report_routes_unchanged():
    match = _dispatch("GET", "/reports/combined")
    assert match is not None
    assert match[0].__name__ == "_combined_report"
    match = _dispatch("GET", "/properties/p1/report")
    assert match is not None
    assert match[0].__name__ == "_property_report"
    assert match[1] == {"propertyId": "p1"}
    assert _dispatch("POST", "/reports/combined") is None
    assert _dispatch("POST", "/properties/p1/report") is None


# --- cross-user -------------------------------------------------------------


def test_other_users_property_matches_missing_property_and_writes_nothing(s3):
    pid = _make_property()
    q = {"taxYear": 2023}
    other = _call("POST", f"/properties/{pid}/report/pdf", query=q, sub=OTHER)
    missing = _call("POST", "/properties/does-not-exist/report/pdf", query=q, sub=OTHER)
    assert other[0] == 404
    assert other == missing
    assert _keys(s3) == []


def test_other_users_property_in_property_ids_matches_missing_id(s3):
    pid = _make_property()
    _make_property("Mine", sub=OTHER)
    q = {"taxYear": 2023}
    other = _call("POST", "/reports/combined/pdf", query={**q, "propertyIds": pid}, sub=OTHER)
    missing = _call(
        "POST", "/reports/combined/pdf", query={**q, "propertyIds": "nope"}, sub=OTHER
    )
    assert other == missing
    assert other[0] == 404, other
    assert _keys(s3) == []
