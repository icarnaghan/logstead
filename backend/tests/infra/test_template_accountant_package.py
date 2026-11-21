"""Infra assertion tests for the accountant-package deltas to ``infra/template.yaml``.

Covers requirements 20.3 to 20.9 and 22.10: the package worker function and its
limits, its narrow policy, the API invoke and delete grants, the lifecycle rules
(including noncurrent-version expiry), the throttled routes, the asynchronous
invoke configuration, and that the CSP resource and the DynamoDB table are
unchanged from a recorded fingerprint.

CloudFormation ``!`` intrinsics are parsed into ``{"!Tag": value}`` mappings so
references stay comparable.
"""

from __future__ import annotations

import hashlib
import json
from pathlib import Path

import pytest
import yaml

TEMPLATE_PATH = Path(__file__).resolve().parents[3] / "infra" / "template.yaml"

# SHA-256 of the canonical JSON (sorted keys, intrinsics as {"!Tag": value}) of
# each resource, recorded before the accountant-package change. A change to
# either resource must be deliberate and update the value here.
CSP_POLICY_FINGERPRINT = "2b4d6bf796647719f1cb116c9ee5243a0bb9a6bd57a5ec851ec4831982d9cef0"
TABLE_FINGERPRINT = "3f0291150956e65b5c8dd173dfd9e4bbb4f377ac56d3aa23049bc26a538323f8"


class _CfnLoader(yaml.SafeLoader):
    pass


def _intrinsic(loader, tag_suffix, node):
    if isinstance(node, yaml.ScalarNode):
        value = loader.construct_scalar(node)
    elif isinstance(node, yaml.SequenceNode):
        value = loader.construct_sequence(node, deep=True)
    else:
        value = loader.construct_mapping(node, deep=True)
    return {"!" + tag_suffix: value}


_CfnLoader.add_multi_constructor("!", _intrinsic)


@pytest.fixture(scope="module")
def resources() -> dict:
    assert TEMPLATE_PATH.is_file(), f"template not found at {TEMPLATE_PATH}"
    doc = yaml.load(TEMPLATE_PATH.read_text(encoding="utf-8"), Loader=_CfnLoader)  # noqa: S506
    return doc["Resources"]


def _fingerprint(resource: dict) -> str:
    return hashlib.sha256(json.dumps(resource, sort_keys=True).encode()).hexdigest()


def _statements(function: dict) -> list[dict]:
    out: list[dict] = []
    for policy in function["Properties"]["Policies"]:
        if isinstance(policy, dict) and isinstance(policy.get("Statement"), list):
            out.extend(policy["Statement"])
    return out


def _as_list(value) -> list:
    return value if isinstance(value, list) else [value]


def _actions(statement: dict) -> list[str]:
    return _as_list(statement["Action"])


def _bucket_resources(statement: dict) -> list[str]:
    """Return the ``Fn::Sub`` strings of a statement's resources."""
    return [r["!Sub"] for r in _as_list(statement["Resource"])]


def test_worker_function_and_limits(resources: dict) -> None:
    fn = resources["PackageWorkerFunction"]
    assert fn["Type"] == "AWS::Serverless::Function"
    props = fn["Properties"]
    assert props["Timeout"] == 600
    assert props["MemorySize"] == 1024
    assert props["EphemeralStorage"]["Size"] == 1024
    assert props["ReservedConcurrentExecutions"] == 2
    assert props["CodeUri"] == resources["ApiFunction"]["Properties"]["CodeUri"]
    assert props["Handler"] != resources["ApiFunction"]["Properties"]["Handler"]
    assert fn["Metadata"]["BuildMethod"] == "makefile"
    assert set(props["Environment"]["Variables"]) == {"TABLE_NAME", "FILES_BUCKET"}


def test_worker_event_invoke_config(resources: dict) -> None:
    cfg = resources["PackageWorkerFunction"]["Properties"]["EventInvokeConfig"]
    assert cfg["MaximumRetryAttempts"] == 0
    assert cfg["MaximumEventAgeInSeconds"] == 300


def test_worker_policy_has_no_actions_beyond_those_listed(resources: dict) -> None:
    fn = resources["PackageWorkerFunction"]
    policies = fn["Properties"]["Policies"]
    # Only inline statements: no managed or SAM policy templates (those are
    # broader than the requirement allows).
    assert all(isinstance(p, dict) and set(p) == {"Statement"} for p in policies)

    by_action: dict[str, list[str]] = {}
    for stmt in _statements(fn):
        assert stmt["Effect"] == "Allow"
        for action in _actions(stmt):
            by_action[action] = [json.dumps(r, sort_keys=True) for r in _as_list(stmt["Resource"])]

    assert set(by_action) == {
        "dynamodb:GetItem",
        "dynamodb:Query",
        "dynamodb:PutItem",
        "s3:GetObject",
        "s3:PutObject",
        "s3:AbortMultipartUpload",
    }
    assert not any("*" == a or a.endswith(":*") for a in by_action)

    receipts = json.dumps({"!Sub": "${FilesBucket.Arn}/receipts/*"}, sort_keys=True)
    packages = json.dumps({"!Sub": "${FilesBucket.Arn}/exports/packages/*"}, sort_keys=True)
    assert by_action["s3:GetObject"] == [receipts]
    assert by_action["s3:PutObject"] == [packages]
    assert by_action["s3:AbortMultipartUpload"] == [packages]
    table_arns = [
        json.dumps({"!GetAtt": "LogsteadTable.Arn"}, sort_keys=True),
        json.dumps({"!Sub": "${LogsteadTable.Arn}/index/*"}, sort_keys=True),
    ]
    for action in ("dynamodb:GetItem", "dynamodb:Query", "dynamodb:PutItem"):
        assert by_action[action] == table_arns


def test_api_function_invoke_and_delete_grants(resources: dict) -> None:
    api = resources["ApiFunction"]
    env = api["Properties"]["Environment"]["Variables"]
    assert env["PACKAGE_WORKER_FUNCTION"] == {"!Ref": "PackageWorkerFunction"}

    statements = _statements(api)
    invoke = [s for s in statements if "lambda:InvokeFunction" in _actions(s)]
    assert len(invoke) == 1
    assert _actions(invoke[0]) == ["lambda:InvokeFunction"]
    assert _as_list(invoke[0]["Resource"]) == [{"!GetAtt": "PackageWorkerFunction.Arn"}]

    deletes = [s for s in statements if "s3:DeleteObject" in _actions(s)]
    assert len(deletes) == 1
    delete_resources = set(_bucket_resources(deletes[0]))
    assert "${FilesBucket.Arn}/exports/packages/*" in delete_resources
    assert "${FilesBucket.Arn}/exports/pdf/*" in delete_resources
    # exports/ as a whole must not be deletable.
    assert "${FilesBucket.Arn}/exports/*" not in delete_resources


def test_files_bucket_lifecycle_rules(resources: dict) -> None:
    rules = resources["FilesBucket"]["Properties"]["LifecycleConfiguration"]["Rules"]
    by_id = {r["Id"]: r for r in rules}
    assert len(by_id) == len(rules), "lifecycle rule ids must be unique"

    for rule_id, prefix in (
        ("ExpireAccountantPackages", "exports/packages/"),
        ("ExpireGeneratedPdfs", "exports/pdf/"),
    ):
        rule = by_id[rule_id]
        assert rule["Status"] == "Enabled"
        assert rule["Prefix"] == prefix
        assert int(rule["ExpirationInDays"]) == 1
        assert int(rule["NoncurrentVersionExpiration"]["NoncurrentDays"]) == 1

    # Existing rules stay as they were.
    assert int(by_id["ExpireExports"]["ExpirationInDays"]) == 30
    assert by_id["ExpireExports"]["Prefix"] == "exports/"
    assert by_id["ExpireScheduleEImports"]["Prefix"] == "imports/schedule-e/"
    assert "AbortIncompleteMultipartUploads" in by_id


@pytest.mark.parametrize(
    ("route", "event_name", "method", "path"),
    [
        (
            "POST /accountant-packages",
            "ThrottledPackageCreate",
            "POST",
            "/accountant-packages",
        ),
        (
            "POST /properties/{propertyId}/report/pdf",
            "ThrottledPropertyReportPdf",
            "POST",
            "/properties/{propertyId}/report/pdf",
        ),
        (
            "POST /reports/combined/pdf",
            "ThrottledCombinedReportPdf",
            "POST",
            "/reports/combined/pdf",
        ),
        (
            "GET /search",
            "ThrottledSearch",
            "GET",
            "/search",
        ),
    ],
)
def test_new_routes_are_explicit_and_throttled(
    resources: dict, route: str, event_name: str, method: str, path: str
) -> None:
    event = resources["ApiFunction"]["Properties"]["Events"][event_name]
    assert event["Type"] == "HttpApi"
    assert event["Properties"]["Method"] == method
    assert event["Properties"]["Path"] == path
    assert event["Properties"]["ApiId"] == {"!Ref": "HttpApi"}
    # No Auth override: the default Cognito JWT authorizer applies.
    assert "Auth" not in event["Properties"]

    settings = resources["HttpApi"]["Properties"]["RouteSettings"][route]
    assert settings["ThrottlingRateLimit"] > 0
    assert settings["ThrottlingBurstLimit"] >= settings["ThrottlingRateLimit"]
    assert settings["DetailedMetricsEnabled"] is True
    if route == "GET /search":
        assert settings["ThrottlingRateLimit"] == 2
        assert settings["ThrottlingBurstLimit"] == 5


def test_worker_errors_alarm(resources: dict) -> None:
    alarm = resources["PackageWorkerErrorsAlarm"]["Properties"]
    assert alarm["MetricName"] == "Errors"
    assert alarm["Dimensions"] == [{"Name": "FunctionName", "Value": {"!Ref": "PackageWorkerFunction"}}]


def test_csp_resource_and_table_are_unchanged(resources: dict) -> None:
    assert _fingerprint(resources["SpaResponseHeadersPolicy"]) == CSP_POLICY_FINGERPRINT
    assert _fingerprint(resources["LogsteadTable"]) == TABLE_FINGERPRINT
