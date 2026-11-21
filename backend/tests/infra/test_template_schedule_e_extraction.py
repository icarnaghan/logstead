"""Infra assertion tests for the Schedule E PDF extraction deltas.

Parses ``infra/template.yaml`` and asserts the three infrastructure additions
required by the schedule-e-pdf-extraction design ("Infra / IAM deltas" and the
Extraction_Job TTL note):

1. ``FilesBucket`` carries the ``ExpireScheduleEImports`` lifecycle rule on the
   ``imports/schedule-e/`` prefix with a 1-day expiry (Req 10.3 backstop).
2. ``ApiFunction`` has a policy statement granting the two Textract async
   document-analysis actions (Req 2.1).
3. The ``Logstead`` table enables DynamoDB TTL on the ``ttl`` attribute
   (Req 10.3 / 11.1, the Extraction_Job sparse TTL).

The template uses SAM/CloudFormation intrinsics (``!Sub``, ``!If``, ``!Ref``,
``!GetAtt``), so a plain ``yaml.safe_load`` would choke on the ``!`` tags. We
register a permissive multi-constructor that turns every unknown ``!Tag`` into
a plain mapping/scalar so the structure parses. When PyYAML is unavailable we
fall back to robust text assertions so the test still provides real coverage.
"""

from __future__ import annotations

from pathlib import Path

import pytest

# infra/template.yaml lives at <repo>/infra/template.yaml; this file is at
# <repo>/backend/tests/infra/, so walk up three parents to the repo root.
TEMPLATE_PATH = Path(__file__).resolve().parents[3] / "infra" / "template.yaml"


@pytest.fixture(scope="module")
def template_text() -> str:
    assert TEMPLATE_PATH.is_file(), f"template not found at {TEMPLATE_PATH}"
    return TEMPLATE_PATH.read_text(encoding="utf-8")


def _load_template(text: str):
    """Parse the SAM template, tolerating CloudFormation ``!`` intrinsic tags.

    Returns the parsed dict, or ``None`` if PyYAML is not installed.
    """
    try:
        import yaml  # noqa: PLC0415 - optional dependency, imported lazily
    except ImportError:
        return None

    class _CfnLoader(yaml.SafeLoader):
        pass

    def _any_tag(loader, tag_suffix, node):  # noqa: ARG001
        if isinstance(node, yaml.ScalarNode):
            return loader.construct_scalar(node)
        if isinstance(node, yaml.SequenceNode):
            return loader.construct_sequence(node)
        return loader.construct_mapping(node)

    # Handle both `!Ref foo` (short) and `!Ref` forms for every intrinsic.
    _CfnLoader.add_multi_constructor("!", _any_tag)

    return yaml.load(text, Loader=_CfnLoader)  # noqa: S506 - custom safe loader


# --------------------------------------------------------------------------- #
# Structured (PyYAML) assertions - the preferred, real YAML checks.
# --------------------------------------------------------------------------- #


def test_files_bucket_has_schedule_e_expire_rule(template_text: str) -> None:
    doc = _load_template(template_text)
    if doc is None:
        pytest.skip("PyYAML not installed; see text-based test below")

    rules = doc["Resources"]["FilesBucket"]["Properties"][
        "LifecycleConfiguration"
    ]["Rules"]
    matching = [r for r in rules if r.get("Id") == "ExpireScheduleEImports"]
    assert len(matching) == 1, "expected exactly one ExpireScheduleEImports rule"

    rule = matching[0]
    assert rule["Status"] == "Enabled"
    assert rule["Prefix"] == "imports/schedule-e/"
    # ExpirationInDays may parse as int 1 or str "1" depending on quoting.
    assert int(rule["ExpirationInDays"]) == 1

    # The pre-existing ExpireExports rule must remain untouched (regression).
    assert any(r.get("Id") == "ExpireExports" for r in rules)


def test_api_function_grants_textract_async_actions(template_text: str) -> None:
    doc = _load_template(template_text)
    if doc is None:
        pytest.skip("PyYAML not installed; see text-based test below")

    policies = doc["Resources"]["ApiFunction"]["Properties"]["Policies"]

    found_actions: set[str] = set()
    for policy in policies:
        if not isinstance(policy, dict):
            continue
        statements = policy.get("Statement")
        if not isinstance(statements, list):
            continue
        for stmt in statements:
            if not isinstance(stmt, dict):
                continue
            actions = stmt.get("Action", [])
            if isinstance(actions, str):
                actions = [actions]
            found_actions.update(actions)

    assert "textract:StartDocumentAnalysis" in found_actions
    assert "textract:GetDocumentAnalysis" in found_actions


def test_logstead_table_enables_ttl_on_ttl_attribute(template_text: str) -> None:
    doc = _load_template(template_text)
    if doc is None:
        pytest.skip("PyYAML not installed; see text-based test below")

    table = doc["Resources"]["LogsteadTable"]["Properties"]
    ttl = table["TimeToLiveSpecification"]
    assert ttl["AttributeName"] == "ttl"
    # Enabled may parse as bool True or str "true".
    enabled = ttl["Enabled"]
    assert enabled is True or str(enabled).lower() == "true"


# --------------------------------------------------------------------------- #
# Text-based fallback - always runs, so the deltas are covered even without
# PyYAML in the environment.
# --------------------------------------------------------------------------- #


def test_template_text_contains_extraction_deltas(template_text: str) -> None:
    # Textract IAM actions.
    assert "textract:StartDocumentAnalysis" in template_text
    assert "textract:GetDocumentAnalysis" in template_text

    # S3 lifecycle rule for the schedule-e import uploads.
    assert "ExpireScheduleEImports" in template_text
    assert "imports/schedule-e/" in template_text

    # DynamoDB TTL on the `ttl` attribute.
    assert "TimeToLiveSpecification" in template_text
    assert "AttributeName: ttl" in template_text
