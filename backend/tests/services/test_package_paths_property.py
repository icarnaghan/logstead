"""Property test for accountant package entry paths and S3 keys.

# Feature: accountant-package, Property 9: Entry paths are safe and unique

**Validates: Requirements 8.5, 8.6, 8.8, 10.2, 15.6**
"""

from __future__ import annotations

import re
from datetime import date

from hypothesis import given, settings
from hypothesis import strategies as st

from logstead.adapters.s3_files import package_key, pdf_key
from logstead.services.package_paths import (
    MAX_ENTRY_PATH_LENGTH,
    dedupe_entry_path,
    is_safe_entry_path,
    receipt_entry_path,
    slugify,
    unique_slugs,
)

_SAFE_CHARS = re.compile(r"[A-Za-z0-9._/-]+")

_ADVERSARIAL = st.sampled_from(
    ["", "..", "../..", "/", "\\", "a/b", "a\\b", "../../etc/passwd", "é日本語", ".", " ", "\x00\n\t"]
)
_NAMES = st.one_of(_ADVERSARIAL, st.text(max_size=120), st.text(alphabet="ab ./\\-_", max_size=60))
_FILENAMES = st.one_of(
    _ADVERSARIAL,
    st.text(max_size=300),
    st.builds(lambda s, e: s + "." + e, st.text(max_size=250), st.text(max_size=12)),
    st.text(alphabet="a./\\ ", min_size=1, max_size=300),
)
_IDS = st.text(alphabet="0123456789abcdef-", min_size=8, max_size=36)
_DATES = st.dates(min_value=date(1990, 1, 1), max_value=date(2100, 12, 31))
_SEGMENT = st.text(alphabet="abcdefghijklmnopqrstuvwxyz0123456789-", min_size=1, max_size=36)


@settings(max_examples=150, deadline=None)
@given(
    names=st.lists(_NAMES, min_size=1, max_size=8),
    categories=st.lists(_NAMES, min_size=1, max_size=4),
    receipts=st.lists(
        st.tuples(st.integers(0, 7), st.integers(0, 3), _DATES, _IDS, _FILENAMES),
        min_size=1,
        max_size=15,
    ),
    duplicate=st.booleans(),
)
def test_entry_paths_are_safe_and_unique(names, categories, receipts, duplicate):
    if duplicate:
        names = names + names[:1]
    prop_ids = [f"{i:02d}{'p' * 30}" for i in range(len(names))]
    prop_slugs = unique_slugs(list(zip(prop_ids, names, strict=True)))
    cat_ids = [f"{i:02d}{'c' * 30}" for i in range(len(categories))]
    cat_slugs = unique_slugs(list(zip(cat_ids, categories, strict=True)))

    # Slugs: allowed alphabet, bounded, unique.
    assert len(set(prop_slugs.values())) == len(prop_ids)
    for slug in [*prop_slugs.values(), *cat_slugs.values()]:
        assert re.fullmatch(r"[a-z0-9-]+", slug)
        assert not slug.startswith("-") and not slug.endswith("-")
        assert ".." not in slug

    taken: set[str] = set()
    for p_idx, c_idx, when, txn_id, filename in receipts:
        pslug = prop_slugs[prop_ids[p_idx % len(prop_ids)]]
        cslug = cat_slugs[cat_ids[c_idx % len(cat_ids)]]
        raw = receipt_entry_path(pslug, cslug, when, txn_id, filename)
        path = dedupe_entry_path(raw, taken)

        assert is_safe_entry_path(path), path
        assert _SAFE_CHARS.fullmatch(path)
        assert not path.startswith("/")
        assert "\\" not in path
        assert ".." not in path.split("/")
        assert len(path) <= MAX_ENTRY_PATH_LENGTH
        assert path not in taken
        # Receipt paths carry property slug, category slug, date, and txn prefix.
        assert path.startswith(f"receipts/{pslug}/{cslug}/")
        assert when.isoformat() in path
        assert txn_id[:8] in path
        taken.add(path)

    assert len(taken) == len(receipts)


@settings(max_examples=100, deadline=None)
@given(text=st.one_of(_NAMES, st.text()), fallback=_NAMES)
def test_slugify_is_always_safe(text, fallback):
    slug = slugify(text, fallback)
    assert re.fullmatch(r"[a-z0-9-]{1,40}", slug)
    assert not slug.startswith("-") and not slug.endswith("-")


@settings(max_examples=100, deadline=None)
@given(path=st.text(max_size=250))
def test_is_safe_entry_path_rejects_unsafe_input(path):
    if is_safe_entry_path(path):
        assert _SAFE_CHARS.fullmatch(path)
        assert not path.startswith("/")
        assert "\\" not in path
        assert ".." not in path.split("/")
        assert len(path) <= MAX_ENTRY_PATH_LENGTH


def test_is_safe_entry_path_examples():
    assert is_safe_entry_path("receipts/a/b/2024-01-01_abcd1234_f.pdf")
    for bad in ["", "/abs", "a/../b", "a\\b", "a b", "a//b", "x" * 201, "é"]:
        assert not is_safe_entry_path(bad)


@settings(max_examples=100, deadline=None)
@given(
    user_id=_SEGMENT,
    job_id=_SEGMENT,
    random_id=_SEGMENT,
    year=st.integers(1990, 2100),
    filename=st.from_regex(r"[a-z0-9-]{1,30}\.pdf", fullmatch=True),
)
def test_s3_keys_match_server_built_shape(user_id, job_id, random_id, year, filename):
    pkg = package_key(user_id, job_id, year)
    assert re.fullmatch(
        rf"exports/packages/{re.escape(user_id)}/{re.escape(job_id)}/logstead-accountant-package-{year}\.zip",
        pkg,
    )
    pdf = pdf_key(user_id, random_id, filename)
    assert re.fullmatch(
        rf"exports/pdf/{re.escape(user_id)}/{re.escape(random_id)}/{re.escape(filename)}", pdf
    )
