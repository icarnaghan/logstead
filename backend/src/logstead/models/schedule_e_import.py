"""Service-layer models for Schedule E Import.

These dataclasses describe the input and output shapes exchanged between the
router and the ``ImportService``. They mirror a real IRS Schedule E Part I
page: a single :class:`ImportSubmission` carries one ``tax_year`` and one or
more :class:`PropertyEntryInput` columns, each with its own property mapping
and its own set of per-line amounts.

No money is parsed in this module. Amounts arrive as strings from the SPA (or
as :class:`decimal.Decimal`) and are passed through verbatim; the service runs
them through the ``util/money`` boundary (``to_money`` / ``money_to_str``), so
the two-decimal money convention is enforced in exactly one place.

The outcome shapes (:class:`EntryOutcome`, :class:`ImportOutcome`,
:class:`RemoveOutcome`) report the per-entry result of an import or the undo of
a prior imported set back to the caller.
"""

from __future__ import annotations

from dataclasses import dataclass, field
from decimal import Decimal

from logstead.models.property import PropertyInput


@dataclass
class LineAmountInput:
    """One Schedule E line amount within a :class:`PropertyEntryInput` (Req 4.1).

    Attributes:
        schedule_e_line: The IRS Schedule E Part I line number. Income lines are
            3 (Rents) and 4 (Royalties); expense lines are 5-17 and 19 (Other).
            Line 18 (Depreciation) is never accepted and the service rejects it.
        amount: The entered money amount as a string from the SPA (or a
            ``Decimal``). ``None`` or blank is treated as the zero Money_Value by
            the service (Req 4.2); no parsing happens here.
        description: Free-text description used only for Line 19 (Other). When
            omitted, the service applies the default description (Req 6.6).
    """

    schedule_e_line: int
    amount: str | Decimal | None
    description: str | None = None


@dataclass
class PropertyEntryInput:
    """One Schedule E Part I property column (Req 1.3, 2).

    Exactly one of ``property_id`` / ``new_property`` is set: either the entry
    maps to an existing owned property, or it carries a :class:`PropertyInput`
    for inline creation (reusing the existing property-creation capability).

    Attributes:
        property_id: Id of an existing property owned by the user, or ``None``
            when the entry creates a property inline.
        new_property: Input for inline property creation, or ``None`` when the
            entry maps to an existing ``property_id``.
        lines: The per-line amounts for this property column; defaults to an
            empty list. Blank/absent lines are treated as zero by the service.
    """

    property_id: str | None = None
    new_property: PropertyInput | None = None
    lines: list[LineAmountInput] = field(default_factory=list)


@dataclass
class ImportSubmission:
    """The whole multi-property, single-year submission (Req 1, 3).

    Attributes:
        tax_year: The single Tax_Year shared by every entry, or ``None`` when
            the user has not selected one (rejected by the service, Req 1.7/3.2).
        entries: One or more property columns in the submission.
    """

    tax_year: int | None
    entries: list[PropertyEntryInput]


@dataclass
class EntryOutcome:
    """Per-entry result of an import (Req 1.5).

    Attributes:
        property_id: The resolved property id (existing or newly inline-created).
        created_transaction_ids: Ids of the Summary_Transactions written for this
            entry's non-zero lines.
        deleted_prior_count: Count of prior imported rows replaced for this
            (Property, Tax_Year) during replace-on-reimport.
        created_inline_property: ``True`` when this entry created its property
            inline during the write phase.
    """

    property_id: str
    created_transaction_ids: list[str]
    deleted_prior_count: int
    created_inline_property: bool


@dataclass
class ImportOutcome:
    """The overall result of an import, reported per entry (Req 1.5).

    Attributes:
        tax_year: The Tax_Year the submission applied to.
        entries: The per-entry outcomes, one per submitted property column.
    """

    tax_year: int
    entries: list[EntryOutcome]


@dataclass
class RemoveOutcome:
    """The result of removing one (Property, Tax_Year) imported set (Req 8 undo).

    Attributes:
        property_id: The property whose imported set was removed.
        tax_year: The Tax_Year cleared.
        deleted_count: Count of imported rows deleted; user-tracked rows are
            never selected or deleted.
    """

    property_id: str
    tax_year: int
    deleted_count: int


__all__ = [
    "LineAmountInput",
    "PropertyEntryInput",
    "ImportSubmission",
    "EntryOutcome",
    "ImportOutcome",
    "RemoveOutcome",
]
