"""Logging audit (task 4.4): the catch-all 500 handler must not log values."""

from __future__ import annotations

import logging

from logstead.router import handler as handler_module
from logstead.router.handler import handler

from tests.router.test_handler_smoke import (  # noqa: F401 - fixtures
    _auth_claims,
    _event,
    aws,
    repo,
    wired,
)

SECRET = "123 Secret St $98765.43 Bearer eyJhbGciOi"


def test_unhandled_error_logs_type_not_message(wired, monkeypatch, caplog) -> None:
    def boom(_event):
        raise ValueError(SECRET)

    monkeypatch.setattr(handler_module, "_parse_body", boom)
    event = _event("POST", "/properties", claims=_auth_claims(), body={"name": "x"})
    event["headers"] = {"authorization": "Bearer eyJhbGciOi"}
    with caplog.at_level(logging.DEBUG):
        resp = handler(event, None)
    assert resp["statusCode"] == 500
    assert "ValueError" in caplog.text
    assert "Secret" not in caplog.text
    assert "98765" not in caplog.text
    assert "eyJhbGciOi" not in caplog.text
    assert "Secret" not in resp["body"]
