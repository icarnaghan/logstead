"""Provider contract test for ``logstead.services.checklist.provider_for``.

Requirements 24.1 to 24.6 (year-end checklist task 5.5).
"""
from __future__ import annotations

import importlib
import inspect
import sys

import pytest
from moto import mock_aws

from logstead.models.user import UserContext
from logstead.router.handler import _Wiring
from logstead.services import checklist as checklist_module
from logstead.services.checklist import provider_for
from tests.services.test_checklist_read_only_property import (
    _RecordingFiles,
    _RecordingRepo,
)
from tests.services.test_imported_marker_update_property import USER_ID, _Env

YEAR = 2023


@pytest.fixture
def env():
    with mock_aws():
        yield _Env()


def _wiring(env: _Env, repo=None, files=None) -> _Wiring:
    return _Wiring(
        repo if repo is not None else env.repo,
        files if files is not None else env.files,
        None,
        None,
    )


def test_signature_is_wiring_user():
    assert list(inspect.signature(provider_for).parameters) == ["wiring", "user"]


@pytest.mark.parametrize("as_context", [True, False])
def test_provider_matches_service_and_writes_nothing(env, as_context):
    repo = _RecordingRepo(env.repo)
    files = _RecordingFiles(env.files)
    wiring = _wiring(env, repo, files)
    user = UserContext(user_id=USER_ID) if as_context else USER_ID

    provider = provider_for(wiring, user)
    assert callable(provider.checklist_for)
    # Requirement 24.3: nothing is read or written until checklist_for is called.
    assert repo.writes == []
    assert files.calls == []

    from logstead.router.handler import _checklist_service

    expected = _checklist_service(wiring, user).checklist_for(env.property_id, YEAR)
    actual = provider.checklist_for(env.property_id, YEAR)
    assert expected.is_ok, expected.error
    assert actual.is_ok, actual.error
    assert actual.value == expected.value
    assert repo.writes == []
    assert files.calls == []


def test_missing_collaborator_raises(env):
    wiring = _wiring(env)
    wiring.files = None  # the transaction service cannot be built
    with pytest.raises(Exception):
        provider_for(wiring, USER_ID)


# --- Optional accountant package import contract ---------------------------

from logstead.services import accountant_package


def test_checklist_module_importable_by_name():
    module = importlib.import_module("logstead.services.checklist")
    assert module is checklist_module
    assert callable(getattr(module, "provider_for"))


def test_accountant_package_uses_provider(env):
    pkg = accountant_package
    default = pkg.default_checklist_provider
    wiring = _wiring(env)
    provider = default(wiring, USER_ID)
    assert provider is not None
    assert callable(provider.checklist_for)


def test_accountant_package_tolerates_hidden_checklist_module(env, monkeypatch):
    pkg = accountant_package
    default = pkg.default_checklist_provider
    monkeypatch.setitem(sys.modules, "logstead.services.checklist", None)
    try:
        provider = default(_wiring(env), USER_ID)
    except Exception:  # the package must treat a failure as an absent checklist
        pytest.fail("default_checklist_provider raised for a hidden module")
    assert provider is None
