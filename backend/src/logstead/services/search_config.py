"""Limits for the global search service."""

from __future__ import annotations

from dataclasses import dataclass


@dataclass(frozen=True)
class SearchConfig:
    min_query_length: int = 2
    max_query_length: int = 100
    max_tokens: int = 5
    default_limit: int = 5
    max_limit: int = 25
    scan_cap: int = 20_000


SEARCH_CONFIG = SearchConfig()
