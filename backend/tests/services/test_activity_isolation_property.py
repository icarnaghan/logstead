"""Activity isolation property tests (fresh moto table per example).

Property 24: Reports do not depend on activity.
    **Validates: Requirements 19.2, 19.3, 19.4, 13.12**
Property 25: Recording failure does not change the response.
    **Validates: Requirements 20.1, 20.2**

Also a source scan: report, dashboard, carryforward, loan, depreciation,
transaction and backup (and the other domain services) never import
``services.activity`` (Requirements 19.1, 20.3).
"""
from __future__ import annotations

import ast
import json
import logging
import re
from contextlib import contextmanager
from datetime import datetime, timedelta, timezone
from pathlib import Path
from unittest import mock

import boto3
import pytest
from hypothesis import HealthCheck, given, settings, strategies as st
from moto import mock_aws

from logstead.adapters.s3_files import S3FileAdapter
from logstead.repository import keys
from logstead.repository.dynamo_repo import DynamoRepository
from logstead.router import handler as handler_module
from logstead.router.handler import handler
from logstead.services.activity import ActivityRecorder, NewEvent

TABLE = "Logstead"
BUCKET = "logstead-files-isolation"
REGION = "us-east-1"
SUB = "user-iso-1"
NOW = datetime(2025, 6, 1, tzinfo=timezone.utc)

_SRC = Path(__file__).resolve().parents[2] / "src" / "logstead" / "services"
_SCANNED = (
    "report.py",
    "report_pdf.py",
    "dashboard.py",
    "carryforward.py",
    "loan.py",
    "depreciation.py",
    "transaction.py",
    "itemized.py",
    "property.py",
    "backup.py",
    "schedule_e_import.py",
    "expense_import.py",
)

_UUID = re.compile(r"[0-9a-f]{8}-?[0-9a-f]{4}-?[0-9a-f]{4}-?[0-9a-f]{4}-?[0-9a-f]{12}")
_STAMP = re.compile(r"\d{4}-\d{2}-\d{2}T[\d:.]+(?:Z|\+00:00)?")


# --- Source scan (Requirements 19.1, 20.3) -------------------------------------


def _imports_activity(tree: ast.AST) -> list[str]:
    found: list[str] = []
    for node in ast.walk(tree):
        if isinstance(node, ast.Import):
            found += [a.name for a in node.names if "activity" in a.name.split(".")[-1]]
        elif isinstance(node, ast.ImportFrom):
            mod = node.module or ""
            if "activity" in mod.split("."):
                found.append(mod)
            found += [f"{mod}.{a.name}" for a in node.names if a.name.startswith("activity")
                      or a.name in ("ActivityRecorder", "ActivityService")]
    return found


@pytest.mark.parametrize("name", _SCANNED)
def test_services_do_not_import_activity(name: str) -> None:
    source = (_SRC / name).read_text(encoding="utf-8")
    assert _imports_activity(ast.parse(source)) == []
    assert "ActivityRecorder" not in source and "ActivityService" not in source


# --- Harness -------------------------------------------------------------------


def _gsi(name: str) -> dict:
    return {
        "IndexName": name,
        "KeySchema": [
            {"AttributeName": f"{name}PK", "KeyType": "HASH"},
            {"AttributeName": f"{name}SK", "KeyType": "RANGE"},
        ],
        "Projection": {"ProjectionType": "ALL"},
    }


@contextmanager
def _fresh_wired():
    with mock_aws():
        ddb = boto3.client("dynamodb", region_name=REGION)
        ddb.create_table(
            TableName=TABLE,
            AttributeDefinitions=[
                {"AttributeName": a, "AttributeType": "S"}
                for a in ("PK", "SK", "GSI1PK", "GSI1SK", "GSI2PK", "GSI2SK")
            ],
            KeySchema=[
                {"AttributeName": "PK", "KeyType": "HASH"},
                {"AttributeName": "SK", "KeyType": "RANGE"},
            ],
            GlobalSecondaryIndexes=[_gsi("GSI1"), _gsi("GSI2")],
            BillingMode="PAY_PER_REQUEST",
        )
        s3 = boto3.client("s3", region_name=REGION)
        s3.create_bucket(Bucket=BUCKET)
        repo = DynamoRepository(ddb, TABLE)
        handler_module.configure(repo=repo, files=S3FileAdapter(s3, BUCKET))
        try:
            yield ddb, repo
        finally:
            handler_module.reset_wiring()


def _call(method: str, path: str, body=None, query=None) -> dict:
    event: dict = {
        "requestContext": {
            "http": {"method": method, "path": path},
            "authorizer": {"jwt": {"claims": {"sub": SUB}}},
        },
        "rawPath": path,
    }
    if body is not None:
        event["body"] = json.dumps(body)
    if query:
        event["queryStringParameters"] = query
    return handler(event)


class _Norm:
    """Replace generated ids and timestamps with stable placeholders (first-seen order)."""

    def __init__(self) -> None:
        self._ids: dict[str, str] = {}

    def __call__(self, text: str) -> str:
        def sub(m: re.Match) -> str:
            return self._ids.setdefault(m.group(0), f"ID{len(self._ids)}")

        return _STAMP.sub("TS", _UUID.sub(sub, text))


def _stored_without_activity(ddb) -> list[str]:
    items: list[dict] = []
    kwargs: dict = {"TableName": TABLE}
    while True:
        page = ddb.scan(**kwargs)
        items += page["Items"]
        if "LastEvaluatedKey" not in page:
            break
        kwargs["ExclusiveStartKey"] = page["LastEvaluatedKey"]
    return [
        json.dumps(i, sort_keys=True)
        for i in items
        if not i["SK"]["S"].startswith(keys.ACT_PREFIX)
    ]


def _normalized_stored(ddb, norm: _Norm) -> list[str]:
    return sorted(norm(s) for s in _stored_without_activity(ddb))


def _money(cents: int) -> str:
    return f"{cents // 100}.{cents % 100:02d}"


_cents = st.integers(1, 5_000_000)
_ops = st.fixed_dictionaries(
    {
        "income": _cents,
        "expense": _cents,
        "asset": _cents,
        "loan": st.integers(100_000, 30_000_000),  # pays off within 600 payments
        "new_expense": _cents,
        "delete_asset": st.booleans(),
        "description": st.text(max_size=20).filter(lambda s: s.strip() == s and s != ""),
    }
)


def _mutations(ops: dict) -> list[tuple[int, str]]:
    """Run a mutation sequence through the real handler; return (status, body)."""
    out: list[tuple[int, str]] = []

    def call(method, path, body=None, query=None):
        r = _call(method, path, body, query)
        out.append((r["statusCode"], r.get("body") or ""))
        return r

    prop = call("POST", "/properties", {"name": "Maple", "address_text": "1 Maple St"})
    pid = json.loads(prop["body"])["id"]
    call(
        "POST", f"/properties/{pid}/transactions",
        {"date": "2024-05-01", "amount": _money(ops["income"]), "type": "income",
         "category_id": "rents-received", "description": ops["description"]},
    )
    exp = call(
        "POST", f"/properties/{pid}/transactions",
        {"date": "2024-05-02", "amount": _money(ops["expense"]), "type": "expense",
         "category_id": "repairs", "description": "Fix"},
    )
    tid = json.loads(exp["body"])["id"]
    call(
        "PUT", f"/properties/{pid}/transactions/{tid}",
        {"date": "2024-05-03", "amount": _money(ops["new_expense"]), "type": "expense",
         "category_id": "repairs", "description": "Fix again"},
    )
    asset = call(
        "POST", f"/properties/{pid}/assets",
        {"description": "HVAC", "cost_basis": _money(ops["asset"]),
         "placed_in_service_date": "2023-01-10"},
    )
    call(
        "POST", f"/properties/{pid}/loans",
        {"description": "Mortgage", "annual_interest_rate": "6.875",
         "monthly_payment": "1970.79", "anchor_balance": _money(ops["loan"]),
         "anchor_date": "2024-06-01", "original_principal": "300000.00",
         "closing_date": "2022-02-14"},
    )
    if ops["delete_asset"] and asset["statusCode"] == 201:
        call("DELETE", f"/properties/{pid}/assets/{json.loads(asset['body'])['id']}")
    call("DELETE", f"/properties/{pid}/transactions/{tid}")
    return out


def _reads(pid: str) -> list[tuple[int, str]]:
    out = []
    for method, path, query in (
        ("GET", f"/properties/{pid}/report", {"taxYear": "2024"}),
        ("GET", "/reports/combined", {"taxYear": "2024"}),
        ("GET", "/dashboard", {"taxYear": "2024"}),
        ("GET", "/dashboard/properties", {"taxYear": "2024"}),
        ("GET", "/carryforward", None),
        ("GET", "/backup", None),
    ):
        r = _call(method, path, None, query)
        body = r.get("body") or ""
        if path == "/backup":
            body = re.sub(r'"exported_at":\s*"[^"]*"', '"exported_at":"T"', body)
        out.append((r["statusCode"], body))
    return out


# --- Property 24 ---------------------------------------------------------------

_event = st.builds(
    NewEvent,
    action=st.sampled_from(["create", "update", "delete", "restore", "import"]),
    entity=st.sampled_from(["transaction", "asset", "loan", "property", "backup"]),
    summary=st.text(max_size=40),
    record_id=st.one_of(st.none(), st.just("r1")),
    property_id=st.none(),
    before=st.one_of(st.none(), st.dictionaries(st.sampled_from(["amount", "description"]),
                                                 st.text(max_size=20), max_size=2)),
    after=st.one_of(st.none(), st.dictionaries(st.sampled_from(["amount", "description"]),
                                                st.text(max_size=20), max_size=2)),
)


@settings(max_examples=8, deadline=None, suppress_health_check=[HealthCheck.too_slow])
@given(ops=_ops, events=st.lists(_event, min_size=1, max_size=8), use_property=st.booleans())
def test_property_24_reports_ignore_activity(ops, events, use_property):
    """Reports and the export are identical with and without ACT# items present."""
    with _fresh_wired() as (ddb, repo):
        # Record the mutations with the real recorder, then drop the events so the
        # baseline has none, then compare against a table full of arbitrary events.
        _mutations(ops)
        pid = json.loads(_call("GET", "/properties")["body"])[0]["id"]
        ActivityRecorder(repo, SUB).purge_user()
        assert not repo.query(keys.user_pk(SUB), sk_begins_with=keys.ACT_PREFIX)

        norm = _Norm()
        before_reads = [(s, norm(b)) for s, b in _reads(pid)]
        before_stored = _normalized_stored(ddb, norm)

        for i, e in enumerate(events):
            at = NOW - timedelta(minutes=i)
            if use_property:
                e = NewEvent(**{**e.__dict__, "property_id": pid})
            ActivityRecorder(repo, SUB, clock=lambda at=at: at).record(e)
        assert repo.query(keys.user_pk(SUB), sk_begins_with=keys.ACT_PREFIX)

        after_reads = [(s, norm(b)) for s, b in _reads(pid)]
        assert after_reads == before_reads
        assert all(s == 200 for s, _ in after_reads)
        assert _normalized_stored(ddb, norm) == before_stored
        # Req 19.3: no attribute on the property item mentions activity.
        for raw in _stored_without_activity(ddb):
            assert "ACT#" not in raw and "eventId" not in raw


@settings(max_examples=6, deadline=None, suppress_health_check=[HealthCheck.too_slow])
@given(ops=_ops)
def test_property_24_stored_items_same_with_recorder_disabled(ops):
    """The stored records after a mutation sequence do not depend on the recorder."""

    class _Off:
        def record(self, event):  # noqa: ANN001
            return None

        def purge_user(self):
            return 0

        def purge_property(self, property_id):  # noqa: ANN001
            return 0

    results = []
    for enabled in (True, False):
        with _fresh_wired() as (ddb, repo):
            patch = (
                mock.patch.object(handler_module, "_activity_recorder", lambda w, u: _Off())
                if not enabled
                else mock.patch.object(handler_module, "_activity_recorder",
                                       handler_module._activity_recorder)
            )
            with patch:
                norm = _Norm()
                responses = [(s, norm(b)) for s, b in _mutations(ops)]
                acts = repo.query(keys.user_pk(SUB), sk_begins_with=keys.ACT_PREFIX)
                assert bool(acts) == enabled
                results.append((responses, _normalized_stored(ddb, norm)))
    assert results[0] == results[1]


# --- Property 25 ---------------------------------------------------------------


class _Boom:
    def record(self, event):  # noqa: ANN001
        raise RuntimeError("recorder down")

    def purge_user(self):
        raise RuntimeError("recorder down")

    def purge_property(self, property_id):  # noqa: ANN001
        raise RuntimeError("recorder down")


def _failure(mode: str):
    if mode == "put_fails":
        return mock.patch.object(DynamoRepository, "put_item", _put_item_failing_for_events())
    if mode == "build_fails":
        return mock.patch.object(ActivityRecorder, "_build", side_effect=RuntimeError("boom"))
    if mode == "recorder_raises":
        return mock.patch.object(handler_module, "_activity_recorder", lambda w, u: _Boom())
    if mode == "recorder_ctor_raises":
        def ctor(w, u):
            raise RuntimeError("no recorder")

        return mock.patch.object(handler_module, "_activity_recorder", ctor)
    raise AssertionError(mode)


def _put_item_failing_for_events():
    real = DynamoRepository.put_item

    def put_item(self, item, *args, **kwargs):  # noqa: ANN001
        if str(item.get("SK", "")).startswith(keys.ACT_PREFIX):
            raise RuntimeError("dynamo down")
        return real(self, item, *args, **kwargs)

    return put_item


@settings(max_examples=8, deadline=None, suppress_health_check=[HealthCheck.too_slow])
@given(
    ops=_ops,
    mode=st.sampled_from(["put_fails", "build_fails", "recorder_raises", "recorder_ctor_raises"]),
)
def test_property_25_recording_failure_is_invisible(ops, mode):
    runs = []
    for failing in (False, True):
        with _fresh_wired() as (ddb, repo):
            norm = _Norm()
            if failing:
                with _failure(mode), mock.patch.object(
                    logging.getLogger("logstead.services.activity"), "warning"
                ):
                    responses = [(s, norm(b)) for s, b in _mutations(ops)]
            else:
                responses = [(s, norm(b)) for s, b in _mutations(ops)]
            acts = repo.query(keys.user_pk(SUB), sk_begins_with=keys.ACT_PREFIX)
            if failing:
                assert acts == []
            else:
                assert acts
            runs.append((responses, _normalized_stored(ddb, norm)))
    assert runs[0] == runs[1]
    assert all(status in (200, 201, 204) for status, _ in runs[0][0])


def test_recorder_logs_warning_and_returns_on_failed_write() -> None:
    """Req 20.1: a failed write logs entity, action and error class, and returns."""

    class _Repo:
        def put_item(self, item):  # noqa: ANN001
            raise ValueError("nope")

    log = mock.Mock(spec=logging.Logger)
    ActivityRecorder(_Repo(), SUB, clock=lambda: NOW, log=log).record(
        NewEvent(action="create", entity="asset", summary="x")
    )
    log.warning.assert_called_once()
    rendered = log.warning.call_args.args[0] % log.warning.call_args.args[1:]
    assert "asset" in rendered and "create" in rendered and "ValueError" in rendered
