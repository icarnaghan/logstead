# Design Document

## Overview

This feature adds a portfolio-level **passive loss carryforward reconciliation** to Logstead. It derives each tax year's Schedule E net from existing data, rolls a running suspended-loss balance forward across the user's Data_Years (the Expected_Carryforward), lets the user record what they actually reported each year (the Reported_Carryforward), and flags the years where the two diverge — the signature of a carryforward the user forgot to roll onto the next return.

It is a **reconciliation aid, not a tax engine**. The Expected_Carryforward is the economic carryforward from Schedule E net alone and deliberately does not apply the IRC §469 limitation (Form 8582, the $25,000 allowance, MAGI phase-out, real-estate-professional status), because the app collects none of the required inputs. A persistent disclaimer states this on the page.

The feature is small and additive:

- **Backend**: a new `CarryforwardService` that reuses the existing `ReportingService.report_for` per-(property, year) derivation looped across the user's Data_Years, plus two tiny new persisted items under the user partition (per-year reported entries and a single opening balance). Three read/write routes.
- **Frontend**: a new `Carryforward_Page` and a `Carryforward_API` transport wrapper, reusing the app's existing money formatting, table, and form conventions.

### Design decisions and rationale

- **Portfolio-level, one running balance.** §469 aggregates rental real estate, and the user chose a single portfolio balance. This keeps one number to enter and reconcile per year and avoids per-property carryforward bookkeeping (explicitly out of scope).
- **Expected is derived, Reported is stored.** The Expected_Carryforward is recomputed from Schedule E nets on every read (no cached aggregate — consistent with the rest of the app, which is fully re-derivable). Only the user-entered Reported_Carryforward and Opening_Balance are durable. This is the one deliberate piece of cross-year stored state and is kept minimal.
- **Gains absorb prior losses, floored at zero.** A profitable year reduces the suspended balance (down to 0.00), mirroring how passive income frees suspended losses, so the Expected line stays realistic rather than a naive cumulative sum of loss years.
- **No §469 math.** The derivation stops at the economic carryforward. Applying the limitation would require MAGI, participation status, non-rental passive income, and disposition events — none collected. Encoding a half-right §469 result would be worse than an honest economic one plus a clear disclaimer.
- **Sign convention.** Schedule_E_Net keeps the app-wide convention (negative = loss). The Suspended_Loss_Balance is carried as a **non-negative magnitude** (0.00 = no suspended loss); a loss year adds `abs(net)`, a gain year subtracts `net` floored at zero. Keeping the balance non-negative avoids sign confusion in the UI and matches how a carryforward is reported (a positive amount of loss carried).
- **Reported entered manually.** The reliable comparison point. Inferring it from uploaded Schedule E PDFs (reading the line 21/22 totals the extractor can see) is deferred — it would lean on OCR of totals rows the parser intentionally does not treat as data.

### Research notes (grounded in the existing codebase)

- `ReportingService.report_for(property_id, tax_year) -> Result[ScheduleEReport]` already yields `report.value.totals.net` as a two-decimal `Decimal` per property per year, user-scoped via the injected `PropertyService`. The dashboard trends (`DashboardService.trends_summary`) already loop this across `PropertyService.list()` and the derived Data_Years; the Data_Year derivation (`_derive_data_years`) is the same union of transaction years and depreciation-schedule years, capped at the latest completed tax year.
- Per-user single-value items follow the `USER#<id> / PROFILE` and per-property `PROPERTY#<id> / NOTE` precedent: a fixed SK for a singleton, a prefixed SK per sub-key. Per-year items follow `USAGE#<year>` (`usage_sk`). The new items reuse these patterns under the user partition.
- Money is `util.money` (`to_money`, `money_to_str`); the router serializes `Decimal` as two-decimal strings via `_to_jsonable`, and `Result` errors map to HTTP (`validation`→400 with `field`, `not_found`→404) via `_result_response`. The frontend `apiClient` has `get`/`post`/`put`/`delete` and money is strings end-to-end.

## Architecture

```
Carryforward_Page (frontend/src/pages/CarryforwardPage.tsx)
  │  fetch on mount + on save/clear
  ▼
Carryforward_API (frontend/src/api/carryforward.ts)
  │  GET  /carryforward                      → Reconciliation_Series
  │  PUT  /carryforward/years/{taxYear}       → set Reported_Carryforward
  │  DELETE /carryforward/years/{taxYear}     → clear Reported_Carryforward
  │  PUT  /carryforward/opening-balance       → set Opening_Balance
  ▼
router/handler.py  (new handlers, user-scoped, Result→HTTP)
  ▼
CarryforwardService (backend/src/logstead/services/carryforward.py)
  │  reconcile():  derive nets → roll Expected → merge Reported → status
  │  set_reported(year, amount) / clear_reported(year) / set_opening(amount)
  ├── ReportingService.report_for(pid, year)   (derived nets, reused)
  ├── PropertyService.list()                   (user's properties, Data_Year source)
  └── DynamoRepository                         (PLCF# per-year items + PLCF_OPENING)
```

### Data_Year derivation (Req 1, 2)

The reconciled years are the user's Data_Years, derived exactly as the dashboard does today: the union across the user's properties of transaction tax years and depreciation-schedule tax years, ascending, de-duplicated, capped at the latest completed tax year. To avoid duplicating logic, `CarryforwardService` depends on the existing derivation. The reconciled span is the Data_Years; when an Opening_Balance is set but there are no Data_Years, the series is empty but the opening balance is still surfaced (see Empty_State, Req 6/7).

### Running-balance algorithm (Req 2, 4)

```
balance = opening_balance            # non-negative magnitude, default 0.00
for year in sorted(data_years):      # ascending
    net = schedule_e_net(year)       # Decimal, negative = loss
    if net < 0:
        balance = balance + (-net)   # a loss adds its magnitude
    else:
        balance = max(balance - net, 0)   # a gain absorbs, floored at 0
    expected[year] = balance         # Expected_Carryforward for the year
    status[year] = (
        "unreported" if reported.get(year) is None
        else "ok" if reported[year] == balance
        else "mismatch"
    )
```

All arithmetic is exact `Decimal` quantized to two places; the balance is never negative.

## Components and Interfaces

### Backend

**`CarryforwardService`** (`backend/src/logstead/services/carryforward.py`), user-scoped, injected collaborators:

```python
class CarryforwardService:
    def __init__(
        self,
        repo: DynamoRepository,
        user: UserContext | str,
        reports: ReportingService,
        properties: PropertyService,
    ) -> None: ...

    def reconcile(self) -> ReconciliationSummary:
        """Derive nets for every Data_Year, roll the Expected_Carryforward
        forward from the Opening_Balance, merge stored Reported_Carryforward
        entries, and classify each year. Empty years tuple when the user has no
        Data_Years. Never applies the §469 limitation (Req 1, 2, 4)."""

    def set_reported(self, tax_year: int, amount: str) -> Result[None]:
        """Validate a non-negative two-decimal amount and persist the
        Reported_Carryforward for the year (replace if present). validation
        failure (field="amount") on a bad amount (Req 3.1-3.3)."""

    def clear_reported(self, tax_year: int) -> Result[None]:
        """Remove the stored Reported_Carryforward for the year; idempotent
        (Req 3.4)."""

    def set_opening_balance(self, amount: str) -> Result[None]:
        """Validate a non-negative two-decimal amount and persist the single
        Opening_Balance for the user (Req 7.1-7.3)."""
```

Derivation detail: `reconcile()` lists the user's properties once, derives the Data_Years (reusing the shared derivation), and for each year sums `reports.report_for(pid, year).value.totals.net` across properties to get the Schedule_E_Net. A non-ok `report_for` for a user-owned id is treated as `0.00` (mirrors the dashboard skip), never raising. Reported entries and the opening balance are read once up front (a single `query` on the `PLCF#` prefix plus a `get_item` for the opening) so `reconcile()` does no per-year extra reads beyond the report derivations.

**Routes** (`router/handler.py`), all auth-gated, user-scoped, no `taxYear` on the collection read:

| Method & path | Handler | Result → HTTP |
|---|---|---|
| `GET /carryforward` | `_carryforward_reconcile` | 200 `ReconciliationSummary` |
| `PUT /carryforward/years/{taxYear}` | `_set_carryforward_reported` | 200 / 400 (bad amount or non-int year) |
| `DELETE /carryforward/years/{taxYear}` | `_clear_carryforward_reported` | 200 |
| `PUT /carryforward/opening-balance` | `_set_carryforward_opening` | 200 / 400 |

The `{taxYear}` segment is parsed with the existing `_int_param` guard (non-integer → 400). The service is built per request by a `_carryforward_service_or_503(wiring, user)` constructor mirroring `_dashboard_service_or_503` (it needs the repo + a reporting service; an unconfigured dependency surfaces the standard 503). `_to_jsonable` serializes all money as two-decimal strings.

### Frontend

**`Carryforward_API`** (`frontend/src/api/carryforward.ts`): transport-only wrapper over the shared `apiClient`, mirroring `api/dashboard.ts`. Wire types use the backend snake_case field names; money fields are typed as `string`.

```ts
export interface ReconciledYear {
  tax_year: number;
  schedule_e_net: string;         // Money_String, negative = loss
  expected_carryforward: string;  // Money_String, non-negative
  reported_carryforward: string | null;  // null = unreported
  status: "ok" | "mismatch" | "unreported";
}
export interface ReconciliationSummary {
  years: readonly ReconciledYear[];
  opening_balance: string;        // Money_String, non-negative
  has_data: boolean;              // false when no Data_Years and no opening balance
}
export class CarryforwardApi {
  getReconciliation(signal?): Promise<ReconciliationSummary>;
  setReported(taxYear: number, amount: string, signal?): Promise<void>;
  clearReported(taxYear: number, signal?): Promise<void>;
  setOpeningBalance(amount: string, signal?): Promise<void>;
}
```

**`Carryforward_Page`** (`frontend/src/pages/CarryforwardPage.tsx`): fetches the reconciliation on mount; renders the `Disclaimer_Notice` persistently (a short plain-language line plus a collapsed-by-default “What is this?” explanation covering suspended carryforwards and why the §469 limitation is not computed, per Req 8.3), the opening-balance control, and the reconciliation table (one row per year ascending with net, expected, reported, and a textual status). Each row has an inline edit control for its Reported_Carryforward; save/clear calls the API then refreshes the series (no full reload). `mismatch` rows carry a distinct, text-labelled highlight (not color alone). The Empty_State shows when `has_data` is false. Money renders via the app's existing `formatMoney` with its loss convention. Added to the app's route table/nav like the other pages.

## Data Models

Two tiny durable item types, both under the user partition, plus a transport dataclass. No change to any existing model.

**Reported_Carryforward item** — one per (user, Tax_Year) the user has entered:

```
PK = USER#<userId>
SK = PLCF#<taxYear>         # new PLCF_PREFIX = "PLCF#", via plcf_year_sk(year)
amount = "<two-decimal string>"   # non-negative
taxYear = <int>
```

**Opening_Balance item** — a single per-user singleton:

```
PK = USER#<userId>
SK = PLCF_OPENING          # new PLCF_OPENING_SK constant
amount = "<two-decimal string>"   # non-negative
```

**Backend transport dataclasses** (`services/carryforward.py`), money as `util.money.Money` (two-decimal `Decimal`), serialized to strings by the router:

```python
@dataclass(frozen=True)
class ReconciledYear:
    tax_year: int
    schedule_e_net: Money
    expected_carryforward: Money
    reported_carryforward: Money | None
    status: Literal["ok", "mismatch", "unreported"]

@dataclass(frozen=True)
class ReconciliationSummary:
    years: tuple[ReconciledYear, ...]
    opening_balance: Money
    has_data: bool
```

New key helpers in `repository/keys.py`: `PLCF_PREFIX = "PLCF#"`, `plcf_year_sk(tax_year)`, `plcf_list_prefix()`, and `PLCF_OPENING_SK = "PLCF_OPENING"` with `plcf_opening_sk()` — following the `USAGE#`/`NOTE`/`PROFILE` conventions.

## Correctness Properties

These are the invariants the implementation must hold, suitable for property-based tests (Hypothesis on the backend). Each maps to acceptance criteria.

### Property 1: Schedule E net reconciles with the reports

For any user, properties, and transactions, each reconciled year's Schedule_E_Net equals the exact-cent sum over the user's properties of `report_for(pid, year).value.totals.net` for that year — the same portfolio net the reports and dashboard produce.

**Validates: Requirements 1.1, 1.2**

### Property 2: Expected is a correct running balance

For any sequence of per-year nets and any Opening_Balance, processing years ascending yields, for each year: `expected = max(prior_balance - net, 0)` when `net >= 0`, and `expected = prior_balance + (-net)` when `net < 0`; and each year's expected is the balance carried into the next year.

**Validates: Requirements 2.1, 2.2, 2.3, 2.4, 2.5**

### Property 3: Expected is never negative

For any inputs, every Expected_Carryforward is `>= 0.00` and is a two-decimal `Decimal`.

**Validates: Requirements 2.4, 2.6**

### Property 4: A profitable run drives the balance to zero and holds

Given a positive Opening_Balance followed by gain years whose cumulative gain meets or exceeds it, the Expected_Carryforward reaches 0.00 and never goes below it, regardless of how large later gains are.

**Validates: Requirements 2.4**

### Property 5: Pure-loss accumulation

Given only loss years (and the opening balance), each year's Expected_Carryforward equals the Opening_Balance plus the cumulative magnitude of losses through that year.

**Validates: Requirements 2.3**

### Property 6: Exact-decimal arithmetic, no float drift

For any inputs, the running balance computed stepwise equals the same balance computed by exact `Decimal` accumulation; no intermediate is a float.

**Validates: Requirements 2.6**

### Property 7: Status classification is total and correct

For every reconciled year exactly one status holds: `unreported` iff no Reported_Carryforward is stored; otherwise `ok` iff `reported == expected` to the cent, else `mismatch`.

**Validates: Requirements 4.1, 4.2, 4.3, 4.4**

### Property 8: Reported round-trips and validates

A persisted Reported_Carryforward reads back equal to the (normalized two-decimal) value written; a negative or non-two-decimal input is rejected with a `validation` error and persists nothing; clearing removes it and the year reverts to `unreported`.

**Validates: Requirements 3.1, 3.2, 3.3, 3.4**

### Property 9: Every figure is a two-decimal money string

In the serialized `GET /carryforward` body, `schedule_e_net`, `expected_carryforward`, every non-null `reported_carryforward`, and `opening_balance` match `^-?\d+\.\d{2}$`; only `tax_year` is an integer and `status` a known literal.

**Validates: Requirements 1.4, 2.6, 3.6**

### Property 10: User scoping — no cross-user leakage

With two users over the same table, each user's reconciliation reflects only their own properties, reported entries, and opening balance; neither can read or modify the other's.

**Validates: Requirements 1.3, 3.5, 7.5**

### Property 11: No properties and no opening balance yields an empty, non-error series

A user with no Data_Years and no Opening_Balance produces `years == ()`, `has_data == false`, and `opening_balance == "0.00"` — never an error.

**Validates: Requirements 6.1, 6.2**

### Property 12: §469 limitation is never applied

For any inputs — including ones where a §469 $25,000 allowance would change a real Form 8582 result — the Expected_Carryforward depends only on the nets and the Opening_Balance (it equals the running-balance algorithm's output), confirming no allowance/phase-out logic influences the figure.

**Validates: Requirements 2.7, 8.3**

## Error Handling

- **Bad amount** (negative, non-numeric, wrong precision) on set-reported or set-opening → `Result.failure("validation", ..., field="amount")` → 400 with the field; nothing persisted (Req 3.3, 7.3).
- **Non-integer `{taxYear}`** path segment → 400 via the existing `_int_param` guard, before the service is called.
- **Clearing an absent reported entry** → success (idempotent delete), year stays `unreported` (Req 3.4).
- **A user-owned property whose `report_for` is not ok** for a year → that property contributes `0.00` to the net for that year; the reconciliation never raises (mirrors the dashboard skip).
- **Unconfigured dependency** (no repo/reporting wiring) → standard 503 via `_carryforward_service_or_503`, consistent with the other services.
- **Unauthenticated request** → 401, like every other protected route.
- The frontend surfaces a save/clear failure inline next to the row's edit control (Req 5.5) and a load failure as the page's error indication, without wiping the disclaimer.

## Testing Strategy

### Property-based tests (Hypothesis, backend)
Cover Properties 1-12 with moto-backed DynamoDB + S3 and the real composed services (mirroring the dashboard trends property tests): generate varied properties, transactions across non-contiguous years, reported entries, and opening balances; assert the running-balance math, non-negativity, status totality, exact-decimal arithmetic, money-string serialization at the route boundary, user scoping, the empty case, and the §469-independence property.

### Unit / example tests
- `CarryforwardService.reconcile` on a hand-built fixture: a loss year, a later gain that partially absorbs, a gain that fully absorbs (floored at zero), a non-contiguous gap year, and an opening balance — asserting the exact Expected_Carryforward and statuses, including the user's real-world "forgot to carry forward" shape (a loss year followed by a next-year reported balance of 0.00 → `mismatch`).
- `set_reported` / `clear_reported` / `set_opening_balance`: persistence, replace, validation rejection, idempotent clear, user scoping.
- Route example tests for the four endpoints: 200 shapes, 400 on bad amount and non-integer year, 401 unauthenticated, and no-shadowing of adjacent routes.
- Frontend: `Carryforward_API` unit tests (correct paths/methods, money typed as strings, no `taxYear` on the collection read); `Carryforward_Page` RTL tests for the table rows, the `mismatch` textual highlight, inline edit → save/clear refresh, the opening-balance control, the persistent disclaimer, and the empty state.

### Design properties → tests mapping
Each Correctness Property above is realized by at least one Hypothesis test; each acceptance criterion is covered by a property test, an example test, or an RTL test as listed.
