"""Example tests for the public report serializers and CSV formula
neutralization (Requirements 8.4, 9.6)."""
from __future__ import annotations

import csv
import io
import json
from decimal import Decimal

import pytest

from logstead.models.property import PropertyInput
from logstead.models.transaction import TransactionInput
from logstead.services.report import serialize_combined, serialize_report

from tests.integration.test_report_export import (  # noqa: F401 - fixtures
    TAX_YEAR,
    aws,
    depreciation,
    files,
    properties,
    repo,
    s3_client,
    service,
    transactions,
)


def _prop(properties, name: str, address: str) -> str:
    r = properties.create(
        PropertyInput(name=name, address_text=address, property_type="single_family")
    )
    assert r.is_ok, r.error
    return r.value.id


def _other(transactions, pid: str, description: str) -> None:
    r = transactions.create(
        TransactionInput(
            property_id=pid,
            date="2024-05-05",
            amount=Decimal("10.00"),
            type="expense",
            category_id="other",
            description=description,
        )
    )
    assert r.is_ok, r.error


def _rows(data: bytes) -> list[list[str]]:
    return list(csv.reader(io.StringIO(data.decode("utf-8"))))


def test_serialize_report_csv_prefixes_formula_text_cells(
    service, properties, transactions
):
    pid = _prop(properties, "=SUM(A1)", "@home")
    _other(transactions, pid, "+cmd")
    report = service.report_for(pid, TAX_YEAR).value

    rows = _rows(serialize_report(report, "csv"))

    assert ["Property", "'=SUM(A1)"] in rows
    assert ["Address", "'@home"] in rows
    assert any(r and r[0] == "'+cmd" for r in rows)


def test_serialize_report_csv_leaves_ordinary_text_unchanged(
    service, properties, transactions
):
    pid = _prop(properties, "Maple", "1 Oak St")
    _other(transactions, pid, "HOA dues")
    report = service.report_for(pid, TAX_YEAR).value

    rows = _rows(serialize_report(report, "csv"))

    assert ["Property", "Maple"] in rows
    assert any(r and r[0] == "HOA dues" for r in rows)
    assert not any(c.startswith("'") for r in rows for c in r)


def test_serialize_report_json_is_not_neutralized(service, properties):
    pid = _prop(properties, "=SUM(A1)", "1 Oak St")
    report = service.report_for(pid, TAX_YEAR).value

    payload = json.loads(serialize_report(report, "json"))

    assert "'=SUM(A1)" not in json.dumps(payload)
    assert "=SUM(A1)" in json.dumps(payload)


def test_serialize_combined_csv_and_json(service, properties):
    p1 = _prop(properties, "-neg", "1 Oak St")
    p2 = _prop(properties, "Plain", "2 Oak St")
    report = service.combined_report([p1, p2], TAX_YEAR).value

    csv_rows = _rows(serialize_combined(report, "csv"))
    assert ["Property", "'-neg"] in csv_rows
    assert ["Property", "Plain"] in csv_rows
    assert any(r and r[0] == "Portfolio Totals" for r in csv_rows)

    payload = json.loads(serialize_combined(report, "json"))
    assert payload["tax_year"] == TAX_YEAR
    assert len(payload["properties"]) == 2
