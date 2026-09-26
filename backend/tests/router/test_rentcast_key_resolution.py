"""Tests for RentCast API key resolution (SSM SecureString, env fallback).

The key is a secret, so production reads it from an SSM SecureString parameter
at runtime rather than a plaintext Lambda env var. A direct RENTCAST_API_KEY
env var still wins (local/dev/tests), and any SSM failure degrades to None so
wiring never crashes (enrichment then 503s).
"""

from __future__ import annotations

import sys
import types

import pytest

from logstead.router import handler as h


@pytest.fixture(autouse=True)
def clean_env(monkeypatch):
    monkeypatch.delenv("RENTCAST_API_KEY", raising=False)
    monkeypatch.delenv("RENTCAST_API_KEY_PARAM", raising=False)
    monkeypatch.setenv("AWS_REGION", "us-east-1")


def test_direct_env_var_wins(monkeypatch):
    monkeypatch.setenv("RENTCAST_API_KEY", "direct-key")
    monkeypatch.setenv("RENTCAST_API_KEY_PARAM", "/logstead/rentcast")  # ignored
    assert h._resolve_rentcast_key() == "direct-key"


def test_none_when_neither_configured():
    assert h._resolve_rentcast_key() is None


def test_reads_from_ssm_when_param_set(monkeypatch):
    monkeypatch.setenv("RENTCAST_API_KEY_PARAM", "/logstead/rentcast")

    calls = {}

    class _FakeSSM:
        def get_parameter(self, Name, WithDecryption):  # noqa: N803 (boto3 kwargs)
            calls["Name"] = Name
            calls["WithDecryption"] = WithDecryption
            return {"Parameter": {"Value": "ssm-secret-key"}}

    fake_boto3 = types.SimpleNamespace(client=lambda svc, region_name=None: _FakeSSM())
    monkeypatch.setitem(sys.modules, "boto3", fake_boto3)

    assert h._resolve_rentcast_key() == "ssm-secret-key"
    assert calls == {"Name": "/logstead/rentcast", "WithDecryption": True}


def test_ssm_failure_degrades_to_none(monkeypatch):
    monkeypatch.setenv("RENTCAST_API_KEY_PARAM", "/logstead/rentcast")

    class _BrokenSSM:
        def get_parameter(self, Name, WithDecryption):  # noqa: N803
            raise RuntimeError("access denied")

    fake_boto3 = types.SimpleNamespace(client=lambda svc, region_name=None: _BrokenSSM())
    monkeypatch.setitem(sys.modules, "boto3", fake_boto3)

    assert h._resolve_rentcast_key() is None


def test_ssm_empty_value_is_none(monkeypatch):
    monkeypatch.setenv("RENTCAST_API_KEY_PARAM", "/logstead/rentcast")

    class _EmptySSM:
        def get_parameter(self, Name, WithDecryption):  # noqa: N803
            return {"Parameter": {"Value": ""}}

    fake_boto3 = types.SimpleNamespace(client=lambda svc, region_name=None: _EmptySSM())
    monkeypatch.setitem(sys.modules, "boto3", fake_boto3)

    assert h._resolve_rentcast_key() is None
