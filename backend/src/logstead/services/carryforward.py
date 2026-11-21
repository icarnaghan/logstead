"""Passive loss carryforward reconciliation service.

This service adds a portfolio-level **passive loss carryforward reconciliation**
to Logstead. It derives each Data_Year's Schedule E net by reusing
:meth:`ReportingService.report_for` across the authenticated user's properties,
rolls a running non-negative suspended-loss balance forward from an optional
opening balance, merges in the user-entered per-year figures, and classifies
each year ``ok`` / ``mismatch`` / ``carried`` / ``unreported``.

Carry-in semantics: the user-entered per-year value (stored in ``PLCF#<year>``
attribute ``amount``, wire field ``reported_carryforward``) is the Form 8582
"Prior years unallowed losses" line of that year's return, i.e. the balance
carried **into** the year from earlier years. Each year exposes an
``expected_carry_in`` (the balance expected to enter the year: the opening
balance for the first year, otherwise the prior year's carry-out) and an
``expected_carryforward`` (the expected carry-out: the year's step applied to
its carry-in). The reported carry-in is compared with ``expected_carry_in``;
``drift`` is ``reported - expected_carry_in``. A ``carried`` year's reported
carry-in equals the prior year's step applied to the prior year's *reported*
carry-in, so it only inherits an earlier error; ``carried_from_year`` names the
most recent earlier ``mismatch`` year, i.e. the year whose carry-in was first
wrong (review the return for the year before it).

Status comparisons (``ok`` and ``carried``) hold when the amounts are within
``STATUS_TOLERANCE`` (``2.00``) because returns are filed in whole dollars;
``drift`` and the expected values stay exact to the cent.

It is a **reconciliation aid, not a tax engine**. The Expected_Carryforward is
the economic carryforward from Schedule E net alone and deliberately does
**not** apply the IRC §469 limitation (Form 8582, the $25,000 allowance, MAGI
phase-out, or real-estate-professional status), because the app collects none
of the inputs those rules require (Requirement 2.7, 8.3).

The service is **user-scoped**: every read and write is confined to the
authenticated user's ``USER#<userId>`` partition, so one user can never read or
modify another user's reported entries or opening balance (Requirement 1.3,
3.5, 7.5). Collaborators (the repository, reporting service, and property
service) are injected so the whole service can be exercised against ``moto``
with no live AWS call.

Money is :class:`util.money.Money` (a two-decimal ``Decimal``) in application
code throughout; the router serializes every figure as a fixed two-decimal
string over the wire (Requirement 1.4, 2.6, 3.6).
"""

from __future__ import annotations

from dataclasses import dataclass
from decimal import Decimal
from typing import TYPE_CHECKING, Literal

from logstead.models.result import Result
from logstead.models.user import UserContext
from logstead.repository import keys
from logstead.services.auth import user_id_of
from logstead.services.dashboard import derive_data_years
from logstead.util.money import Money, money_to_str, to_money

if TYPE_CHECKING:
    from logstead.repository.dynamo_repo import DynamoRepository
    from logstead.services.depreciation import DepreciationService
    from logstead.services.loan import LoanService
    from logstead.services.property import PropertyService
    from logstead.services.report import ReportingService
    from logstead.services.transaction import TransactionService


__all__ = [
    "STATUS_TOLERANCE",
    "ReconciledYear",
    "ReconciliationSummary",
    "CarryforwardService",
]


# The largest absolute difference (in dollars) between a reported carry-in and
# the expected / chain figure that still counts as a match. Returns are filed in
# whole dollars while the app computes to the cent, so a reported value within
# this tolerance is treated as matching. It applies to the status comparisons
# only (the ``ok`` and ``carried`` rules); ``drift``, ``expected_carry_in`` and
# ``expected_carryforward`` stay exact to the cent. Exact ``Decimal`` — never a
# float. Exposed on the wire as ``status_tolerance``.
STATUS_TOLERANCE = Decimal("2.00")


def _within_tolerance(a: Money, b: Money) -> bool:
    """Whether two amounts match within :data:`STATUS_TOLERANCE`.

    ``abs(a - b) <= STATUS_TOLERANCE`` in exact ``Decimal`` arithmetic, so a
    difference of exactly the tolerance matches and one cent more does not.
    Evaluated independently per comparison; tolerance never accumulates.
    """
    return abs(a - b) <= STATUS_TOLERANCE


# Sentinel distinguishing "leave this attribute as-is" from "clear it to None"
# in the per-year read-modify-write merge. A caller passing ``amount=None``
# means *drop* the attribute; omitting the kwarg (leaving it ``_UNSET``) means
# *preserve* whatever the stored item currently carries.
_UNSET = object()


@dataclass(frozen=True)
class ReconciledYear:
    """One reconciled Tax_Year in the Reconciliation_Series (Req 1, 2, 4).

    Carries the derived Schedule_E_Net, the expected carry-in and carry-out,
    the user-entered carry-in (when present), and the per-year
    Reconciliation_Status. Every monetary figure is a two-decimal
    :class:`~logstead.util.money.Money`; the router serializes each as a
    two-decimal string.

    Note the deliberate naming asymmetry on the wire: ``reported_carryforward``
    is a carry-IN while ``expected_carryforward`` is a carry-OUT. The latter
    keeps its original value and name so running-balance consumers are
    unaffected; ``expected_carry_in`` is what the reported value is compared
    with.

    Attributes:
        tax_year: The four-digit Data_Year every figure is derived for.
        schedule_e_net: The portfolio Schedule E net for the year; negative
            denotes a net loss (Req 1.4).
        expected_carryforward: The expected carry-OUT: the running
            Suspended_Loss_Balance after applying the year's step to
            ``expected_carry_in`` — a non-negative magnitude. It is the next
            year's ``expected_carry_in`` (Req 2.6).
        reported_carryforward: The carry-IN the user reported for the year: the
            Form 8582 "Prior years unallowed losses" line (a non-negative
            magnitude), or ``None`` when unreported (Req 3).
        allowed_loss: The Allowed_Loss amount applied to the year — a
            non-negative magnitude, ``0.00`` when none is stored (Req 1.6, 7.4).
            Defaults to the two-decimal zero so existing ``ReconciledYear(...)``
            call sites stay valid until a later task populates it explicitly.
        fully_allowed: The Fully_Allowed flag for the year — ``True`` when the
            whole loss for the year was allowed (Req 7.4). Defaults to ``False``
            (not fully allowed) for the same backward-compatibility reason.
        status: The Reconciliation_Status for the year: ``ok`` when the reported
            carry-in is within ``STATUS_TOLERANCE`` of ``expected_carry_in``,
            ``unreported`` when no reported value is stored, ``carried`` when
            it is outside tolerance of ``expected_carry_in`` but within
            tolerance of the prior year's step applied to
            the prior year's reported carry-in (the difference was inherited
            from an earlier mistake), and ``mismatch`` when it differs from
            both, i.e. the break occurred between the prior return's carry-out
            and this return's carry-in (Req 4.1-4.4).
        drift: ``reported_carryforward - expected_carry_in`` as a signed
            two-decimal value (positive means the return shows more than
            expected), or ``None`` when the year is unreported. Informational
            only; it never influences ``status``.
        carried_from_year: For a ``carried`` year, the tax year of the most
            recent earlier ``mismatch`` year (strictly less than ``tax_year``),
            i.e. the year whose carry-in was first wrong (review the return for
            the year before it), or ``None`` otherwise. Defaults to ``None``.
        expected_carry_in: The balance expected to enter the year: the
            Opening_Balance for the first year, otherwise the prior year's
            ``expected_carryforward``. What ``reported_carryforward`` is
            compared with. Defaults to the two-decimal zero so existing
            ``ReconciledYear(...)`` call sites stay valid.
    """

    tax_year: int
    schedule_e_net: Money
    expected_carryforward: Money
    reported_carryforward: Money | None
    allowed_loss: Money = Decimal("0.00")
    fully_allowed: bool = False
    status: Literal["ok", "mismatch", "carried", "unreported"] = "unreported"
    drift: Money | None = None
    carried_from_year: int | None = None
    expected_carry_in: Money = Decimal("0.00")


@dataclass(frozen=True)
class ReconciliationSummary:
    """The portfolio-level Reconciliation_Series for a user (Req 2, 6, 7).

    Carries one :class:`ReconciledYear` per Data_Year (ascending, empty when the
    user has no Data_Years), the user's Opening_Balance (default ``0.00``), and a
    flag indicating whether there is anything to reconcile.

    Attributes:
        years: The reconciled years ascending by ``tax_year`` (empty when the
            user has no Data_Years).
        opening_balance: The user's Opening_Balance carried into the earliest
            reconciled year, a non-negative magnitude defaulting to ``0.00``
            (Req 7).
        has_data: ``False`` when the user has no Data_Years and no Opening_Balance
            set, so the page shows the Empty_State rather than a zero-row table
            (Req 6).
        next_year: The latest reconciled year plus one, or ``None`` when the
            series is empty. Defaults to ``None``.
        next_year_expected_carry_in: The balance expected to carry into
            ``next_year``, i.e. the figure the next return's "Prior years
            unallowed losses" line should show: the latest year's
            ``expected_carryforward``, or the Opening_Balance when the series is
            empty. Defaults to the two-decimal zero.
        status_tolerance: The :data:`STATUS_TOLERANCE` used for the ``ok`` and
            ``carried`` comparisons, so the page can explain it. Always set,
            including when the series is empty. Defaults to
            :data:`STATUS_TOLERANCE`.
    """

    years: tuple[ReconciledYear, ...]
    opening_balance: Money
    has_data: bool
    next_year: int | None = None
    next_year_expected_carry_in: Money = Decimal("0.00")
    status_tolerance: Money = STATUS_TOLERANCE


class CarryforwardService:
    """Portfolio-level passive-loss carryforward reconciliation, user-scoped.

    Derives the Expected_Carryforward series from the per-property Schedule E
    nets, merges the user-entered Reported_Carryforward entries, and classifies
    each year. Reads and writes are confined to the authenticated user's
    partition (Req 1.3, 3.5, 7.5).

    Args:
        repo: The single-table DynamoDB repository, used for the per-year
            ``PLCF#<year>`` reported entries and the ``PLCF_OPENING`` singleton.
        user: The authenticated :class:`UserContext` or a raw user id string;
            every operation is scoped to this user.
        reports: The reporting service, used to derive each property's Schedule
            E net per year via :meth:`ReportingService.report_for`, so the
            reconciliation reconciles with the reports and dashboard (Req 1.1,
            1.2).
        properties: The property service, used to list the user's properties
            (the Data_Year source and the set of nets to sum per year).
        transactions: The transaction service, used by the Data_Year derivation
            to collect each property's transaction tax years (the
            income/expense half of a Data_Year). Added so the carryforward
            reconciliation derives the SAME Data_Years as the dashboard via the
            shared :func:`~logstead.services.dashboard.derive_data_years` helper;
            the carryforward route (task 4.1) wires it.
        depreciation: The depreciation service, used by the Data_Year derivation
            to collect each property's depreciation-schedule years (the Line 18
            half of a Data_Year). Added for the same shared-derivation reason;
            the carryforward route (task 4.1) wires it.
        loans: Optional loan service, passed through to the shared Data_Year
            derivation so years with an included loan's rollup join the
            series. ``None`` leaves behavior unchanged. Line 12 loan interest
            itself reaches the nets via ``reports`` (``report_for``).
    """

    def __init__(
        self,
        repo: "DynamoRepository",
        user: UserContext | str,
        reports: "ReportingService",
        properties: "PropertyService",
        transactions: "TransactionService | None" = None,
        depreciation: "DepreciationService | None" = None,
        loans: "LoanService | None" = None,
    ) -> None:
        self._repo = repo
        self._user_id = (
            user_id_of(user) if isinstance(user, UserContext) else user
        )
        self._reports = reports
        self._properties = properties
        self._transactions = transactions
        self._depreciation = depreciation
        self._loans = loans

    # --- Data_Year derivation (Req 1, 2) ------------------------------------

    def _derive_data_years(self, properties: list) -> list[int]:
        """The user's capped Data_Years for the given properties (Req 1.1, 2.1).

        Delegates to the shared
        :func:`~logstead.services.dashboard.derive_data_years` helper — the
        exact derivation the dashboard uses — so the reconciliation reconciles
        with the dashboard/report years to the cent: the ascending,
        de-duplicated, gap-preserving union of each property's transaction tax
        years and depreciation-schedule years, capped at the latest completed
        tax year (:func:`~logstead.services.dashboard.latest_tax_year`).

        Requires the injected ``transactions`` and ``depreciation``
        collaborators (wired by the carryforward route). ``transactions`` may be
        ``None``, in which case only the depreciation half contributes, matching
        the shared helper's contract.

        Args:
            properties: The user's properties (already listed by the caller, so
                a repeat ``PropertyService.list()`` is avoided).

        Returns:
            The ascending, de-duplicated list of capped Data_Years.
        """
        if self._depreciation is None:
            raise RuntimeError(
                "CarryforwardService requires a DepreciationService to derive "
                "Data_Years; wire it via the constructor (the carryforward "
                "route provides it)."
            )
        return derive_data_years(
            properties, self._transactions, self._depreciation, self._loans
        )

    # --- Schedule_E_Net derivation (Req 1, 5) -------------------------------

    def _schedule_e_net_for(self, tax_year: int, properties: list) -> Money:
        """The portfolio Schedule_E_Net for a Tax_Year (Req 1.1, 1.2, 5.2).

        The exact-cent sum across the user's ``properties`` of
        :meth:`ReportingService.report_for`'s ``value.totals.net`` for the year.
        A non-ok report for a user-owned id contributes ``0.00`` and never
        raises (mirrors the dashboard skip). Factored out of :meth:`reconcile`
        so the running-balance loop and the allowed-data validation derive the
        same net to the cent and stay user-scoped.

        Args:
            tax_year: The four-digit Data_Year to derive the net for.
            properties: The user's properties (already listed by the caller, so
                a repeat ``PropertyService.list()`` is avoided).

        Returns:
            The two-decimal :class:`Money` net; negative denotes a net loss.
        """
        net = Decimal("0.00")
        for prop in properties:
            result = self._reports.report_for(prop.id, tax_year)
            if result.is_ok:
                net += result.value.totals.net
        return to_money(net)

    @staticmethod
    def _effective_allowed(
        net: Money, allowed_loss: Money | None, fully_allowed: bool
    ) -> Money:
        """The Effective_Allowed_Amount for a year (Req 3.2, 4.2-4.6).

        Centralizes the precedence rules used by the running-balance loop:

        * ``0.00`` for a Non_Loss_Year (``net >= 0.00``) — no allowed amount
          applies (Req 3.2).
        * the current Loss_Magnitude (``-net``) when ``fully_allowed`` is on,
          taking precedence over any stored ``allowed_loss`` so the toggle
          tracks the loss dynamically (Req 4.2-4.4).
        * otherwise the stored ``allowed_loss`` (``None`` treated as ``0.00``,
          Req 4.5).

        All arithmetic is exact two-decimal :class:`Money`; no float.

        Args:
            net: The year's Schedule_E_Net (negative denotes a loss).
            allowed_loss: The stored Allowed_Loss amount, or ``None`` when none
                is stored (treated as ``0.00``).
            fully_allowed: The Fully_Allowed flag for the year.

        Returns:
            The two-decimal :class:`Money` effective allowed amount.
        """
        if net >= 0:
            return to_money("0.00")
        if fully_allowed:
            return to_money(-net)
        if allowed_loss is None:
            return to_money("0.00")
        return to_money(allowed_loss)

    @staticmethod
    def _apply_year_step(
        prior: Money, net: Money, effective_allowed: Money
    ) -> Money:
        """One year's Suspended_Loss_Balance step (exact Decimal, no float).

        A loss year adds only its unallowed portion
        (``max(-net - effective_allowed, 0.00)``) to ``prior``; a non-loss year
        absorbs the gain, floored at ``0.00``. Shared so the expected balance
        and any chain value use the identical step.

        Args:
            prior: The balance entering the year (non-negative).
            net: The year's Schedule_E_Net (negative denotes a loss).
            effective_allowed: The Effective_Allowed_Amount for the year.

        Returns:
            The balance after the year, as two-decimal :class:`Money`.
        """
        if net < 0:
            suspended = max((-net) - effective_allowed, Decimal("0.00"))
            return prior + suspended
        return max(prior - net, Decimal("0.00"))

    def reconcile(self) -> ReconciliationSummary:
        """Derive the full Reconciliation_Series for the user (Req 1, 2, 4, 6).

        Derives the Schedule_E_Net for every Data_Year, rolls the running
        balance forward from the Opening_Balance (each year's ``expected_carry_in``
        is the balance before its step; ``expected_carryforward`` is the carry-out
        after it), merges the stored per-year entries (the reported carry-in, the
        Form 8582 "Prior years unallowed losses" line), and classifies each year
        by comparing the reported carry-in with ``expected_carry_in``. The
        summary also exposes ``next_year`` and ``next_year_expected_carry_in``. The ``years``
        tuple is empty when the user has no Data_Years. Never applies the IRC
        §469 limitation (Req 2.7).

        The reconciliation is fully re-derived on every read: the user's
        properties are listed once, the Opening_Balance and every stored
        Reported_Carryforward entry are read up front (one ``get_item`` + one
        ``query``), the Data_Years are derived via the shared dashboard helper,
        and each year's Schedule_E_Net is the exact-cent sum of
        :meth:`ReportingService.report_for` across the properties. The running
        Suspended_Loss_Balance follows the design's running-balance algorithm
        exactly (a loss adds its magnitude; a gain is absorbed, floored at
        ``0.00``) — it depends only on the nets and the Opening_Balance, so the
        §469 limitation is never applied.
        """
        # List the user's properties once (the Data_Year source and the set of
        # per-year nets to sum).
        properties = self._properties.list()

        # Read the Opening_Balance up front (default 0.00 when unset).
        opening_item = self._repo.get_item(
            keys.user_pk(self._user_id), keys.plcf_opening_sk()
        )
        if opening_item is not None and "amount" in opening_item:
            opening = to_money(opening_item["amount"])
        else:
            opening = to_money("0.00")

        # Read every stored per-year entry up front. The PLCF_OPENING singleton
        # is NOT matched by the PLCF# prefix, but skip any item lacking taxYear
        # defensively. An item may now carry any subset of amount / allowedLoss
        # / fullyAllowed, so each map is populated independently (an item may
        # exist with allowedLoss/fullyAllowed but NO amount). Pass
        # money_attrs={"amount", "allowedLoss"} so allowedLoss round-trips as a
        # two-decimal string; fullyAllowed stays a BOOL.
        reported: dict[int, Money] = {}
        allowed_loss: dict[int, Money] = {}
        fully_allowed: dict[int, bool] = {}
        for item in self._repo.query(
            keys.user_pk(self._user_id),
            sk_begins_with=keys.plcf_list_prefix(),
            money_attrs={"amount", "allowedLoss"},
        ):
            if "taxYear" not in item:
                continue
            year = int(item["taxYear"])
            if "amount" in item:
                reported[year] = to_money(item["amount"])
            if "allowedLoss" in item:
                allowed_loss[year] = to_money(item["allowedLoss"])
            fully_allowed[year] = bool(item.get("fullyAllowed"))

        # Derive the Data_Years (ascending, capped) via the shared helper.
        years = self._derive_data_years(properties)

        # Roll the running balance across the Data_Years. All arithmetic is
        # exact Decimal; the balance is a non-negative magnitude.
        balance = opening
        prev_reported: Money | None = None
        prev_net: Money | None = None
        prev_allowed: Money | None = None
        last_mismatch_year: int | None = None
        reconciled: list[ReconciledYear] = []
        for index, year in enumerate(years):
            # Schedule_E_Net for the year: exact-cent sum across properties via
            # the shared helper. A non-ok report for a user-owned id contributes
            # 0.00 and never raises (mirrors the dashboard skip).
            net = self._schedule_e_net_for(year, properties)

            # Running Suspended_Loss_Balance: a loss adds only its UNALLOWED
            # portion (Loss_Magnitude minus the Effective_Allowed_Amount, floored
            # at 0.00); a gain is absorbed, floored at 0.00. Never applies the
            # §469 limitation. With no allowed data the effective allowed is
            # 0.00, so a loss adds its full magnitude — byte-for-byte today's
            # series.
            effective_allowed = self._effective_allowed(
                net, allowed_loss.get(year), fully_allowed.get(year, False)
            )
            expected_in = to_money(balance)
            expected_out = to_money(
                self._apply_year_step(expected_in, net, effective_allowed)
            )
            balance = expected_out

            # Status, in order: unreported when no entry; ok when the reported
            # carry-in (Form 8582 "Prior years unallowed losses") is within
            # STATUS_TOLERANCE of the expected carry-in; carried when it is
            # within tolerance of the chain value (the PREVIOUS year's step
            # applied to the previous year's REPORTED carry-in, i.e. a faithful
            # carry-through); else mismatch. Status never reads ``drift``,
            # which stays the exact cent difference.
            # The chain rule needs a prior reconciled year with a reported
            # value, so the first year and any year after an unreported year
            # use the fallback rules only.
            reported_value = reported.get(year)
            drift: Money | None = (
                None
                if reported_value is None
                else to_money(reported_value - expected_in)
            )
            chain_in: Money | None = None
            if (
                index > 0
                and prev_reported is not None
                and prev_net is not None
                and prev_allowed is not None
            ):
                chain_in = to_money(
                    self._apply_year_step(prev_reported, prev_net, prev_allowed)
                )

            carried_from: int | None = None
            status: Literal["ok", "mismatch", "carried", "unreported"]
            if reported_value is None:
                status = "unreported"
            elif _within_tolerance(reported_value, expected_in):
                status = "ok"
            elif chain_in is not None and _within_tolerance(
                reported_value, chain_in
            ):
                status = "carried"
                carried_from = last_mismatch_year
            else:
                status = "mismatch"
                last_mismatch_year = year
            prev_reported = reported_value
            prev_net = net
            prev_allowed = effective_allowed

            reconciled.append(
                ReconciledYear(
                    tax_year=year,
                    schedule_e_net=net,
                    expected_carryforward=expected_out,
                    reported_carryforward=reported_value,
                    allowed_loss=allowed_loss.get(year, to_money("0.00")),
                    fully_allowed=fully_allowed.get(year, False),
                    status=status,
                    drift=drift,
                    carried_from_year=carried_from,
                    expected_carry_in=expected_in,
                )
            )

        return ReconciliationSummary(
            years=tuple(reconciled),
            opening_balance=opening,
            has_data=(bool(years) or opening != Decimal("0.00")),
            next_year=(years[-1] + 1) if years else None,
            next_year_expected_carry_in=to_money(balance),
            status_tolerance=to_money(STATUS_TOLERANCE),
        )

    @staticmethod
    def _validate_amount(amount: str) -> Result[Money]:
        """Validate a non-negative two-decimal money magnitude (Req 3.2, 7.3).

        Normalizes ``amount`` through :func:`~logstead.util.money.to_money`.
        Returns a ``validation`` failure identifying the ``amount`` field when
        the value is not a parseable money string or is negative; otherwise a
        success carrying the normalized two-decimal :class:`Money`. Callers
        persist nothing on a failure.
        """
        try:
            money = to_money(amount)
        except (ValueError, TypeError):
            return Result.failure(
                "validation",
                "Amount must be a valid non-negative money value.",
                field="amount",
            )
        if money < 0:
            return Result.failure(
                "validation",
                "Amount must be non-negative.",
                field="amount",
            )
        return Result.success(money)

    # --- Per-year item read-modify-write (Req 1, 2, 4) ----------------------

    def _merge_year_item(
        self,
        tax_year: int,
        *,
        amount: object = _UNSET,
        allowed_loss: object = _UNSET,
        fully_allowed: object = _UNSET,
    ) -> None:
        """Read-modify-write one attribute of the per-year item (Req 2.2-2.6).

        The ``PLCF#<year>`` item now carries up to three independent optional
        value attributes — ``amount`` (Reported_Carryforward), ``allowedLoss``
        (Allowed_Loss amount), and ``fullyAllowed`` (the Fully_Allowed flag).
        The repository has no partial-update primitive, so every per-year setter
        and clear reads the current item, merges the one attribute it owns, and
        writes the full merged item back — preserving the siblings it does not
        touch (Req 2.3, 2.4).

        Each keyword distinguishes three cases via the module-level ``_UNSET``
        sentinel:

        * left ``_UNSET`` → leave that attribute exactly as the stored item has
          it (preserve a sibling);
        * a value → set/replace that attribute;
        * ``None`` → clear (drop) that attribute.

        After merging, if the item would carry none of ``amount`` /
        ``allowedLoss`` / ``fullyAllowed``, the item is **deleted** rather than
        left as a bare ``{taxYear}`` tombstone (Req 2.5). Otherwise the merged
        item is written with ``taxYear`` set and ``money_attrs={"amount",
        "allowedLoss"}`` so both money fields round-trip as two-decimal strings;
        ``fullyAllowed`` is included only when ``True`` (sparse — ``False`` is
        never stored, Req 4.6). All operations are confined to the user's
        partition (Req 2.6, 9.6).

        Args:
            tax_year: The four-digit Tax_Year whose per-year item to merge.
            amount: ``_UNSET`` to preserve, a money string / :class:`Money` to
                set, or ``None`` to clear the Reported_Carryforward.
            allowed_loss: ``_UNSET`` to preserve, a money string / :class:`Money`
                to set, or ``None`` to clear the Allowed_Loss amount.
            fully_allowed: ``_UNSET`` to preserve, ``True`` to set, or ``None``
                (or ``False``) to clear the Fully_Allowed flag.
        """
        pk = keys.user_pk(self._user_id)
        sk = keys.plcf_year_sk(tax_year)

        current = self._repo.get_item(
            pk, sk, money_attrs={"amount", "allowedLoss"}
        )
        current = current or {}

        # Start from the stored attributes, then apply each non-_UNSET kwarg.
        amount_val: object = current.get("amount")
        allowed_val: object = current.get("allowedLoss")
        fully_val = bool(current.get("fullyAllowed"))

        if amount is not _UNSET:
            amount_val = amount
        if allowed_loss is not _UNSET:
            allowed_val = allowed_loss
        if fully_allowed is not _UNSET:
            fully_val = bool(fully_allowed)

        # Nothing left to carry → delete rather than leave a bare tombstone.
        if amount_val is None and allowed_val is None and not fully_val:
            self._repo.delete_item(pk, sk)
            return

        item: dict[str, object] = {
            "PK": pk,
            "SK": sk,
            "taxYear": tax_year,
        }
        if amount_val is not None:
            item["amount"] = money_to_str(to_money(amount_val))
        if allowed_val is not None:
            item["allowedLoss"] = money_to_str(to_money(allowed_val))
        # Store fullyAllowed only when True; omitted (sparse) otherwise so "off"
        # and "never set" are indistinguishable (Req 4.6).
        if fully_val:
            item["fullyAllowed"] = True

        self._repo.put_item(item, money_attrs={"amount", "allowedLoss"})

    def set_reported(self, tax_year: int, amount: str) -> Result[None]:
        """Persist the Reported_Carryforward for a Tax_Year (Req 3.1-3.3).

        Validates a non-negative two-decimal money amount and merges it onto the
        per-year item, replacing any existing reported value while preserving the
        year's ``allowedLoss``/``fullyAllowed`` siblings (read-modify-write, Req
        2.3). A negative or non-two-decimal amount is rejected with a
        ``validation`` failure identifying ``amount`` and nothing is persisted.
        """
        validated = self._validate_amount(amount)
        if not validated.is_ok:
            return Result.failure(
                validated.error.kind,
                validated.error.message,
                field=validated.error.field,
            )

        self._merge_year_item(
            tax_year, amount=money_to_str(validated.value)
        )
        return Result.success(None)

    def clear_reported(self, tax_year: int) -> Result[None]:
        """Remove the stored Reported_Carryforward for a Tax_Year (Req 3.4).

        Drops only ``amount`` and preserves the year's ``allowedLoss`` /
        ``fullyAllowed`` siblings; deletes the per-year item when nothing else
        remains (Req 2.4, 2.5). Idempotent: succeeds whether or not an entry
        exists, and the year reverts to the ``unreported`` status.
        """
        self._merge_year_item(tax_year, amount=None)
        return Result.success(None)

    def set_allowed_loss(self, tax_year: int, amount: str) -> Result[None]:
        """Persist the Allowed_Loss amount for a Tax_Year (Req 1.1-1.3, 2.2-2.3).

        Validates the submitted amount via :meth:`_validate_allowed`, then merges
        the validated ``allowedLoss`` onto the per-year item, preserving the
        year's ``amount``/``fullyAllowed`` siblings (read-modify-write). A
        validation failure persists nothing and returns the failure.
        """
        validated = self._validate_allowed(tax_year, amount)
        if not validated.is_ok:
            return Result.failure(
                validated.error.kind,
                validated.error.message,
                field=validated.error.field,
            )

        self._merge_year_item(
            tax_year, allowed_loss=money_to_str(validated.value)
        )
        return Result.success(None)

    def clear_allowed_loss(self, tax_year: int) -> Result[None]:
        """Remove the stored Allowed_Loss amount for a Tax_Year (Req 1.4, 2.4).

        Drops only ``allowedLoss`` and preserves the year's ``amount`` /
        ``fullyAllowed`` siblings; deletes the per-year item when nothing else
        remains (Req 2.5). Idempotent.
        """
        self._merge_year_item(tax_year, allowed_loss=None)
        return Result.success(None)

    def set_fully_allowed(self, tax_year: int, on: bool) -> Result[None]:
        """Set or clear the Fully_Allowed flag for a Tax_Year (Req 4.1, 4.5, 4.6, 5.4).

        Turning on first derives the year's Schedule_E_Net (listing the user's
        properties exactly as :meth:`reconcile` does, kept user-scoped) and
        rejects a Non_Loss_Year (``net >= 0``) with a ``validation`` failure
        identifying ``field="fullyAllowed"``, persisting nothing (Req 5.4). On a
        Loss_Year it merges ``fullyAllowed=True`` onto the per-year item without
        snapshotting the loss into ``allowedLoss`` (Req 4.1), preserving the
        year's ``amount``/``allowedLoss`` siblings. Turning off drops the
        ``fullyAllowed`` attribute (sparse — ``False`` is never stored, Req 4.6)
        with no validation (turning off is always allowed) and deletes the item
        when nothing else remains (Req 2.5). All operations are confined to the
        user's partition (Req 4.6, 9.6).
        """
        if on:
            properties = self._properties.list()
            net = self._schedule_e_net_for(tax_year, properties)
            if net >= 0:
                return Result.failure(
                    "validation",
                    "A year with no rental loss cannot be marked fully "
                    "allowed.",
                    field="fullyAllowed",
                )
            self._merge_year_item(tax_year, fully_allowed=True)
        else:
            self._merge_year_item(tax_year, fully_allowed=None)
        return Result.success(None)

    def _validate_allowed(self, tax_year: int, amount: str) -> Result[Money]:
        """Validate a submitted Allowed_Loss amount (Req 5.1-5.6).

        The full net-based validation for the allowed-loss amount. Follows the
        design's five-step rule:

        1. Normalize ``amount`` through the shared :meth:`_validate_amount`
           shape; reject a negative or non-two-decimal value with a
           ``validation`` failure identifying ``field="allowedLoss"`` (the field
           name is re-mapped from ``amount`` so the error points at the allowed
           control, Req 5.1, 5.6).
        2. Derive the year's Schedule_E_Net via :meth:`_schedule_e_net_for`,
           listing the user's properties exactly as :meth:`reconcile` does so
           validation and reconciliation agree to the cent and stay user-scoped
           (Req 5.2).
        3. If the year is a Non_Loss_Year (``net >= 0``) and the validated
           amount is ``> 0.00``, reject with ``field="allowedLoss"`` (Req 5.4).
           An amount of exactly ``0.00`` on a Non_Loss_Year is harmless (it
           stores zero allowed, equivalent to none) and is accepted to keep
           clears / no-ops simple.
        4. Compute ``loss_magnitude = -net`` (meaningful only when ``net < 0``);
           if the amount exceeds it, reject with ``field="allowedLoss"`` (Req
           5.3).
        5. Otherwise succeed carrying the normalized :class:`Money`
           (``0.00 <= amount <= loss_magnitude`` on a Loss_Year, Req 5.5).

        Every rejection persists nothing and uses the existing
        ``Result.failure("validation", message, field="allowedLoss")`` pattern
        (Req 5.6).
        """
        validated = self._validate_amount(amount)
        if not validated.is_ok:
            return Result.failure(
                "validation",
                validated.error.message,
                field="allowedLoss",
            )
        money = validated.value

        properties = self._properties.list()
        net = self._schedule_e_net_for(tax_year, properties)

        if net >= 0:
            if money > 0:
                return Result.failure(
                    "validation",
                    "Allowed loss cannot be recorded for a year with no "
                    "rental loss.",
                    field="allowedLoss",
                )
            return Result.success(money)

        loss_magnitude = -net
        if money > loss_magnitude:
            return Result.failure(
                "validation",
                "Allowed loss cannot exceed the year's loss of "
                f"{money_to_str(loss_magnitude)}.",
                field="allowedLoss",
            )
        return Result.success(money)

    def set_opening_balance(self, amount: str) -> Result[None]:
        """Persist the single Opening_Balance for the user (Req 7.1-7.3).

        Validates a non-negative two-decimal money amount and persists the
        single per-user Opening_Balance item. A negative or non-two-decimal
        amount is rejected with a ``validation`` failure and nothing is
        persisted.
        """
        validated = self._validate_amount(amount)
        if not validated.is_ok:
            return Result.failure(
                validated.error.kind,
                validated.error.message,
                field=validated.error.field,
            )

        self._repo.put_item(
            {
                "PK": keys.user_pk(self._user_id),
                "SK": keys.plcf_opening_sk(),
                "amount": money_to_str(validated.value),
            }
        )
        return Result.success(None)
