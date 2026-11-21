"""Global search over the authenticated user's properties, records and businesses.

Reads only through the existing services (all user-scoped), performs no write
and no S3 call, and never builds a pattern from the query. Only the text
fields listed in Requirement 8.2 are searched; amounts, dates and category
labels are never matched. Money is passed through without arithmetic.
"""

from __future__ import annotations

from dataclasses import dataclass
from typing import TYPE_CHECKING, Any

from logstead.models.result import Result
from logstead.services.search_config import SEARCH_CONFIG, SearchConfig
from logstead.services.search_match import (
    link_for,
    match_rank,
    sort_key,
    tokenize,
)
from logstead.util.money import Money

if TYPE_CHECKING:
    from logstead.services.business import BusinessService
    from logstead.services.depreciation import DepreciationService
    from logstead.services.loan import LoanService
    from logstead.services.property import PropertyService
    from logstead.services.transaction import TransactionService

#: Fixed response order of the groups.
GROUP_KINDS: tuple[str, ...] = (
    "property",
    "transaction",
    "itemized_entry",
    "asset",
    "loan",
    "business",
)


@dataclass(frozen=True)
class SearchHit:
    kind: str
    id: str
    property_id: str | None
    title: str
    subtitle: str | None
    matched_field: str
    link: str
    amount: Money | None
    date: str | None


@dataclass(frozen=True)
class SearchGroup:
    kind: str
    total: int
    hits: tuple[SearchHit, ...]


@dataclass(frozen=True)
class SearchResult:
    query: str
    groups: tuple[SearchGroup, ...]
    truncated: bool
    scanned: int


class SearchService:
    """Substring search with ranking, bounded by ``config.scan_cap``."""

    def __init__(
        self,
        properties: "PropertyService",
        transactions: "TransactionService",
        depreciation: "DepreciationService",
        loans: "LoanService",
        businesses: "BusinessService",
        config: SearchConfig = SEARCH_CONFIG,
    ) -> None:
        self._properties = properties
        self._transactions = transactions
        self._depreciation = depreciation
        self._loans = loans
        self._businesses = businesses
        self._config = config

    def search(
        self,
        q: str,
        *,
        limit: int | None = None,
        property_id: str | None = None,
    ) -> Result[SearchResult]:
        cfg = self._config
        query = q.strip() if isinstance(q, str) else ""
        if not (cfg.min_query_length <= len(query) <= cfg.max_query_length):
            return Result.failure(
                "validation",
                f"q must be between {cfg.min_query_length} and "
                f"{cfg.max_query_length} characters.",
                field="q",
            )
        if limit is None:
            limit = cfg.default_limit
        elif isinstance(limit, bool) or not isinstance(limit, int):
            return Result.failure(
                "validation", "limit must be an integer.", field="limit"
            )
        elif not 1 <= limit <= cfg.max_limit:
            return Result.failure(
                "validation",
                f"limit must be between 1 and {cfg.max_limit}.",
                field="limit",
            )

        tokens = tokenize(query, cfg.max_tokens)
        if not tokens:
            return Result.failure(
                "validation", "q must contain searchable text.", field="q"
            )

        properties = self._properties.list()
        if property_id is not None:
            properties = [p for p in properties if p.id == property_id]
            if not properties:
                return Result.failure(
                    "not_found", "Property not found.", field="propertyId"
                )

        found: dict[str, list[tuple[tuple, SearchHit]]] = {k: [] for k in GROUP_KINDS}

        scanned = 0
        truncated = False
        count = len(properties)
        for index, prop in enumerate(properties):
            if scanned >= cfg.scan_cap:
                truncated = True
                break
            pid = prop.id
            names = prop.name or ""

            if property_id is None:
                ranked = match_rank(
                    tokens,
                    [("name", names), ("address_text", prop.address_text or "")],
                )
                if ranked is not None:
                    self._add_hit(
                        found,
                        "property",
                        ranked,
                        SearchHit(
                            kind="property",
                            id=pid,
                            property_id=pid,
                            title=names,
                            subtitle=prop.address_text or None,
                            matched_field=ranked[1],
                            link=link_for("property", pid, pid),
                            amount=None,
                            date=None,
                        ),
                    )

            txns = self._transactions.list_for_property(pid)
            if txns.error is not None:
                return self._propagate(txns.error)
            assets = self._depreciation.list_assets(pid)
            loans = self._loans.list_loans(pid)
            if loans.error is not None:
                return self._propagate(loans.error)

            scanned += len(txns.value) + len(assets) + len(loans.value)

            for t in txns.value:
                itemized = bool(t.itemized)
                kind = "itemized_entry" if itemized else "transaction"
                fields = [("description", t.description or "")]
                if itemized:
                    fields.append(("notes", t.notes or ""))
                ranked = match_rank(tokens, fields)
                if ranked is None:
                    continue
                year = (t.date or "")[:4]
                try:
                    link = link_for(kind, pid, t.id, year)
                except ValueError:
                    continue
                self._add_hit(
                    found,
                    kind,
                    ranked,
                    SearchHit(
                        kind=kind,
                        id=t.id,
                        property_id=pid,
                        title=t.description or "",
                        subtitle=f"{names} · {t.date}",
                        matched_field=ranked[1],
                        link=link,
                        amount=t.amount,
                        date=t.date,
                    ),
                )

            for a in assets:
                ranked = match_rank(tokens, [("description", a.description or "")])
                if ranked is None:
                    continue
                try:
                    link = link_for("asset", pid, a.id)
                except ValueError:
                    continue
                self._add_hit(
                    found,
                    "asset",
                    ranked,
                    SearchHit(
                        kind="asset",
                        id=a.id,
                        property_id=pid,
                        title=a.description or "",
                        subtitle=names,
                        matched_field=ranked[1],
                        link=link,
                        amount=a.cost_basis,
                        date=None,
                    ),
                )

            for ln in loans.value:
                ranked = match_rank(tokens, [("description", ln.description or "")])
                if ranked is None:
                    continue
                try:
                    link = link_for("loan", pid, ln.id)
                except ValueError:
                    continue
                self._add_hit(
                    found,
                    "loan",
                    ranked,
                    SearchHit(
                        kind="loan",
                        id=ln.id,
                        property_id=pid,
                        title=ln.description or "",
                        subtitle=names,
                        matched_field=ranked[1],
                        link=link,
                        amount=None,
                        date=None,
                    ),
                )

            # The cap is reached with unread properties left.
            if scanned >= cfg.scan_cap and index + 1 < count:
                truncated = True
                break

        if property_id is None:
            for b in self._businesses.list():
                ranked = match_rank(
                    tokens,
                    [
                        ("legal_name", b.legal_name or ""),
                        ("business_address", b.business_address or ""),
                    ],
                )
                if ranked is None:
                    continue
                try:
                    link = link_for("business", None, b.id)
                except ValueError:
                    continue
                self._add_hit(
                    found,
                    "business",
                    ranked,
                    SearchHit(
                        kind="business",
                        id=b.id,
                        property_id=None,
                        title=b.legal_name or "",
                        subtitle=b.business_address or None,
                        matched_field=ranked[1],
                        link=link,
                        amount=None,
                        date=None,
                    ),
                )

        groups = []
        for kind in GROUP_KINDS:
            entries = sorted(found[kind], key=lambda e: e[0])
            groups.append(
                SearchGroup(
                    kind=kind,
                    total=len(entries),
                    hits=tuple(h for _, h in entries[:limit]),
                )
            )
        return Result.success(
            SearchResult(
                query=" ".join(tokens),
                groups=tuple(groups),
                truncated=truncated,
                scanned=scanned,
            )
        )

    @staticmethod
    def _add_hit(
        found: dict[str, list[tuple[tuple, SearchHit]]],
        kind: str,
        ranked: tuple[int, str],
        hit: SearchHit,
    ) -> None:
        found[kind].append((sort_key(hit, ranked[0]), hit))

    @staticmethod
    def _propagate(error: Any) -> Result[SearchResult]:
        return Result.failure(
            error.kind, error.message, field=error.field, errors=error.errors
        )
