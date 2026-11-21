"""Property test: package report files agree with the report (task 5.5).

Feature: accountant-package, Property 7: Package files agree with the report

For generated state (properties, transactions, itemized Repairs entries, loans,
and assets) stored in moto, the amounts read from the package's Property_Pdf,
CSV, and JSON equal ``ReportingService.report_for`` line totals, totals, and
Line 12 fields, and the Repairs appendix line 14 equals report line 14.

**Validates: Requirements 2.1, 2.2, 8.3, 3.6**
"""

from __future__ import annotations

import csv
import io
import json
import re
import tempfile
import zipfile
from datetime import datetime, timezone
from decimal import Decimal

import boto3
from hypothesis import HealthCheck, given, settings
from hypothesis import strategies as st
from moto import mock_aws
from pypdf import PdfReader

from logstead.adapters.s3_files import S3FileAdapter
from logstead.models.depreciation import AssetInput
from logstead.models.loan import LoanInput
from logstead.models.property import PropertyInput
from logstead.models.transaction import TransactionInput
from logstead.repository.dynamo_repo import DynamoRepository
from logstead.services.accountant_package import PackageBuilder
from logstead.services.depreciation import DepreciationService
from logstead.services.itemized import EntryInput, ItemizedExpenseService
from logstead.services.loan import LoanService, monthly_interest
from logstead.services.package_paths import slugify
from logstead.services.property import PropertyService
from logstead.services.report import ReportingService
from logstead.services.report_pdf import (
    LINE12_FROM_LOAN,
    LINE12_FROM_TRANSACTIONS,
    format_money,
)
from logstead.services.transaction import TransactionService
from logstead.util.money import money_to_str

TABLE = "Logstead"
BUCKET = "logstead-files-test"
REGION = "us-east-1"
USER = "user-abc"
YEAR = 2024
ZERO = Decimal("0.00")

# Assignable categories used for plain transactions (line 12 and 13 included).
_CATEGORIES = (
    ("income", "rents-received"),
    ("expense", "insurance"),
    ("expense", "supplies"),
    ("expense", "mortgage-interest-banks"),
    ("expense", "other-interest"),
    ("expense", "repairs"),  # an unmarked repairs row acts as the entered total
)


def _create_table(ddb) -> None:
    ddb.create_table(
        TableName=TABLE,
        AttributeDefinitions=[
            {"AttributeName": n, "AttributeType": "S"}
            for n in ("PK", "SK", "GSI1PK", "GSI1SK", "GSI2PK", "GSI2SK")
        ],
        KeySchema=[
            {"AttributeName": "PK", "KeyType": "HASH"},
            {"AttributeName": "SK", "KeyType": "RANGE"},
        ],
        GlobalSecondaryIndexes=[
            {
                "IndexName": name,
                "KeySchema": [
                    {"AttributeName": f"{name}PK", "KeyType": "HASH"},
                    {"AttributeName": f"{name}SK", "KeyType": "RANGE"},
                ],
                "Projection": {"ProjectionType": "ALL"},
            }
            for name in ("GSI1", "GSI2")
        ],
        BillingMode="PAY_PER_REQUEST",
    )


def _ok(result):
    assert result.is_ok, result.error
    return result.value


# --- Strategies -----------------------------------------------------------------

_amount = st.integers(min_value=1, max_value=2_000_000).map(
    lambda cents: Decimal(cents).scaleb(-2)
)
_day = st.sampled_from(["2024-01-05", "2024-06-15", "2024-12-31", "2023-12-31"])
_txn = st.tuples(st.sampled_from(_CATEGORIES), _amount, _day)
_entry = st.tuples(_amount, _day)
_loan = st.tuples(
    st.integers(100_000, 20_000_000).map(lambda c: Decimal(c).scaleb(-2)),  # balance
    st.integers(0, 90_000).map(lambda n: Decimal(n).scaleb(-4)),  # rate percent
    st.integers(100, 3_000),  # principal share, basis points of the balance
    st.sampled_from(["2022-03-01", "2023-07-01", "2024-02-01"]),  # anchor date
    st.booleans(),  # include in report
)
_asset = st.tuples(
    st.integers(100_000, 30_000_000).map(lambda c: Decimal(c).scaleb(-2)),
    st.sampled_from(["2020-05-01", "2023-09-01", "2024-03-01"]),
)
_property = st.fixed_dictionaries(
    {
        "txns": st.lists(_txn, max_size=5),
        "entries": st.lists(_entry, max_size=3),
        "loans": st.lists(_loan, max_size=2),
        "assets": st.lists(_asset, max_size=2),
    }
)
_state = st.lists(_property, min_size=1, max_size=2)


# --- Extraction from each file ----------------------------------------------------


def _parse_pdf_money(text: str) -> Decimal:
    value = Decimal(text.strip("()$").replace(",", "").replace("$", ""))
    return -value if text.startswith("(") else value


_AMOUNT = r"(\(?\$[\d,]+\.\d{2}\)?)"


def _pdf_text(pdf: bytes) -> str:
    return " ".join(
        " ".join((p.extract_text() or "").split()) for p in PdfReader(io.BytesIO(pdf)).pages
    )


def _pdf_figures(text: str, report):
    """Return (line amounts, totals, line 12 sentence text, line 14 appendix) from PDF text."""
    lines: dict[int, Decimal] = {}
    pos = 0
    for ln in sorted(report.lines, key=lambda x: x.line):
        pattern = rf"(?<!\d){ln.line} {re.escape(ln.label)}(?: \u2020)? {_AMOUNT}"
        found = re.compile(pattern).search(text, pos)
        assert found, f"line {ln.line} missing from the PDF"
        lines[ln.line] = _parse_pdf_money(found.group(1))
        pos = found.end()
    totals = {}
    for key, label in (
        ("total_income", "Total income"),
        ("total_expenses", "20 Total expenses"),
        ("net", "21 Net income or (loss)"),
    ):
        found = re.search(rf"{re.escape(label)} {_AMOUNT}", text)
        assert found, f"{label} missing from the PDF"
        totals[key] = _parse_pdf_money(found.group(1))
    return lines, totals


def _csv_figures(raw: bytes):
    rows = list(csv.reader(io.StringIO(raw.decode("utf-8"), newline="")))
    lines = {
        int(r[0]): Decimal(r[3]) for r in rows if len(r) == 4 and r[0].isdigit()
    }
    by_label = {r[0]: r[1:] for r in rows if len(r) >= 2}
    totals = {
        "total_income": Decimal(by_label["Total Income"][0]),
        "total_expenses": Decimal(by_label["Total Expenses"][0]),
        "net": Decimal(by_label["Net"][0]),
    }
    line12 = (
        by_label["Line 12 Source"][0],
        Decimal(by_label["Line 12 Superseded Manual Interest"][0]),
        int(by_label["Line 12 Superseded Transaction Count"][0]),
    )
    return lines, totals, line12


def _json_figures(raw: bytes):
    data = json.loads(raw)
    lines = {row["line"]: Decimal(row["amount"]) for row in data["lines"]}
    totals = {k: Decimal(v) for k, v in data["totals"].items()}
    sup = data["line12"]["superseded_manual_interest"]
    line12 = (data["line12"]["source"], Decimal(sup["amount"]), sup["count"])
    return lines, totals, line12


@settings(
    max_examples=25,
    deadline=None,
    suppress_health_check=[HealthCheck.function_scoped_fixture, HealthCheck.too_slow],
)
@given(state=_state)
def test_package_files_agree_with_the_report(state):
    with mock_aws(), tempfile.TemporaryDirectory() as tmp:
        ddb = boto3.client("dynamodb", region_name=REGION)
        _create_table(ddb)
        s3 = boto3.client("s3", region_name=REGION)
        s3.create_bucket(Bucket=BUCKET)
        repo = DynamoRepository(ddb, TABLE)
        files = S3FileAdapter(s3, BUCKET)
        props = PropertyService(repo, USER)
        txns = TransactionService(repo, files)
        depreciation = DepreciationService(repo)
        loans = LoanService(repo)
        reports = ReportingService(txns, depreciation, props, files, loans=loans)
        itemized = ItemizedExpenseService(txns)
        builder = PackageBuilder(
            reports,
            itemized,
            txns,
            props,
            files,
            None,
            lambda: datetime(2025, 1, 15, 14, 3, 22, tzinfo=timezone.utc),
        )

        ids: list[str] = []
        for index, spec in enumerate(state):
            prop = _ok(
                props.create(
                    PropertyInput(
                        name=f"Agreement {index}",
                        address_text=f"{index} Agreement Way",
                        property_type="single_family",
                    )
                )
            )
            pid = prop.id
            ids.append(pid)
            for (kind, category), amount, day in spec["txns"]:
                _ok(
                    txns.create(
                        TransactionInput(
                            property_id=pid,
                            date=day,
                            amount=amount,
                            type=kind,
                            category_id=category,
                        )
                    )
                )
            for amount, day in spec["entries"]:
                _ok(
                    itemized.create_entry(
                        pid,
                        "repairs",
                        EntryInput(
                            date=day, amount=amount, description="fix", tax_year=int(day[:4])
                        ),
                    )
                )
            for balance, rate, share_bps, anchor, include in spec["loans"]:
                share = max(Decimal("0.01"), (balance * share_bps / 10_000).quantize(ZERO))
                _ok(
                    loans.create_loan(
                        LoanInput(
                            property_id=pid,
                            description="Loan",
                            annual_interest_rate=rate,
                            monthly_payment=monthly_interest(balance, rate) + share,
                            anchor_balance=balance,
                            anchor_date=anchor,
                            extra_principal=ZERO,
                            payoff_date=None,
                            include_in_report=include,
                        )
                    )
                )
            for cost, placed in spec["assets"]:
                _ok(
                    depreciation.create_asset(
                        AssetInput(
                            property_id=pid,
                            description="Asset",
                            cost_basis=cost,
                            placed_in_service_date=placed,
                            recovery_period_years=Decimal("27.5"),
                        )
                    )
                )

        zip_path = f"{tmp}/pkg.zip"
        builder.build(YEAR, ids, zip_path)
        with zipfile.ZipFile(zip_path) as zf:
            members = {n: zf.read(n) for n in zf.namelist() if n.startswith("reports/")}

        slugs = _slugs(members, ids, reports)
        for pid in ids:
            report = _ok(reports.report_for(pid, YEAR))
            base = f"reports/schedule-e-{slugs[pid]}-{YEAR}"
            want_lines = {ln.line: ln.total for ln in report.lines}
            want_totals = {
                "total_income": report.totals.total_income,
                "total_expenses": report.totals.total_expenses,
                "net": report.totals.net,
            }
            sup = report.line12.superseded_manual_interest
            want_line12 = (report.line12.source, sup.amount, sup.count)

            for lines, totals, line12 in (
                _csv_figures(members[f"{base}.csv"]),
                _json_figures(members[f"{base}.json"]),
            ):
                assert lines == want_lines
                assert totals == want_totals
                assert line12 == want_line12
                assert money_to_str(lines[14]) == money_to_str(want_lines[14])

            text = _pdf_text(members[f"{base}.pdf"])
            pdf_lines, pdf_totals = _pdf_figures(text, report)
            assert pdf_lines == want_lines
            assert pdf_totals == want_totals
            source = (
                LINE12_FROM_LOAN
                if report.line12.source == "loan-generated"
                else LINE12_FROM_TRANSACTIONS
            )
            assert source in text
            if sup.count > 0:
                assert f"{sup.count} hand-entered mortgage interest" in text
                assert f"totaling {format_money(sup.amount)}" in text
            else:
                assert "hand-entered" not in text
            if "Appendix A" in text:
                appendix = text[text.index("Appendix A") :]
                assert f"Line 14 amount: {format_money(want_lines[14])}" in appendix


def _slugs(members, ids, reports):
    """Map property id to the slug used in its report file names."""
    found = {}
    for pid in ids:
        name = _ok(reports.report_for(pid, YEAR)).header.property_name
        slug = slugify(name, "property")
        candidates = [
            n for n in members if n.endswith(f"-{YEAR}.json") and "combined" not in n
        ]
        match = [n for n in candidates if n.startswith(f"reports/schedule-e-{slug}")]
        assert match, f"no report file for {name}"
        found[pid] = match[0][len("reports/schedule-e-") : -len(f"-{YEAR}.json")]
    return found
