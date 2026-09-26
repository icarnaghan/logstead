"""Schedule E category catalog: definition, seeding, and listing (Requirement 7).

The set of user-assignable Schedule E categories is fixed reference data, not
user content. This module is the single source of truth for that catalog and
provides the two operations the rest of the system needs:

* :func:`seed_categories` — write the catalog into the single table as
  ``CATEGORY#<id> / META`` items (idempotent; re-seeding overwrites).
* :func:`list_categories` — read the seeded catalog back as
  :class:`ScheduleECategory` objects.

Catalog contents (Requirements 7.1, 7.2, 7.5)
---------------------------------------------
Income categories (Schedule E Part I income lines):

* Rents received — Line 3
* Royalties received — Line 4

Expense categories (Schedule E Part I expense lines):

* Advertising (5), Auto and travel (6), Cleaning and maintenance (7),
  Commissions (8), Insurance (9), Legal and other professional fees (10),
  Management fees (11), Mortgage interest paid to banks (12), Other interest
  (13), Repairs (14), Supplies (15), Taxes (16), Utilities (17), and Other (19).

Line 18 (Depreciation) is **intentionally excluded** from the assignable
catalog (Requirement 7.5): depreciation on the report is derived from the
depreciation schedules, not from a user-assigned transaction category.

The "Other" expense category (Line 19) is flagged ``requires_description`` so a
transaction assigned to it must carry a free-text description (Requirement 7.4).

DynamoDB item shape (design.md "ScheduleECategory reference")
-------------------------------------------------------------
Keys come from :mod:`logstead.repository.keys` (``PK=CATEGORY#<id>``, ``SK=META``).
Attributes are stored in the design's camelCase form: ``kind``, ``label``,
``scheduleELine`` (int), and ``requiresDescription`` (bool). ``id`` is stored so
reads can reconstruct the category without re-parsing the key.
"""

from __future__ import annotations

from typing import TYPE_CHECKING

from logstead.models.category import ScheduleECategory
from logstead.repository import keys

if TYPE_CHECKING:
    from logstead.repository.dynamo_repo import DynamoRepository


__all__ = ["CATEGORY_CATALOG", "seed_categories", "list_categories"]


# --- The fixed catalog -------------------------------------------------------
#
# Order mirrors Schedule E Part I: income lines first (3, 4), then expense lines
# in line order (5-17), then Other (19). Line 18 (Depreciation) is deliberately
# absent (Requirement 7.5). Ids are stable slugs so transactions can reference a
# category id that never changes across re-seeds.

CATEGORY_CATALOG: tuple[ScheduleECategory, ...] = (
    # Income (Requirement 7.1)
    ScheduleECategory(id="rents-received", kind="income",
                      label="Rents received", schedule_e_line=3),
    ScheduleECategory(id="royalties-received", kind="income",
                      label="Royalties received", schedule_e_line=4),
    # Expenses (Requirement 7.2)
    ScheduleECategory(id="advertising", kind="expense",
                      label="Advertising", schedule_e_line=5),
    ScheduleECategory(id="auto-and-travel", kind="expense",
                      label="Auto and travel", schedule_e_line=6),
    ScheduleECategory(id="cleaning-and-maintenance", kind="expense",
                      label="Cleaning and maintenance", schedule_e_line=7),
    ScheduleECategory(id="commissions", kind="expense",
                      label="Commissions", schedule_e_line=8),
    ScheduleECategory(id="insurance", kind="expense",
                      label="Insurance", schedule_e_line=9),
    ScheduleECategory(id="legal-and-professional-fees", kind="expense",
                      label="Legal and other professional fees",
                      schedule_e_line=10),
    ScheduleECategory(id="management-fees", kind="expense",
                      label="Management fees", schedule_e_line=11),
    ScheduleECategory(id="mortgage-interest-banks", kind="expense",
                      label="Mortgage interest paid to banks",
                      schedule_e_line=12),
    ScheduleECategory(id="other-interest", kind="expense",
                      label="Other interest", schedule_e_line=13),
    ScheduleECategory(id="repairs", kind="expense",
                      label="Repairs", schedule_e_line=14),
    ScheduleECategory(id="supplies", kind="expense",
                      label="Supplies", schedule_e_line=15),
    ScheduleECategory(id="taxes", kind="expense",
                      label="Taxes", schedule_e_line=16),
    ScheduleECategory(id="utilities", kind="expense",
                      label="Utilities", schedule_e_line=17),
    # Line 18 (Depreciation) intentionally omitted (Requirement 7.5).
    ScheduleECategory(id="other", kind="expense",
                      label="Other", schedule_e_line=19,
                      requires_description=True),
)


# --- Serialization boundary --------------------------------------------------

def _to_item(category: ScheduleECategory) -> dict[str, object]:
    """Render a category as its DynamoDB item (design camelCase attributes)."""
    return {
        "PK": keys.category_pk(category.id),
        "SK": keys.category_sk(),
        "id": category.id,
        "kind": category.kind,
        "label": category.label,
        "scheduleELine": category.schedule_e_line,
        "requiresDescription": category.requires_description,
    }


def _from_item(item: dict[str, object]) -> ScheduleECategory:
    """Reconstruct a category from a stored item."""
    return ScheduleECategory(
        id=str(item["id"]),
        kind=item["kind"],  # type: ignore[arg-type]  # "income" | "expense"
        label=str(item["label"]),
        schedule_e_line=int(item["scheduleELine"]),  # type: ignore[arg-type]
        requires_description=bool(item.get("requiresDescription", False)),
    )


# --- Public operations -------------------------------------------------------

def seed_categories(repo: "DynamoRepository") -> tuple[ScheduleECategory, ...]:
    """Write the fixed category catalog into the table (Requirements 7.1, 7.2).

    Each catalog entry becomes a ``CATEGORY#<id> / META`` item. The operation is
    idempotent: re-seeding overwrites existing items with identical content, so
    it is safe to run at deploy time or from a maintenance task.

    Returns the seeded catalog for convenience.
    """
    for category in CATEGORY_CATALOG:
        repo.put_item(_to_item(category))
    return CATEGORY_CATALOG


def list_categories(repo: "DynamoRepository") -> list[ScheduleECategory]:
    """Read the seeded catalog back (Requirements 7.1, 7.2).

    Categories share the ``CATEGORY#`` key prefix but each lives in its own
    partition, so this reads each catalog id directly and returns them in
    Schedule E line order. Absent items are skipped, so a partially seeded table
    still returns what is present.
    """
    result: list[ScheduleECategory] = []
    for category in CATEGORY_CATALOG:
        item = repo.get_item(keys.category_pk(category.id), keys.category_sk())
        if item is not None:
            result.append(_from_item(item))
    return result
