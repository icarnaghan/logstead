"""Pure helpers for slugs and ZIP entry paths in the accountant package.

Property names, category labels, and receipt filenames are user text. Every
entry path is computed from a slug or ``sanitize_filename`` and then checked
with :func:`is_safe_entry_path`.
"""

from __future__ import annotations

import re
import unicodedata
from collections.abc import Sequence
from datetime import date

from logstead.adapters.s3_files import sanitize_filename

MAX_SLUG_LENGTH = 40
MAX_ENTRY_PATH_LENGTH = 200
_ID_SUFFIX_LENGTH = 6
_TXN_PREFIX_LENGTH = 8

_NON_SLUG = re.compile(r"[^a-z0-9]+")
_SAFE_PATH = re.compile(r"[A-Za-z0-9._/-]+")
_UNSAFE_NAME_CHARS = re.compile(r"[^A-Za-z0-9._-]")
_SPLIT_EXT = re.compile(r"^(?P<stem>.*?)(?P<ext>\.[A-Za-z0-9]{1,10})?$", re.DOTALL)


def slugify(text: str | None, fallback: str) -> str:
    """Return a lowercase ASCII slug of letters, digits, and single hyphens.

    At most ``MAX_SLUG_LENGTH`` characters, with no leading or trailing hyphen.
    Uses ``fallback`` (slugified the same way, then ``"item"``) when nothing
    usable remains.
    """

    def _clean(value: str | None) -> str:
        ascii_text = (
            unicodedata.normalize("NFKD", str(value or ""))
            .encode("ascii", "ignore")
            .decode("ascii")
            .lower()
        )
        return _NON_SLUG.sub("-", ascii_text)[:MAX_SLUG_LENGTH].strip("-")

    return _clean(text) or _clean(fallback) or "item"


def unique_slugs(items: Sequence[tuple[str, str]]) -> dict[str, str]:
    """Map ``(id, name)`` pairs to unique slugs, keyed by id.

    A later item whose slug is taken gets ``-`` plus the first six characters
    of its id. If that is still taken, a numeric suffix is added.
    """
    result: dict[str, str] = {}
    taken: set[str] = set()
    for item_id, name in items:
        base = slugify(name, "item")
        slug = base
        if slug in taken:
            suffix = slugify(str(item_id)[:_ID_SUFFIX_LENGTH], "id")
            slug = f"{base[: MAX_SLUG_LENGTH - len(suffix) - 1].rstrip('-')}-{suffix}"
            counter = 2
            candidate = slug
            while candidate in taken:
                candidate = f"{slug}-{counter}"
                counter += 1
            slug = candidate
        taken.add(slug)
        result[item_id] = slug
    return result


def _split_extension(name: str) -> tuple[str, str]:
    match = _SPLIT_EXT.match(name)
    if match is None:  # pragma: no cover - the pattern matches every string
        return name, ""
    return match.group("stem"), match.group("ext") or ""


def _fit(stem: str, ext: str, budget: int) -> str:
    """Join ``stem`` and ``ext`` within ``budget`` characters, trimming the stem."""
    budget = max(budget, 1)
    if len(stem) + len(ext) <= budget:
        return stem + ext
    if len(ext) >= budget:
        ext = ""
    return (stem[: budget - len(ext)] or "f") + ext


def receipt_entry_path(
    property_slug: str,
    category_slug: str,
    entry_date: date | str,
    transaction_id: str,
    filename: str | None,
) -> str:
    """Return ``receipts/<property>/<category>/<date>_<txn8>_<filename>``.

    The filename passes through ``sanitize_filename`` and is then reduced to
    ``[A-Za-z0-9._-]``. It is shortened as needed so the whole path stays
    within ``MAX_ENTRY_PATH_LENGTH``.
    """
    date_text = entry_date.isoformat() if isinstance(entry_date, date) else str(entry_date)
    date_part = _UNSAFE_NAME_CHARS.sub("_", date_text)
    txn_part = _UNSAFE_NAME_CHARS.sub("_", str(transaction_id)[:_TXN_PREFIX_LENGTH]) or "txn"
    prop = slugify(property_slug, "property")
    cat = slugify(category_slug, "uncategorized")
    prefix = f"receipts/{prop}/{cat}/{date_part}_{txn_part}_"

    name = _UNSAFE_NAME_CHARS.sub("_", sanitize_filename(filename))
    stem, ext = _split_extension(name)
    # Leave room for a "-NN" dedupe suffix added later.
    budget = MAX_ENTRY_PATH_LENGTH - len(prefix) - 4
    return prefix + _fit(stem, ext, budget)


def is_safe_entry_path(path: str) -> bool:
    """True when ``path`` is a valid package entry path."""
    if not isinstance(path, str) or not path or len(path) > MAX_ENTRY_PATH_LENGTH:
        return False
    if _SAFE_PATH.fullmatch(path) is None:
        return False
    if path.startswith("/") or "\\" in path:
        return False
    return all(segment not in ("", "..") for segment in path.split("/"))


def dedupe_entry_path(path: str, taken: set[str]) -> str:
    """Return ``path``, or ``path`` with ``-2``, ``-3``, ... before the extension.

    Does not modify ``taken``. The result stays within the length limit.
    """
    if path not in taken:
        return path
    directory, slash, name = path.rpartition("/")
    stem, ext = _split_extension(name)
    counter = 2
    while True:
        suffix = f"-{counter}"
        budget = MAX_ENTRY_PATH_LENGTH - len(directory) - len(slash) - len(suffix) - len(ext)
        candidate = f"{directory}{slash}{stem[: max(budget, 1)]}{suffix}{ext}"
        if candidate not in taken:
            return candidate
        counter += 1
