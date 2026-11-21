"""Property-based test for design Correctness Property 5 (task 8.5).

# Feature: schedule-e-pdf-extraction, Property 5: No Line 18 (Depreciation) ever appears in a Review_Draft

Validates: Requirements 4.5, 8.4

*For any* uploaded document — including one whose Schedule E Part I **always**
carries a Line 18 (Depreciation) row with a real amount — the produced
``Review_Draft`` SHALL contain no ``ExtractedLine`` with ``schedule_e_line == 18``
in any column, and the Line 18 amount SHALL never surface among the draft's line
amounts. The parser's allow-set ``{3, 4, 5-17, 19}`` structurally excludes
depreciation, so it can never be read, carried, or pre-filled — no matter what
the document contains.

The property is driven end-to-end through the **real** extraction path. A
Hypothesis strategy generates a Schedule E Part I **Textract-shaped block
fixture** (random property-column count, random allow-set line amounts, a random
tax year, random addresses) that *always* includes a Line 18 Depreciation table
row with a randomly generated amount. The generated blocks are fed to the real
``ExtractionService.get_status`` via a fake ``TextractAdapter`` returning a
``SUCCEEDED`` result (live Amazon Textract is never called), running the genuine
parse → ``ReviewDraft`` build. The produced draft is then asserted to be
free of Line 18 and of the generated depreciation amounts.

Each example provisions its own moto-backed single-table DynamoDB + S3 bucket
and walks the full start → upload → begin → poll sequence, so the assertion is
made on exactly the ``ReviewDraft`` the SPA would receive. Per-example table +
bucket provisioning is not instantaneous, so the deadline is disabled while
``max_examples`` is held at 100.
"""

from __future__ import annotations

import boto3
from hypothesis import HealthCheck, given, settings
from hypothesis import strategies as st
from moto import mock_aws

from logstead.adapters.s3_files import S3FileAdapter
from logstead.adapters.textract import TextractResult
from logstead.repository.dynamo_repo import DynamoRepository
from logstead.services.schedule_e_extraction import (
    PDF_CONTENT_TYPE,
    ExtractionService,
)

TABLE_NAME = "Logstead"
BUCKET = "logstead-files-test"
REGION = "us-east-1"
USER = "user-prop5"

# The Depreciation line that must NEVER appear in a Review_Draft.
_LINE_18 = 18

# The allow-set lines the parser may legitimately read, paired with the exact
# label text the parser's _LABEL_TO_LINE table recognizes. Line 18 is absent
# here by construction — this mirrors the parser's own allow-set.
#
# ``_LOCATOR_LABELS`` is the subset whose text the parser also recognizes as a
# page-location marker (its _LINE_LABELS set): a page is treated as Part I only
# when the title marker co-occurs with ≥2 of these. The strategy always draws
# at least two locator rows so every generated document is located as Part I
# (the point of this test is the Line 18 exclusion, not page location).
_LOCATOR_LABELS: tuple[tuple[int, str], ...] = (
    (3, "Rents received"),
    (4, "Royalties received"),
    (5, "Advertising"),
    (7, "Cleaning and maintenance"),
    (9, "Insurance"),
    (11, "Management fees"),
    (12, "Mortgage interest paid to banks"),
    (14, "Repairs"),
    (15, "Supplies"),
    (16, "Taxes"),
    (17, "Utilities"),
)

# The remaining allow-set lines whose text is read for amounts but is not itself
# a page-location marker.
_OTHER_LABELS: tuple[tuple[int, str], ...] = (
    (6, "Auto and travel"),
    (8, "Commissions"),
    (10, "Legal and other professional fees"),
    (13, "Other interest"),
    (19, "Other"),
)

# A money amount token as OCR would render it (plain integer or two decimals).
_amount_tokens = st.one_of(
    st.integers(min_value=0, max_value=5_000_000).map(str),
    st.integers(min_value=0, max_value=5_000_000).map(lambda n: f"{n}.00"),
    st.decimals(
        min_value=0, max_value=50_000, places=2, allow_nan=False, allow_infinity=False
    ).map(lambda d: f"{d:.2f}"),
)

# A distinctive Line 18 depreciation amount: large and ".77"-tailed so it is
# vanishingly unlikely to collide with a generated allow-set amount, making the
# "the depreciation value never appears" assertion sharp.
_line18_amount_tokens = st.integers(min_value=100_000, max_value=99_999_999).map(
    lambda n: f"{n}.77"
)

_year_tokens = st.integers(min_value=1990, max_value=2099)

_address_tokens = st.text(
    alphabet="ABCDEFGHIJKLMNOPQRSTUVWXYZ abcdefghijklmnopqrstuvwxyz 0123456789",
    min_size=0,
    max_size=24,
)


def _word(block_id: str, text: str, conf: float = 97.0) -> dict:
    return {"Id": block_id, "BlockType": "WORD", "Text": text, "Confidence": conf}


def _cell(block_id: str, row: int, col: int, child_id: str, conf: float = 97.0) -> dict:
    return {
        "Id": block_id,
        "BlockType": "CELL",
        "RowIndex": row,
        "ColumnIndex": col,
        "Confidence": conf,
        "Relationships": [{"Type": "CHILD", "Ids": [child_id]}],
    }


def _build_schedule_e_blocks(
    *,
    num_columns: int,
    allowed_rows: list[tuple[int, str]],
    allowed_amounts: list[list[str]],
    line18_amounts: list[str],
    year: int,
    addresses: list[str],
) -> list[dict]:
    """Assemble a Textract TABLES-shaped Schedule E Part I block fixture.

    The table always carries one Line 18 (Depreciation) row (``line18_amounts``
    per property column) alongside the drawn allow-set rows. The parser reads the
    cell at (line-label row, property column); column 1 is the label column and
    property columns are columns 2..(num_columns+1). The returned blocks mirror
    the hand-built parser fixtures' shape closely enough to exercise the real
    parse → ReviewDraft path.
    """
    blocks: list[dict] = []
    line_ids: list[str] = []

    # --- Header / markers so the page is recognized as Schedule E Part I. ---
    blocks.append(
        {
            "Id": "ttl",
            "BlockType": "LINE",
            "Page": 1,
            "Text": "SCHEDULE E (Form 1040) Supplemental Income and Loss",
            "Confidence": 99.0,
            "Geometry": {"BoundingBox": {"Left": 0.05, "Top": 0.02, "Width": 0.5, "Height": 0.02}},
        }
    )
    line_ids.append("ttl")
    blocks.append(
        {
            "Id": "parti",
            "BlockType": "LINE",
            "Page": 1,
            "Text": "Part I Income or Loss From Rental Real Estate and Royalties",
            "Confidence": 98.5,
            "Geometry": {"BoundingBox": {"Left": 0.05, "Top": 0.08, "Width": 0.6, "Height": 0.02}},
        }
    )
    line_ids.append("parti")
    blocks.append(
        {
            "Id": "cal",
            "BlockType": "LINE",
            "Page": 1,
            "Text": f"For calendar year {year}",
            "Confidence": 98.0,
            "Geometry": {"BoundingBox": {"Left": 0.70, "Top": 0.02, "Width": 0.2, "Height": 0.02}},
        }
    )
    line_ids.append("cal")

    # --- Line-label LINE blocks (the parser's page-location needs ≥2 of the
    # recognizable labels present as LINE text; the table carries the amounts).
    top = 0.30
    for idx, (_line_no, label) in enumerate(allowed_rows):
        lid = f"lbl-{idx}"
        blocks.append(
            {
                "Id": lid,
                "BlockType": "LINE",
                "Page": 1,
                "Text": label,
                "Confidence": 98.0,
                "Geometry": {"BoundingBox": {"Left": 0.05, "Top": top, "Width": 0.3, "Height": 0.02}},
            }
        )
        line_ids.append(lid)
        top += 0.02
    # The Line 18 label LINE is present in the document too, to be realistic.
    blocks.append(
        {
            "Id": "lbl-dep",
            "BlockType": "LINE",
            "Page": 1,
            "Text": "18 Depreciation expense or depletion",
            "Confidence": 98.0,
            "Geometry": {"BoundingBox": {"Left": 0.05, "Top": top, "Width": 0.3, "Height": 0.02}},
        }
    )
    line_ids.append("lbl-dep")

    # --- Address LINE blocks per column (geometry fallback source). ---
    addr_lid = "addr-lbl"
    blocks.append(
        {
            "Id": addr_lid,
            "BlockType": "LINE",
            "Page": 1,
            "Text": "1a Physical address of each property",
            "Confidence": 97.0,
            "Geometry": {"BoundingBox": {"Left": 0.05, "Top": 0.14, "Width": 0.3, "Height": 0.02}},
        }
    )
    line_ids.append(addr_lid)
    for ci in range(num_columns):
        addr = addresses[ci].strip()
        if not addr:
            continue
        aid = f"addr-{ci}"
        blocks.append(
            {
                "Id": aid,
                "BlockType": "LINE",
                "Page": 1,
                "Text": addr,
                "Confidence": 96.0,
                "Geometry": {
                    "BoundingBox": {
                        "Left": 0.40 + ci * 0.15,
                        "Top": 0.14,
                        "Width": 0.12,
                        "Height": 0.02,
                    }
                },
            }
        )
        line_ids.append(aid)

    # --- The PAGE block owning all LINEs (page location honors PAGE→CHILD). ---
    blocks.append(
        {
            "Id": "page-1",
            "BlockType": "PAGE",
            "Page": 1,
            "Relationships": [{"Type": "CHILD", "Ids": line_ids}],
        }
    )

    # --- The TABLE: label in column 1, property amounts in columns 2..N+1. ---
    # Rows: the drawn allow-set rows, plus one guaranteed Line 18 row.
    table_child_ids: list[str] = []
    row_index = 0

    def _add_row(prefix: str, label_text: str, amounts: list[str]) -> None:
        nonlocal row_index
        row_index += 1
        # Column 1: the label cell.
        lcell = f"{prefix}-l"
        lword = f"{prefix}-lw"
        blocks.append(_word(lword, label_text))
        blocks.append(_cell(lcell, row_index, 1, lword))
        table_child_ids.append(lcell)
        # Columns 2..N+1: the property amount cells.
        for ci in range(num_columns):
            ccell = f"{prefix}-c{ci}"
            cword = f"{prefix}-c{ci}-w"
            blocks.append(_word(cword, amounts[ci]))
            blocks.append(_cell(ccell, row_index, ci + 2, cword))
            table_child_ids.append(ccell)

    for idx, (_line_no, label) in enumerate(allowed_rows):
        _add_row(f"r{idx}", label, allowed_amounts[idx])

    # The GUARANTEED Line 18 Depreciation row with a real amount per column.
    _add_row("rdep", "Depreciation expense or depletion", line18_amounts)

    blocks.append(
        {
            "Id": "table-1",
            "BlockType": "TABLE",
            "Page": 1,
            "Confidence": 97.5,
            "Relationships": [{"Type": "CHILD", "Ids": table_child_ids}],
        }
    )

    return blocks


@st.composite
def _schedule_e_with_line18(draw) -> tuple[list[dict], list[str]]:
    """Draw a Schedule E Part I block fixture that always contains Line 18.

    Returns ``(blocks, line18_amounts)``: the Textract-shaped blocks and the
    exact Line 18 depreciation amount tokens placed into the document, so the
    test can assert those values never surface in the Review_Draft.
    """
    num_columns = draw(st.integers(min_value=1, max_value=4))

    # Always include ≥2 locator rows so the page is recognized as Part I, then a
    # random mix of any other allow-set rows. Deduplicate by line number and
    # order stably. Line 18 is never among these by construction.
    locator_rows = draw(
        st.lists(
            st.sampled_from(_LOCATOR_LABELS),
            min_size=2,
            max_size=len(_LOCATOR_LABELS),
            unique_by=lambda pair: pair[0],
        )
    )
    extra_rows = draw(
        st.lists(
            st.sampled_from(_LOCATOR_LABELS + _OTHER_LABELS),
            min_size=0,
            max_size=6,
            unique_by=lambda pair: pair[0],
        )
    )
    by_line = {pair[0]: pair for pair in (*locator_rows, *extra_rows)}
    allowed_rows = sorted(by_line.values(), key=lambda pair: pair[0])

    allowed_amounts = [
        draw(st.lists(_amount_tokens, min_size=num_columns, max_size=num_columns))
        for _ in allowed_rows
    ]
    line18_amounts = draw(
        st.lists(_line18_amount_tokens, min_size=num_columns, max_size=num_columns)
    )
    year = draw(_year_tokens)
    addresses = draw(
        st.lists(_address_tokens, min_size=num_columns, max_size=num_columns)
    )

    blocks = _build_schedule_e_blocks(
        num_columns=num_columns,
        allowed_rows=allowed_rows,
        allowed_amounts=allowed_amounts,
        line18_amounts=line18_amounts,
        year=year,
        addresses=addresses,
    )
    return blocks, line18_amounts


class _FakeTextract:
    """In-memory ``TextractAdapter`` stand-in returning a canned SUCCEEDED result."""

    def __init__(self, blocks: list[dict]) -> None:
        self._result = TextractResult(status="SUCCEEDED", blocks=blocks)
        self.job_id = "textract-job-prop5"

    def start_document_analysis(self, bucket: str, key: str) -> str:
        return self.job_id

    def get_document_analysis(self, job_id: str) -> TextractResult:
        return self._result


@settings(max_examples=100, deadline=None, suppress_health_check=[HealthCheck.too_slow])
@given(generated=_schedule_e_with_line18())
def test_line_18_never_appears_in_review_draft(generated):
    """A Line 18 amount in the document never reaches the Review_Draft (Req 4.5, 8.4)."""
    blocks, line18_amounts = generated

    with mock_aws():
        ddb = boto3.client("dynamodb", region_name=REGION)
        ddb.create_table(
            TableName=TABLE_NAME,
            AttributeDefinitions=[
                {"AttributeName": "PK", "AttributeType": "S"},
                {"AttributeName": "SK", "AttributeType": "S"},
            ],
            KeySchema=[
                {"AttributeName": "PK", "KeyType": "HASH"},
                {"AttributeName": "SK", "KeyType": "RANGE"},
            ],
            BillingMode="PAY_PER_REQUEST",
        )
        s3 = boto3.client("s3", region_name=REGION)
        s3.create_bucket(Bucket=BUCKET)

        repo = DynamoRepository(ddb, TABLE_NAME)
        files = S3FileAdapter(s3, BUCKET)
        textract = _FakeTextract(blocks)
        service = ExtractionService(repo, USER, files=files, textract=textract)

        # Full real path: start -> upload the PDF bytes -> begin -> poll.
        start = service.start_extraction("return.pdf", PDF_CONTENT_TYPE)
        assert start.is_ok
        job_id = start.value.job_id

        key = f"imports/schedule-e/{USER}/{job_id}.pdf"
        s3.put_object(
            Bucket=BUCKET,
            Key=key,
            Body=b"%PDF-1.7 generated body",
            ContentType=PDF_CONTENT_TYPE,
        )

        begin = service.begin_extraction(job_id)
        assert begin.is_ok
        assert begin.value.status == "processing"

        poll = service.get_status(job_id)
        assert poll.is_ok
        view = poll.value
        assert view.status == "complete"
        assert view.outcome == "draft"
        draft = view.review_draft
        assert draft is not None

    # --- The property: no Line 18 anywhere, and no depreciation value leaks. ---
    seen_line18_values = set(line18_amounts)
    for column in draft.columns:
        # No ExtractedLine carries schedule_e_line == 18 in ANY column.
        assert all(
            line.schedule_e_line != _LINE_18 for line in column.lines
        ), f"Line 18 appeared in a column: {[l.schedule_e_line for l in column.lines]}"

        # The Line 18 amount value never surfaces among the draft's line amounts.
        for line in column.lines:
            assert line.amount not in seen_line18_values, (
                f"A depreciation amount {line.amount!r} leaked into line "
                f"{line.schedule_e_line}"
            )
