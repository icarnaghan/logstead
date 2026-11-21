"""Property tests for the pure search matching helpers (ui-polish task 7.2)."""

from __future__ import annotations

from datetime import date, timedelta

from hypothesis import given, settings
from hypothesis import strategies as st

from logstead.services.search_config import SEARCH_CONFIG
from logstead.services.search_match import (
    RANK_EXACT,
    RANK_SUBSTRING,
    RANK_WORD_PREFIX,
    match_rank,
    normalize,
    sort_key,
    tokenize,
)

_COMBINING = "\u0301\u0308\u0327\u0323"
_PATTERN_CHARS = "*%\\.?[](){}+^$|_"

# Full unicode (no surrogates) plus targeted combining marks and pattern chars.
texts = st.one_of(
    st.text(max_size=60),
    st.text(
        alphabet=st.sampled_from(
            list("aeAEnNßİıﬁ Ａ１ \t\u00a0" + _COMBINING + _PATTERN_CHARS)
        ),
        max_size=40,
    ),
)
words = st.text(
    alphabet=st.sampled_from(list("abcXYZ019éÉßİ" + _COMBINING + _PATTERN_CHARS)),
    min_size=1,
    max_size=8,
).filter(lambda w: normalize(w) != "" and " " not in normalize(w))


# Feature: ui-polish, Property 9: Query normalization is idempotent
# **Validates: Requirements 9.1, 9.8**
@settings(max_examples=200, deadline=None)
@given(s=texts, max_tokens=st.integers(min_value=1, max_value=SEARCH_CONFIG.max_tokens))
def test_normalize_idempotent_and_tokens_wellformed(s: str, max_tokens: int) -> None:
    n = normalize(s)
    assert normalize(n) == n
    toks = tokenize(s, max_tokens)
    assert len(toks) <= max_tokens
    for t in toks:
        assert t != ""
        assert normalize(t) == t
        assert not any(c.isspace() for c in t)


# Feature: ui-polish, Property 8 (pure part): Search matching
# **Validates: Requirements 9.2, 9.9**
@settings(max_examples=200, deadline=None)
@given(
    fields=st.lists(st.tuples(st.sampled_from(["a", "b", "c"]), texts), max_size=4),
    query=texts,
)
def test_every_match_contains_every_token(fields, query) -> None:
    toks = tokenize(query, SEARCH_CONFIG.max_tokens)
    result = match_rank(toks, fields)
    joined = " ".join(normalize(t) for _, t in fields)
    if result is None:
        # No match: either no tokens, or some token is absent from the text.
        assert not toks or any(t not in joined for t in toks)
        return
    rank, name = result
    assert toks
    assert all(t in joined for t in toks)
    assert rank in (RANK_EXACT, RANK_WORD_PREFIX, RANK_SUBSTRING)
    assert name in {n for n, _ in fields}


@settings(max_examples=200, deadline=None)
@given(
    prefix=words, middle=words, suffix=words, data=st.data(),
)
def test_substring_of_field_always_matches_and_pattern_chars_are_literal(
    prefix, middle, suffix, data
) -> None:
    text = f"{prefix} {middle} {suffix}"
    fields = [("description", text)]
    norm = normalize(text)
    # Any substring of the normalized field text (single token) must match.
    i = data.draw(st.integers(0, len(norm) - 1))
    j = data.draw(st.integers(i + 1, len(norm)))
    piece = norm[i:j].strip()
    if piece and " " not in piece:
        assert match_rank(tokenize(piece, 5), fields) is not None
    # The whole field, as a query, is an exact match (rank 0).
    # (three words, so within the five-token cap).
    assert match_rank(tokenize(text, 5), fields) == (RANK_EXACT, "description")


@settings(max_examples=100, deadline=None)
@given(left=words, right=words)
def test_pattern_characters_are_not_wildcards(left, right) -> None:
    # "left.right" in the data must not be matched by wildcard-like queries.
    text = f"{left}-{right}"
    for wildcard in ("*", "%", ".", "?"):
        q = tokenize(f"{left}{wildcard}{right}", 5)
        got = match_rank(q, [("f", text)])
        joined = normalize(text)
        if got is not None:
            assert all(t in joined for t in q)
    # Literal pattern characters in the data are found literally.
    literal = f"{left}.*{right}"
    assert match_rank(tokenize(".*", 5), [("f", literal)]) is not None


def test_pattern_characters_unit_examples() -> None:
    assert match_rank(["a*c"], [("f", "abc")]) is None
    assert match_rank(["a.c"], [("f", "abc")]) is None
    assert match_rank(["a%c"], [("f", "abc")]) is None
    assert match_rank(["a*c"], [("f", "xa*cx")]) == (RANK_SUBSTRING, "f")
    assert match_rank(["\\"], [("f", "C:\\temp")]) == (RANK_SUBSTRING, "f")
    assert match_rank(tokenize("CAFE\u0301", 5), [("f", "Caf\u00e9")]) == (RANK_EXACT, "f")
    assert match_rank(["rep"], [("f", "Roof repair")]) == (RANK_WORD_PREFIX, "f")


# Feature: ui-polish, Property 10 (pure part): Search order and determinism
# **Validates: Requirements 9.4, 9.7**
hits = st.lists(
    st.fixed_dictionaries(
        {
            "rank": st.integers(0, 2),
            "date": st.integers(0, 30).map(lambda d: (date(2024, 1, 1) + timedelta(d)).isoformat()),
            "title": st.sampled_from(["", "alpha", "Alpha", "beta", "Éclair", "eclair", "z"]),
            "id": st.text(alphabet="abc123", min_size=1, max_size=3),
        }
    ),
    max_size=15,
)


@settings(max_examples=200, deadline=None)
@given(items=hits, seed=st.randoms(use_true_random=False))
def test_sort_is_deterministic_and_ordered(items, seed) -> None:
    ordered = sorted(items, key=sort_key)
    shuffled = list(items)
    seed.shuffle(shuffled)
    again = sorted(shuffled, key=sort_key)
    # Identical keys imply identical hits except for exact duplicates on the key.
    assert [sort_key(h) for h in ordered] == [sort_key(h) for h in again]
    assert sorted(ordered, key=sort_key) == ordered

    for a, b in zip(ordered, ordered[1:], strict=False):
        assert a["rank"] <= b["rank"]
        if a["rank"] == b["rank"]:
            assert a["date"] >= b["date"]
            if a["date"] == b["date"]:
                assert normalize(a["title"]) <= normalize(b["title"])
                if a["title"] == b["title"]:
                    assert a["id"] <= b["id"]
