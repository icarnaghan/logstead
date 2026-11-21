"""Tests for the multi-field ``errors`` support on ``Error`` / ``Result``.

Validates: Requirements 1.3, 8.9
"""

from __future__ import annotations

from logstead.models.result import Error, Result
from logstead.router.handler import _error_body


def test_error_errors_defaults_to_empty():
    err = Error(kind="validation", message="bad")
    assert err.errors == ()


def test_failure_without_errors_defaults_to_empty():
    result = Result.failure("validation", "bad", field="rate")
    assert result.error is not None
    assert result.error.errors == ()
    assert result.error.field == "rate"


def test_failure_passes_errors_through():
    pairs = (("rate", "must be positive"), ("term", "must be > 0"))
    result = Result.failure("validation", "must be positive", "rate", pairs)
    assert result.error is not None
    assert result.error.errors == pairs


def test_error_body_omits_errors_when_empty():
    body = _error_body(Error(kind="validation", message="bad", field="rate"))
    assert body == {"error": "validation", "message": "bad", "field": "rate"}
    assert "errors" not in body


def test_error_body_emits_errors_and_keeps_first_field_message():
    pairs = (("rate", "must be positive"), ("term", "must be > 0"))
    result = Result.failure("validation", "must be positive", "rate", pairs)
    assert result.error is not None
    body = _error_body(result.error)
    assert body["field"] == "rate"
    assert body["message"] == "must be positive"
    assert body["errors"] == [
        {"field": "rate", "message": "must be positive"},
        {"field": "term", "message": "must be > 0"},
    ]
    assert body["errors"][0] == {"field": body["field"], "message": body["message"]}
