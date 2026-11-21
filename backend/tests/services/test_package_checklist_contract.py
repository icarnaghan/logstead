"""Checklist import contract for the accountant package (task 5.7).

Requirements 11.2, 11.3, 11.4, 11.6, 11.7. The provider-side contract lives in
``test_checklist_provider_contract.py``; this file covers the built package.
"""
from __future__ import annotations

import json
import sys
import types
import zipfile
from datetime import datetime, timezone

import pytest
from moto import mock_aws

from logstead.models.result import Result
from logstead.router.handler import _Wiring, build_package_service
from logstead.services.accountant_package import (
    PackageBuilder,
    default_checklist_provider,
)
from tests.services.test_imported_marker_update_property import USER_ID, _Env

YEAR = 2023
MODULE = "logstead.services.checklist"
NOT_AVAILABLE = "not available in this release"
FAILED = "could not be generated"


@pytest.fixture
def env():
    with mock_aws():
        yield _Env()


def _build(env, tmp_path, user=USER_ID) -> tuple[dict, list[str]]:
    wiring = _Wiring(env.repo, env.files, None, None)
    svc = build_package_service(wiring, user)
    builder = PackageBuilder(
        svc.reports, svc.itemized, svc.transactions, svc.properties, env.files,
        default_checklist_provider(wiring, user),
        lambda: datetime(2024, 1, 15, tzinfo=timezone.utc),
    )
    path = str(tmp_path / "out.zip")
    builder.build(YEAR, [env.property_id], path)
    with zipfile.ZipFile(path) as zf:
        manifest = json.loads(zf.read("manifest.json"))
        names = zf.namelist()
        checklist = {n: json.loads(zf.read(n)) for n in names if n.startswith("checklist/")}
    manifest["_checklist_files"] = checklist
    return manifest, names


class _StubProvider:
    def checklist_for(self, property_id, tax_year):
        return Result.success({"property": property_id, "year": tax_year})


def _stub_module(provider_for=None) -> types.ModuleType:
    module = types.ModuleType(MODULE)
    if provider_for is not None:
        module.provider_for = provider_for
    return module


def test_real_module_adds_checklist_file(env, tmp_path):
    manifest, names = _build(env, tmp_path)
    path = f"checklist/year-end-checklist-{YEAR}.json"
    assert path in names
    assert manifest["sections"]["checklist"] == {"included": True, "path": path}
    body = manifest["_checklist_files"][path]
    assert body["tax_year"] == YEAR
    assert [p["property_id"] for p in body["properties"]] == [env.property_id]
    assert {f["path"] for f in manifest["files"]} >= {path}


def test_stub_module_provider_is_returned_and_used(env, tmp_path, monkeypatch):
    stub = _StubProvider()
    seen = []

    def provider_for(wiring, user):
        seen.append((wiring, user))
        return stub

    monkeypatch.setitem(sys.modules, MODULE, _stub_module(provider_for))
    wiring = _Wiring(env.repo, env.files, None, None)
    assert default_checklist_provider(wiring, USER_ID) is stub
    manifest, names = _build(env, tmp_path)
    assert seen and seen[-1][1] == USER_ID
    path = f"checklist/year-end-checklist-{YEAR}.json"
    assert path in names
    assert manifest["_checklist_files"][path]["properties"][0]["checklist"] == {
        "property": env.property_id,
        "year": YEAR,
    }


def test_hidden_module_completes_with_reason(env, tmp_path, monkeypatch):
    monkeypatch.setitem(sys.modules, MODULE, None)
    manifest, names = _build(env, tmp_path)
    assert manifest["sections"]["checklist"] == {"included": False, "reason": NOT_AVAILABLE}
    assert not any(n.startswith("checklist/") for n in names)


def test_module_without_provider_for_completes_with_reason(env, tmp_path, monkeypatch):
    monkeypatch.setitem(sys.modules, MODULE, _stub_module())
    manifest, names = _build(env, tmp_path)
    assert manifest["sections"]["checklist"] == {"included": False, "reason": NOT_AVAILABLE}
    assert not any(n.startswith("checklist/") for n in names)


def test_provider_for_raising_completes_with_reason(env, tmp_path, monkeypatch):
    def boom(wiring, user):
        raise RuntimeError("boom")

    monkeypatch.setitem(sys.modules, MODULE, _stub_module(boom))
    manifest, names = _build(env, tmp_path)
    assert manifest["sections"]["checklist"] == {"included": False, "reason": NOT_AVAILABLE}
    assert not any(n.startswith("checklist/") for n in names)


@pytest.mark.parametrize("mode", ["raises", "fails"])
def test_failing_checklist_for_records_failed_reason(env, tmp_path, monkeypatch, mode):
    class Bad:
        def checklist_for(self, property_id, tax_year):
            if mode == "raises":
                raise RuntimeError("boom")
            return Result.failure("not_found", "nope")

    monkeypatch.setitem(sys.modules, MODULE, _stub_module(lambda w, u: Bad()))
    manifest, names = _build(env, tmp_path)
    assert manifest["sections"]["checklist"] == {"included": False, "reason": FAILED}
    assert not any(n.startswith("checklist/") for n in names)
