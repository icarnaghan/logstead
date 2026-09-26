"""Schedule E category reference model (Requirement 7).

Categories are a fixed, seeded catalog mapping user-assignable
Transaction_Categories to their Schedule E line. Line 18 (Depreciation) is
intentionally excluded from assignable categories (Requirement 7.5).
"""

from __future__ import annotations

from dataclasses import dataclass
from typing import Literal

CategoryKind = Literal["income", "expense"]


@dataclass(frozen=True)
class ScheduleECategory:
    """A user-assignable Schedule E income or expense category.

    Attributes:
        id: Stable category identifier.
        kind: Whether the category is income or expense.
        label: Human-readable label (e.g., "Rents received").
        schedule_e_line: The Schedule E Part I line number this maps to.
        requires_description: True for the "Other" expense category (Line 19),
            which requires a free-text description (Requirement 7.4).
    """

    id: str
    kind: CategoryKind
    label: str
    schedule_e_line: int
    requires_description: bool = False
