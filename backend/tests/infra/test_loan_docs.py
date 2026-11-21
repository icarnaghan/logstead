"""Documentation and key-discipline tests for the mortgage loan feature.

Checks that the docs describe the Loan entity, keys, routes and backup
treatment, that ``keys.py`` lists the Loan entities, that services never build
raw ``LOAN#`` style strings (only ``repository/keys.py`` does), and that the
CHANGELOG records the feature (Requirements 12.1, 12.7).
"""

from __future__ import annotations

import re
from pathlib import Path

import pytest

REPO_ROOT = Path(__file__).resolve().parents[3]
SRC = REPO_ROOT / "backend" / "src" / "logstead"
SERVICES = SRC / "services"
KEYS_PY = SRC / "repository" / "keys.py"

# A raw loan key literal: a string whose text starts with a loan prefix or
# contains the year marker, e.g. "LOAN#", f"LOAN#{id}", "#YEAR#", "LOANYR#".
_RAW_KEY = re.compile(r"""["'](?:LOAN#|LOANYR#|[^"'\n]*#YEAR#)""")


def _read(path: Path) -> str:
    assert path.is_file(), f"missing {path}"
    return path.read_text(encoding="utf-8")


def _headings(text: str) -> list[str]:
    return [m.group(2).strip() for m in re.finditer(r"^(#{1,6})\s+(.*)$", text, re.M)]


def test_data_model_has_required_headings() -> None:
    headings = _headings(_read(REPO_ROOT / "docs" / "data-model.md"))
    for required in (
        "Loan entity",
        "Loan attributes (anchor shape)",
        "Override_Only_Rollup row",
        "Loan key prefixes",
        "Line 12 precedence rule",
        "Loan backup treatment",
        "Loan input model change",
    ):
        assert required in headings, f"data-model.md lacks heading {required!r}"


def test_data_model_describes_anchor_shape_only() -> None:
    text = _read(REPO_ROOT / "docs" / "data-model.md")
    for token in ("`monthlyPayment`", "`anchorBalance`", "`anchorDate`"):
        assert token in text
    for removed in ("`termMonths`", "`firstPaymentDate`", "`paymentOverride`"):
        assert removed not in text


def test_data_model_mentions_loan_keys() -> None:
    text = _read(REPO_ROOT / "docs" / "data-model.md")
    for token in ("LOAN#<loanId>", "LOAN#<loanId>#YEAR#<taxYear>", "LOANYR#"):
        assert token in text


def test_api_doc_lists_loan_routes() -> None:
    text = _read(REPO_ROOT / "docs" / "api.md")
    for route in (
        "/properties/{propertyId}/loans",
        "/properties/{propertyId}/loans/line-12-impact",
        "/properties/{propertyId}/loans/{loanId}",
        "/properties/{propertyId}/loans/{loanId}/schedule",
        "/properties/{propertyId}/loans/{loanId}/interest-overrides/{taxYear}",
    ):
        assert f"`{route}`" in text, f"api.md lacks route {route}"


def test_keys_docstring_lists_loan_entities() -> None:
    doc = _read(KEYS_PY).split('"""')[1]
    assert "SK=LOAN#<loanId>" in doc
    assert "SK=LOAN#<loanId>#YEAR#<taxYear>" in doc
    assert "LoanYearRollup" in doc
    assert "GSI2SK=LOANYR#<loanId>" in doc


def test_loan_service_builds_no_raw_pk_or_sk_strings() -> None:
    source = _read(SERVICES / "loan.py")
    offenders = [
        line.strip()
        for line in source.splitlines()
        if not line.lstrip().startswith("#") and _RAW_KEY.search(line)
    ]
    assert offenders == []
    assert "keys.loan_sk(" in source and "keys.loan_year_sk(" in source


@pytest.mark.parametrize(
    "path", sorted(SERVICES.glob("*.py")), ids=lambda p: p.name
)
def test_no_service_builds_raw_loan_keys(path: Path) -> None:
    offenders = [
        line.strip()
        for line in _read(path).splitlines()
        if not line.lstrip().startswith("#") and _RAW_KEY.search(line)
    ]
    assert offenders == []


def test_changelog_has_loan_entries() -> None:
    text = _read(REPO_ROOT / "CHANGELOG.md")
    unreleased = text.split("## [Unreleased]", 1)[1].split("\n## [", 1)[0]
    for phrase in (
        "Loans projected from a known balance",
        "Loan routes",
        "Loans in backup and restore",
        "Line 12 uses loan interest",
        "A property with loans cannot be deleted",
    ):
        assert phrase in unreleased, f"CHANGELOG lacks {phrase!r}"
