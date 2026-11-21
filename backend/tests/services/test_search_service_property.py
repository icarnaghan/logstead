"""Property tests for ``SearchService`` over moto (ui-polish task 7.4).

Property 8  Search matching (service level)            Requirements 8.2, 9.2, 9.5, 9.6, 9.10
Property 10 Search order and determinism               Requirements 9.4, 9.7
Property 11 Search is user-scoped and shaped           Requirements 8.3, 8.5, 10.1
Property 12 Money and links pass through unchanged     Requirements 8.7, 8.8, 8.9, 11.5
Property 13 Scan cap and truncation                    Requirements 12.2, 12.3, 12.5

Each Hypothesis example provisions its own moto table, seeds it through the
real services, and searches through a stack whose repository and file adapter
are recording wrappers (so writes, S3 calls and repeated reads are observable).
Text is drawn from a small alphabet that includes pattern characters so that
matches are frequent and ``*``, ``%``, ``\\``, ``.``, ``?``, ``[`` are
exercised as literals.
"""

from __future__ import annotations

import contextlib
import re
from datetime import date
from decimal import Decimal
from typing import Any

import boto3
import pytest
from hypothesis import assume, given, settings
from hypothesis import strategies as st
from moto import mock_aws

from logstead.adapters.s3_files import S3FileAdapter
from logstead.models.business import BusinessInput
from logstead.models.depreciation import AssetInput
from logstead.models.loan import LoanInput
from logstead.models.property import PropertyInput
from logstead.models.transaction import TransactionInput
from logstead.repository import keys
from logstead.repository.dynamo_repo import DynamoRepository
from logstead.services.business import BusinessService
from logstead.services.depreciation import DepreciationService
from logstead.services.loan import LoanService
from logstead.services.property import PropertyService
from logstead.services.search import GROUP_KINDS, SearchService
from logstead.services.search_config import SEARCH_CONFIG, SearchConfig
from logstead.services.search_match import match_rank, normalize, sort_key, tokenize
from logstead.services.transaction import TransactionService

TABLE_NAME = "Logstead"
BUCKET = "logstead-files-test"
REGION = "us-east-1"
USER_A = "user-a"
USER_B = "user-b"
LOAN_TODAY = date(2025, 6, 1)

_SETTINGS = settings(deadline=None, max_examples=25)


# --- Environment -------------------------------------------------------------


@contextlib.contextmanager
def _moto_env():
    """A fresh moto table (base + GSI1 + GSI2) and bucket per example."""
    with mock_aws():
        ddb = boto3.client("dynamodb", region_name=REGION)
        ddb.create_table(
            TableName=TABLE_NAME,
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
        s3 = boto3.client("s3", region_name=REGION)
        s3.create_bucket(Bucket=BUCKET)
        yield DynamoRepository(ddb, TABLE_NAME), S3FileAdapter(s3, BUCKET)


class RecordingRepo:
    """Delegates to a real repository and records every call."""

    WRITES = {"put_item", "delete_item", "transact_write"}

    def __init__(self, inner: DynamoRepository) -> None:
        self._inner = inner
        self.calls: list[tuple[str, tuple, tuple]] = []

    def __getattr__(self, name: str) -> Any:
        target = getattr(self._inner, name)
        if not callable(target):
            return target

        def call(*args: Any, **kwargs: Any) -> Any:
            self.calls.append((name, args, tuple(sorted(kwargs.items(), key=str))))
            return target(*args, **kwargs)

        return call

    @property
    def writes(self) -> list[str]:
        return [c[0] for c in self.calls if c[0] in self.WRITES]

    @property
    def queries(self) -> list[tuple]:
        return [c for c in self.calls if c[0] == "query"]


class RecordingFiles:
    """Any use of the file adapter is recorded and then rejected."""

    def __init__(self) -> None:
        self.used: list[str] = []

    def __getattr__(self, name: str) -> Any:
        self.used.append(name)

        def call(*_a: Any, **_k: Any) -> Any:
            raise AssertionError(f"search touched the file adapter: {name}")

        return call


def _search_stack(
    repo: DynamoRepository,
    user_id: str,
    config: SearchConfig = SEARCH_CONFIG,
) -> tuple[SearchService, RecordingRepo, RecordingFiles]:
    rrepo = RecordingRepo(repo)
    rfiles = RecordingFiles()
    svc = SearchService(
        PropertyService(rrepo, user_id),
        TransactionService(rrepo, rfiles),
        DepreciationService(rrepo),
        LoanService(rrepo, today=lambda: LOAN_TODAY),
        BusinessService(rrepo, user_id),
        config,
    )
    return svc, rrepo, rfiles


# --- Strategies --------------------------------------------------------------

_ALPHABET = "abAB é.*%?[\\"

_text = st.text(alphabet=_ALPHABET, min_size=1, max_size=8).filter(
    lambda s: bool(s.strip())
)
_opt_text = st.none() | _text
_amount = st.decimals(
    min_value=Decimal("0.01"),
    max_value=Decimal("99999.99"),
    places=2,
    allow_nan=False,
    allow_infinity=False,
)

_txn_spec = st.fixed_dictionaries(
    {
        "itemized": st.booleans(),
        "income": st.booleans(),
        "desc": _opt_text,
        "notes": _opt_text,
        "amount": _amount,
        "year": st.integers(min_value=2018, max_value=2024),
        "month": st.integers(min_value=1, max_value=12),
        "day": st.integers(min_value=1, max_value=28),
    }
)


def _prop_spec(max_txns: int = 4, max_assets: int = 2, max_loans: int = 2):
    return st.fixed_dictionaries(
        {
            "name": _text,
            "address": _text,
            "txns": st.lists(_txn_spec, max_size=max_txns),
            "assets": st.lists(
                st.fixed_dictionaries({"desc": _text, "cost": _amount}),
                max_size=max_assets,
            ),
            "loans": st.lists(_text, max_size=max_loans),
        }
    )


_business_spec = st.fixed_dictionaries({"name": _text, "address": _opt_text})

_state = st.fixed_dictionaries(
    {
        "props": st.lists(_prop_spec(), min_size=1, max_size=2),
        "businesses": st.lists(_business_spec, max_size=2),
    }
)

_query = st.text(alphabet=_ALPHABET, min_size=2, max_size=4).filter(
    lambda s: len(s.strip()) >= 2
)


# --- Seeding and the independent oracle --------------------------------------


class Rec:
    """One seeded record: what the oracle needs to know about it."""

    def __init__(self, kind, id_, pid, fields, title, date_, amount):
        self.kind = kind
        self.id = id_
        self.pid = pid
        self.fields = fields  # [(name, raw text)]
        self.title = title
        self.date = date_
        self.amount = amount


def _seed(repo, files, user_id: str, state: dict) -> list[Rec]:
    props = PropertyService(repo, user_id)
    txns = TransactionService(repo, files)
    depr = DepreciationService(repo)
    loans = LoanService(repo, today=lambda: LOAN_TODAY)
    businesses = BusinessService(repo, user_id)
    recs: list[Rec] = []

    for p in state["props"]:
        created = props.create(
            PropertyInput(
                name=p["name"], address_text=p["address"], property_type="single_family"
            )
        )
        assert created.is_ok, created.error
        prop = created.value
        pid = prop.id
        recs.append(
            Rec(
                "property",
                pid,
                pid,
                [("name", prop.name), ("address_text", prop.address_text)],
                prop.name,
                None,
                None,
            )
        )

        for t in p["txns"]:
            itemized = t["itemized"]
            income = t["income"] and not itemized
            desc = t["desc"] if t["desc"] is not None else ("zz" if itemized else None)
            r = txns.create(
                TransactionInput(
                    property_id=pid,
                    date=f"{t['year']:04d}-{t['month']:02d}-{t['day']:02d}",
                    amount=t["amount"],
                    type="income" if income else "expense",
                    category_id="rents-received" if income else "repairs",
                    description=desc,
                    itemized=itemized,
                    notes=t["notes"] if itemized else None,
                )
            )
            assert r.is_ok, r.error
            txn = r.value
            fields = [("description", txn.description or "")]
            if txn.itemized:
                fields.append(("notes", txn.notes or ""))
            recs.append(
                Rec(
                    "itemized_entry" if txn.itemized else "transaction",
                    txn.id,
                    pid,
                    fields,
                    txn.description or "",
                    txn.date,
                    txn.amount,
                )
            )

        for a in p["assets"]:
            r = depr.create_asset(
                AssetInput(
                    property_id=pid,
                    description=a["desc"],
                    cost_basis=a["cost"],
                    placed_in_service_date="2020-03-01",
                    recovery_period_years=Decimal("27.5"),
                )
            )
            assert r.is_ok, r.error
            recs.append(
                Rec(
                    "asset",
                    r.value.id,
                    pid,
                    [("description", r.value.description)],
                    r.value.description,
                    None,
                    r.value.cost_basis,
                )
            )

        for desc in p["loans"]:
            r = loans.create_loan(
                LoanInput(
                    property_id=pid,
                    description=desc,
                    annual_interest_rate=Decimal("0"),
                    monthly_payment=Decimal("1000.00"),
                    anchor_balance=Decimal("5000.00"),
                    anchor_date="2025-06-01",
                )
            )
            assert r.is_ok, r.error
            recs.append(
                Rec(
                    "loan",
                    r.value.id,
                    pid,
                    [("description", r.value.description)],
                    r.value.description,
                    None,
                    None,
                )
            )

    for b in state["businesses"]:
        r = businesses.create(
            BusinessInput(
                legal_name=b["name"], entity_type="llc", business_address=b["address"]
            )
        )
        assert r.is_ok, r.error
        biz = r.value
        recs.append(
            Rec(
                "business",
                biz.id,
                None,
                [
                    ("legal_name", biz.legal_name),
                    ("business_address", biz.business_address or ""),
                ],
                biz.legal_name,
                None,
                None,
            )
        )
    return recs


def _matches(rec: Rec, tokens: list[str]) -> bool:
    """Spec oracle: every token occurs in the normalized searchable text."""
    joined = " ".join(normalize(text) for _, text in rec.fields)
    return all(tok in joined for tok in tokens)


def _expected_ids(recs: list[Rec], tokens: list[str]) -> dict[str, set[str]]:
    out: dict[str, set[str]] = {k: set() for k in GROUP_KINDS}
    for r in recs:
        if _matches(r, tokens):
            out[r.kind].add(r.id)
    return out


def _search_ok(svc: SearchService, q: str, **kw: Any):
    res = svc.search(q, **kw)
    assert res.is_ok, res.error
    return res.value


# --- Property 8 --------------------------------------------------------------


# Feature: ui-polish, Property 8: Search matching
@_SETTINGS
@given(state=_state, q=_query)
def test_property_8_search_matching(state, q):
    """**Validates: Requirements 8.2, 9.2, 9.5, 9.6, 9.10**"""
    with _moto_env() as (repo, files):
        recs = _seed(repo, files, USER_A, state)
        svc, _, _ = _search_stack(repo, USER_A)
        tokens = tokenize(q.strip(), SEARCH_CONFIG.max_tokens)
        expected = _expected_ids(recs, tokens)

        full = _search_ok(svc, q, limit=SEARCH_CONFIG.max_limit)
        one = _search_ok(svc, q, limit=1)

        for g_full, g_one in zip(full.groups, one.groups, strict=True):
            exp = expected[g_full.kind]
            got = {h.id for h in g_full.hits}
            assert g_full.total == len(exp)
            assert g_one.total == g_full.total  # total independent of limit
            assert len(g_one.hits) <= 1
            assert len(g_full.hits) == min(len(exp), SEARCH_CONFIG.max_limit)
            assert got == exp  # at most 16 records per kind: nothing is cut off
            assert all(h.kind == g_full.kind for h in g_full.hits)


# --- Property 10 -------------------------------------------------------------


# Feature: ui-polish, Property 10: Search order and determinism
@_SETTINGS
@given(state=_state, q=_query)
def test_property_10_order_and_determinism(state, q):
    """**Validates: Requirements 9.4, 9.7**"""
    with _moto_env() as (repo, files):
        recs = _seed(repo, files, USER_A, state)
        svc, _, _ = _search_stack(repo, USER_A)
        tokens = tokenize(q.strip(), SEARCH_CONFIG.max_tokens)

        first = _search_ok(svc, q, limit=SEARCH_CONFIG.max_limit)
        second = _search_ok(svc, q, limit=SEARCH_CONFIG.max_limit)
        assert first == second

        for group in first.groups:
            ranked = []
            for r in recs:
                if r.kind != group.kind:
                    continue
                m = match_rank(tokens, r.fields)
                if m is None:
                    continue
                key = sort_key({"date": r.date, "title": r.title, "id": r.id}, m[0])
                ranked.append((key, r.id))
            assert [h.id for h in group.hits] == [i for _, i in sorted(ranked)]


# --- Property 11 -------------------------------------------------------------


# Feature: ui-polish, Property 11: Search is user-scoped and shaped
@_SETTINGS
@given(a_state=_state, b_state=_state, q=_query)
def test_property_11_user_scoped_and_shaped(a_state, b_state, q):
    """**Validates: Requirements 8.3, 8.5, 10.1**"""
    with _moto_env() as (repo, files):
        a_recs = _seed(repo, files, USER_A, a_state)
        b_recs = _seed(repo, files, USER_B, b_state)
        a_ids = {r.id for r in a_recs}
        b_ids = {r.id for r in b_recs}
        a_pids = {r.pid for r in a_recs if r.pid}
        tokens = tokenize(q.strip(), SEARCH_CONFIG.max_tokens)

        svc, rrepo, rfiles = _search_stack(repo, USER_A)
        result = _search_ok(svc, q, limit=SEARCH_CONFIG.max_limit)

        assert [g.kind for g in result.groups] == list(GROUP_KINDS)
        seen = {h.id for g in result.groups for h in g.hits}
        assert seen <= a_ids
        assert not (seen & b_ids)
        for g in result.groups:
            assert g.total == len(_expected_ids(a_recs, tokens)[g.kind])
            if g.total == 0:
                assert g.hits == ()
            for h in g.hits:
                assert h.property_id is None or h.property_id in a_pids

        assert rrepo.writes == []
        assert rfiles.used == []
        # Partition queries only, and each partition is read once (Req 12.1, 12.4).
        assert not any(c[0] == "scan" for c in rrepo.calls)
        query_keys = [repr(c) for c in rrepo.queries]
        assert len(query_keys) == len(set(query_keys))


# --- Property 12 -------------------------------------------------------------

_ID_CLASS = r"[A-Za-z0-9_.:-]{1,128}"
_LINK_PATTERNS = {
    "property": re.compile(rf"^/properties/{_ID_CLASS}$"),
    "transaction": re.compile(
        rf"^/properties/{_ID_CLASS}/transactions\?year=\d{{4}}&focus={_ID_CLASS}$"
    ),
    "itemized_entry": re.compile(
        rf"^/properties/{_ID_CLASS}/repairs\?year=\d{{4}}&focus={_ID_CLASS}$"
    ),
    "asset": re.compile(rf"^/properties/{_ID_CLASS}/assets\?focus={_ID_CLASS}$"),
    "loan": re.compile(rf"^/properties/{_ID_CLASS}/loans\?focus={_ID_CLASS}$"),
    "business": re.compile(rf"^/businesses/{_ID_CLASS}$"),
}


def _is_safe_app_link(link: str) -> bool:
    """Python mirror of ``isSafeAppLink`` in ``frontend/src/lib/safeLink.ts``."""
    if not link.startswith("/") or link.startswith("//"):
        return False
    return not any(ch == "\\" or ord(ch) < 0x20 or ord(ch) == 0x7F for ch in link)


def _expected_link(rec: Rec) -> str:
    if rec.kind == "property":
        return f"/properties/{rec.id}"
    if rec.kind == "business":
        return f"/businesses/{rec.id}"
    if rec.kind == "asset":
        return f"/properties/{rec.pid}/assets?focus={rec.id}"
    if rec.kind == "loan":
        return f"/properties/{rec.pid}/loans?focus={rec.id}"
    page = "transactions" if rec.kind == "transaction" else "repairs"
    return f"/properties/{rec.pid}/{page}?year={rec.date[:4]}&focus={rec.id}"


# Feature: ui-polish, Property 12: Money and links pass through unchanged
@_SETTINGS
@given(state=_state, data=st.data())
def test_property_12_money_and_links_pass_through(state, data):
    """**Validates: Requirements 8.7, 8.8, 8.9, 11.5**"""
    with _moto_env() as (repo, files):
        recs = _seed(repo, files, USER_A, state)
        by_key = {(r.kind, r.id): r for r in recs}
        candidates = [
            text.strip()
            for r in recs
            for _, text in r.fields
            if len(text.strip()) >= 2
        ]
        assume(candidates)
        q = data.draw(st.sampled_from(candidates))

        svc, _, _ = _search_stack(repo, USER_A)
        result = _search_ok(svc, q, limit=SEARCH_CONFIG.max_limit)
        hits = [h for g in result.groups for h in g.hits]
        assert hits  # the record the query was taken from matches

        for h in hits:
            rec = by_key[(h.kind, h.id)]
            if rec.amount is None:
                assert h.amount is None
            else:
                assert isinstance(h.amount, Decimal)
                assert h.amount == rec.amount
                assert str(h.amount) == f"{rec.amount:.2f}"  # no rounding or drift
            assert h.link == _expected_link(rec)
            assert _LINK_PATTERNS[h.kind].match(h.link)
            assert _is_safe_app_link(h.link)


# --- Property 13 -------------------------------------------------------------


# Feature: ui-polish, Property 13: Scan cap and truncation
@_SETTINGS
@given(
    props=st.lists(_prop_spec(3, 2, 1), min_size=1, max_size=4),
    cap=st.integers(min_value=1, max_value=14),
    q=_query,
)
def test_property_13_scan_cap_and_truncation(props, cap, q):
    """**Validates: Requirements 12.2, 12.3, 12.5**"""
    with _moto_env() as (repo, files):
        recs = _seed(repo, files, USER_A, {"props": props, "businesses": []})
        counts: dict[str, int] = {}
        for r in recs:
            if r.kind != "property":
                counts[r.pid] = counts.get(r.pid, 0) + 1
        order = [p.id for p in PropertyService(repo, USER_A).list()]
        available = sum(counts.get(pid, 0) for pid in order)

        # Replay the documented stopping rule: stop once the cap is reached
        # while properties remain unread.
        reached_with_unread = False
        running = 0
        for index, pid in enumerate(order):
            if running >= cap:
                reached_with_unread = True
                break
            running += counts.get(pid, 0)
            if running >= cap and index + 1 < len(order):
                reached_with_unread = True
                break

        svc, _, _ = _search_stack(repo, USER_A, SearchConfig(scan_cap=cap))
        result = _search_ok(svc, q, limit=SEARCH_CONFIG.max_limit)

        assert result.scanned >= 0
        if result.truncated:
            assert result.scanned >= cap  # Req 12.2 (a property may overshoot)
        if available < cap:
            assert result.truncated is False  # Req 12.3
        # A single property may overshoot the cap without anything unread, so
        # ``available > cap`` does not by itself imply ``truncated``.
        if not reached_with_unread:
            assert result.truncated is False
            assert result.scanned == available
            tokens = tokenize(q.strip(), SEARCH_CONFIG.max_tokens)
            expected = _expected_ids(recs, tokens)
            for g in result.groups:
                assert {h.id for h in g.hits} == expected[g.kind]


# --- Examples ----------------------------------------------------------------


def _one_property_state(**over: Any) -> dict:
    prop = {"name": "Maple", "address": "1 Oak", "txns": [], "assets": [], "loans": []}
    prop.update(over)
    return {"props": [prop], "businesses": []}


def test_default_scan_cap_is_twenty_thousand():
    with _moto_env() as (repo, _files):
        svc, _, _ = _search_stack(repo, USER_A)
        assert SEARCH_CONFIG.scan_cap == 20_000
        assert svc._config is SEARCH_CONFIG


def test_corrupt_loan_returns_the_existing_error():
    with _moto_env() as (repo, files):
        recs = _seed(
            repo,
            files,
            USER_A,
            _one_property_state(loans=["Mortgage"]),
        )
        loan = next(r for r in recs if r.kind == "loan")
        item = repo.get_item(
            keys.property_scoped_pk(loan.pid), keys.loan_sk(loan.id), money_attrs=set()
        )
        item["anchorBalance"] = "12"
        repo.put_item(item, money_attrs=set())

        direct = LoanService(repo, today=lambda: LOAN_TODAY).list_loans(loan.pid)
        svc, rrepo, _ = _search_stack(repo, USER_A)
        res = svc.search("mortgage")

        assert direct.error is not None
        assert res.error is not None
        assert res.error.kind == direct.error.kind == "conflict"
        assert res.error.field == direct.error.field == "anchorBalance"
        assert res.error.message == direct.error.message
        assert rrepo.writes == []


def test_property_id_restricts_to_one_property():
    with _moto_env() as (repo, files):
        state = {
            "props": [
                {
                    "name": "Alpha",
                    "address": "1 Oak",
                    "txns": [],
                    "assets": [{"desc": "Alpha fridge", "cost": Decimal("10.00")}],
                    "loans": ["Alpha loan"],
                },
                {
                    "name": "Alpha two",
                    "address": "2 Oak",
                    "txns": [],
                    "assets": [{"desc": "Alpha stove", "cost": Decimal("20.00")}],
                    "loans": [],
                },
            ],
            "businesses": [{"name": "Alpha LLC", "address": None}],
        }
        recs = _seed(repo, files, USER_A, state)
        target = next(r for r in recs if r.kind == "asset" and "fridge" in r.title)
        svc, _, _ = _search_stack(repo, USER_A)

        everything = _search_ok(svc, "alpha")
        assert {g.kind: g.total for g in everything.groups} == {
            "property": 2,
            "transaction": 0,
            "itemized_entry": 0,
            "asset": 2,
            "loan": 1,
            "business": 1,
        }

        scoped = _search_ok(svc, "alpha", property_id=target.pid)
        totals = {g.kind: g.total for g in scoped.groups}
        assert totals["property"] == 0  # property rows are skipped when scoped
        assert totals["business"] == 0  # and so are businesses
        assert totals["asset"] == 1 and totals["loan"] == 1
        assert all(h.property_id == target.pid for g in scoped.groups for h in g.hits)

        missing = svc.search("alpha", property_id="no-such-property")
        assert missing.error is not None and missing.error.kind == "not_found"


def test_amount_date_and_category_label_are_not_searchable():
    with _moto_env() as (repo, files):
        txn = {
            "itemized": False,
            "income": False,
            "desc": "plain words",
            "notes": None,
            "amount": Decimal("1234.56"),
            "year": 2024,
            "month": 5,
            "day": 17,
        }
        item = dict(txn, itemized=True, desc="other words", notes="more words")
        _seed(
            repo,
            files,
            USER_A,
            _one_property_state(txns=[txn, item]),
        )
        svc, _, _ = _search_stack(repo, USER_A)

        for q in ("1234.56", "1,234", "2024-05-17", "2024-05", "repairs", "Repairs"):
            result = _search_ok(svc, q)
            assert [g.total for g in result.groups] == [0] * len(GROUP_KINDS), q

        # Sanity: the text fields of the same records do match.
        assert _search_ok(svc, "plain").groups[1].total == 1
        assert _search_ok(svc, "more words").groups[2].total == 1


def test_non_itemized_transaction_notes_are_not_searched():
    """Notes only exist on itemized entries; a plain transaction searches description."""
    with _moto_env() as (repo, files):
        txn = {
            "itemized": False,
            "income": False,
            "desc": "alpha",
            "notes": "hidden",
            "amount": Decimal("5.00"),
            "year": 2024,
            "month": 1,
            "day": 1,
        }
        _seed(repo, files, USER_A, _one_property_state(txns=[txn]))
        svc, _, _ = _search_stack(repo, USER_A)
        assert _search_ok(svc, "hidden").groups[1].total == 0
        assert _search_ok(svc, "alpha").groups[1].total == 1


@pytest.mark.parametrize("bad", ["", " ", "a", "x" * 101])
def test_invalid_query_is_a_validation_error(bad):
    with _moto_env() as (repo, _files):
        svc, _, _ = _search_stack(repo, USER_A)
        res = svc.search(bad)
        assert res.error is not None and res.error.kind == "validation"
        assert res.error.field == "q"
