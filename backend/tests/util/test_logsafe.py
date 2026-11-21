"""Logging audit (task 4.4): exception values must not reach the logs."""

from __future__ import annotations

import logging

from logstead.adapters.pdf_parse import parse_expense_summary
from logstead.util.logsafe import exc_summary

SECRET = "123 Secret St $98765.43 Bearer eyJhbGciOi"


def test_exc_summary_has_types_and_location_but_no_message() -> None:
    try:
        try:
            raise KeyError(SECRET)
        except KeyError as inner:
            raise RuntimeError(SECRET) from inner
    except RuntimeError as exc:
        text = exc_summary(exc)
    assert "RuntimeError" in text and "KeyError" in text
    assert "test_logsafe.py" in text
    assert "Secret" not in text and "98765" not in text


def test_pdf_extractor_failure_logs_no_document_text(caplog) -> None:
    def boom(_b: bytes):
        raise ValueError(SECRET)

    with caplog.at_level(logging.DEBUG):
        parse_expense_summary(b"%PDF", extract_text=boom)
    assert "ValueError" in caplog.text
    assert "Secret" not in caplog.text and "98765" not in caplog.text
