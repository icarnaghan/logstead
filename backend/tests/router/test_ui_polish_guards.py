"""ui-polish guards: no new Python dependency, and exactly the four new routes.

Validates: Requirements 28.7, 29.2
"""

from __future__ import annotations

import re
from collections import Counter
from pathlib import Path

from logstead.router import handler as handler_module

REQUIREMENTS = Path(__file__).resolve().parents[2] / "requirements.txt"

# Names committed for the runtime (reportlab arrived with the PDF work, not ui-polish).
RUNTIME_NAMES = {"boto3", "pdfplumber", "pypdf", "reportlab"}


def _names(path: Path) -> set[str]:
    names = set()
    for line in path.read_text().splitlines():
        line = line.split("#", 1)[0].strip()
        if line and not line.startswith("-"):
            names.add(re.split(r"[=<>!~\[; ]", line, maxsplit=1)[0].lower())
    return names


def test_requirements_names_unchanged() -> None:
    assert _names(REQUIREMENTS) == RUNTIME_NAMES


def test_four_new_routes_registered_once_each() -> None:
    counts = Counter((m, p) for m, p, *_ in handler_module._ROUTES)
    new = {
        ("GET", "/search"),
        ("GET", "/activity"),
        ("GET", "/properties/{propertyId}/activity"),
        ("POST", "/properties/{propertyId}/activity/{eventId}/restore"),
    }
    for route in new:
        assert counts[route] == 1, route
    assert all(c == 1 for c in counts.values()), [r for r, c in counts.items() if c > 1]


def test_search_and_activity_accept_get_only() -> None:
    for path in ("/search", "/activity", "/properties/{propertyId}/activity"):
        methods = {m for m, p, *_ in handler_module._ROUTES if p == path}
        assert methods == {"GET"}, path
