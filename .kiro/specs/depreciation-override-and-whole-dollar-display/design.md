# Design Document

## Overview

This feature bundles two user-approved changes to Logstead's depreciation handling, both aimed at making the app reproduce the figures a user actually filed while keeping its internal math exact.

- **Feature A — per-year depreciation override.** The pure schedule engine `compute_schedule_rows(asset)` gains an optional per-year override map carried on the asset. After computing the normal straight-line + mid-month schedule, the engine replaces each overridden year's `amount` with the user's filed value and rolls the resulting delta into the tail year, so the engine's two existing invariants (amounts sum exactly to `cost_basis`; `remaining_basis` is non-increasing to exactly `0.00`) still hold by construction. Overrides that cannot be reconciled are rejected at validation time with a field-identifying `Result` failure. Nothing about storage keys, routes, or the materialization path changes — overrides flow through because `compute_schedule_rows` now reads `asset.depreciation_overrides`.

- **Feature B — whole-dollar display rounding.** A new `formatMoneyWholeDollars` helper in `frontend/src/lib/money.ts` rounds a money string to the nearest whole dollar (IRS convention: cents remainder ≥ 50 rounds the magnitude up, below 50 rounds down), computed in exact integer cents with no floating-point arithmetic. It is swapped in at the tax-oriented display surfaces only. This is a presentation change: nothing stored, computed, or sent over the wire is rounded.

The two features are additive and independent of each other; they share only the money pipeline's "two-decimal strings everywhere on the wire, integer cents in the UI, no float" discipline.

### Design decisions and rationale

- **Overrides live on the asset item as one Map attribute, keyed by tax year, values as two-decimal strings.** Requirement 1.2 forbids extra schedule-row items, sort keys, routes, or tables. A single DynamoDB Map attribute `depreciationOverrides` (`{ "<taxYear>": "<two-decimal string>" }`) keeps overrides co-located with the asset, round-trips through the existing `put_item` / `get_item` path, and is backward compatible (absent attribute == no overrides). Values are **strings**, not DynamoDB Numbers, for the same reason all money is: a `Number` can drift. See "Storing the override map" below for why the map must bypass the repository's `money_attrs` serializer.

- **Delta rolls into the tail year, exactly as the engine already pins the tail.** The engine today pins the final year's cumulative to the exact cost basis so rounding never drifts. The override reconciliation generalizes that: after overriding years, the tail year absorbs whatever delta keeps the per-year sum equal to `cost_basis`. This reuses the engine's existing "tail absorbs the remainder" shape rather than inventing a new reconciliation point.

- **Validation rejects the unsatisfiable cases rather than silently breaking an invariant.** An override is a deliberate reproduction of a known filed value, not a free-form editor. If the overrides can't be reconciled (negative amount, non-schedule year, sum > basis, tail would go negative, tail itself overridden leaving no absorber), the service returns a `validation` failure identifying the offending year and persists nothing. The invariants are preserved by construction for every input the service accepts.

- **Whole-dollar rounding is display-only and lives in the existing money module.** The helper sits beside `formatMoney` and reuses `toCents` (the same integer-cents parser), so the "no float in the money pipeline" guarantee extends to it. Rounding happens at the last formatting step; the string that was rounded is never stored or re-parsed.

- **Scope of rounding is confirmed to tax-oriented surfaces only.** Per the resolved Requirement 11: ReportView and its line tables, the depreciation schedule display, the dashboard depreciation + net figures, and the carryforward table round to whole dollars. Raw transaction amounts (TransactionsPage) and the asset cost-basis echo (AssetList) keep cents. The broader "every `formatMoney` site" option was not chosen.

### Research notes (grounded in the existing codebase)

- **Engine shape.** `compute_schedule_rows(asset)` builds `num_years = ceil(recovery) + 1` rows from the placed-in-service year, prorating the first year by `(12.5 - month)/12`, and pins the final row's cumulative to the exact `cost_basis` (`backend/src/logstead/services/depreciation.py`). `_materialize_schedule` recomputes and rewrites rows on create/update in one `transact_write`; `delete_asset` cascades; `property_depreciation_for_year` sums the GSI2 tax-year partition. The override reconciliation is inserted inside `compute_schedule_rows` (via a helper) so all of these paths pick it up with no change.

- **Money/attr handling.** The repository serializes only the attributes named in `money_attrs` as two-decimal strings (`backend/src/logstead/repository/dynamo_repo.py`), and asset reads/writes narrow that set to `{"costBasis"}` so `recoveryPeriodYears` stays a plain `Decimal` string. A Map attribute is **not** a top-level money attribute; `TypeSerializer`/`TypeDeserializer` round-trips a DynamoDB Map of strings faithfully as long as the inner values are already strings. `asset_to_item` must therefore render the override values to strings itself and `_from_item` must parse them back — the `money_attrs` serializer only touches top-level names and would not recurse into the map anyway.

- **Router serialization.** `_to_jsonable` renders `Decimal` as its exact string and recurses into dicts (coercing keys to strings) and dataclasses (`backend/src/logstead/router/handler.py`). An override map typed as `dict[int, Decimal]` therefore serializes to `{ "2010": "1952.00" }` automatically. `_asset_input` maps request bodies (snake_case or camelCase) to `AssetInput`.

- **Frontend money.** `frontend/src/lib/money.ts` exposes `toCents` (string → exact integer cents, no float), `centsToMoney`, `formatMoney` (empty/null/undefined → `""`, non-numeric → passthrough, else `en-US` USD), `isLoss`, and `sumMoney`. Call sites render through `tabular-nums`. The new formatter reuses `toCents` and the same passthrough contract.

- **Schedule UI.** `ScheduleTable.tsx` renders the per-year rows (tax year, amount, remaining basis) and is hosted by `AssetsPage.tsx`, which already owns asset CRUD, `updateAsset`, and schedule reloads. The override controls and markers live in `ScheduleTable` driven by props the page supplies; the page sends the updated map via `updateAsset` and reloads the schedule.

## Architecture

```
Feature A — override round-trip
───────────────────────────────
AssetsPage (frontend/src/pages/AssetsPage.tsx)
  │ edit/clear a year's override in the schedule UI
  ▼
ScheduleTable (frontend/src/components/assets/ScheduleTable.tsx)
  │ per-year override input + clear + Override_Marker + note
  │ builds the updated override map (Record<string,string>, integer-cents only)
  ▼
assets.ts  updateAsset(propertyId, assetId, { ...fields, depreciation_overrides })
  ▼
PUT /properties/{propertyId}/assets/{assetId}   (router _update_asset → _asset_input)
  ▼
DepreciationService.update_asset
  │ _validate (now validates the override map)  ──► Result.failure("validation", …, field="depreciation_overrides.<year>")
  │ put asset item (depreciationOverrides Map)
  ▼ _materialize_schedule → compute_schedule_rows(asset)
       compute base Computed_Schedule  (unchanged)
       _apply_overrides(base, asset.depreciation_overrides)  ──► Effective_Schedule
  ▼
rows written under ASSET#<id>#SCHED#<year> (base table + GSI2), exactly as today
  ▼
property_depreciation_for_year / schedule_for  read the Effective_Schedule rows


Feature B — whole-dollar display (display boundary only)
────────────────────────────────────────────────────────
ReportView / ScheduleELineTable / OtherItemsList / ScheduleTable
DashboardPage (depreciation tile, net headline, net-by-property) / CarryforwardPage
  │
  ▼ formatMoneyWholeDollars(moneyString)   (frontend/src/lib/money.ts)
      toCents(s) → round to nearest dollar in integer cents → Intl en-US USD, 0 fraction digits
```

### Override-and-reconcile algorithm (Req 2, 3)

The reconciliation is a pure helper `_apply_overrides(base_rows, overrides)` called at the end of `compute_schedule_rows`, after the base `Computed_Schedule` is built exactly as today. All arithmetic is `Decimal` quantized to two places.

```
def _apply_overrides(base_rows, overrides):           # overrides: dict[int, Decimal]
    if not overrides:
        return base_rows                              # Req 5.1: identical to today

    years          = [r.tax_year for r in base_rows]
    tail_year      = years[-1]
    base_amount    = {r.tax_year: r.amount for r in base_rows}

    # amounts after overrides, before tail reconciliation
    eff_amount = dict(base_amount)
    for year, value in overrides.items():
        eff_amount[year] = value                      # Req 2.2

    # delta the tail must absorb so the sum stays == cost_basis
    #   sum(base) == cost_basis already, so:
    #   delta = sum(base amounts of overridden years) - sum(override amounts)
    delta = sum(base_amount[y] for y in overrides) - sum(overrides.values())

    if tail_year not in overrides:
        eff_amount[tail_year] = base_amount[tail_year] + delta   # Req 2.3
    # else: tail is pinned by the user; the validator guarantees the override
    # map already sums to cost_basis so no absorption is needed (see validation).

    # rebuild rows with recomputed remaining_basis (Req 2.4)
    cost_basis = sum(base_amount.values())            # == asset.cost_basis exactly
    rows, cumulative = [], Decimal("0.00")
    for r in base_rows:
        amount    = eff_amount[r.tax_year]
        cumulative += amount
        remaining = cost_basis - cumulative
        rows.append(replace(r, amount=amount, remaining_basis=remaining))
    return rows
```

Why the invariants hold for every accepted input:

- **Invariant_Sum.** The base rows already sum to `cost_basis`. Replacing overridden years changes the sum by exactly `-delta`; adding `delta` back to the tail restores the sum to `cost_basis`. When the tail itself is overridden, the validator only accepts maps whose overrides sum to `cost_basis` with no non-overridden absorber needed (the degenerate single-year / fully-overridden case), so `delta == 0` and the sum is `cost_basis` by the override values alone.
- **Invariant_Monotonic.** `remaining_basis` is recomputed as `cost_basis - cumulative` over the same ascending rows, so it ends at `0.00` whenever the amounts sum to `cost_basis`. It is non-increasing **iff** every effective amount is ≥ 0. The validator rejects the cases that would make an amount negative (negative override; tail delta that would drive the tail below 0), so every accepted schedule is monotone.

Cases the algorithm **cannot** satisfy, each rejected by validation (Req 3) with `Result.failure("validation", msg, field=…)`:

| Case | Why it can't reconcile | Field |
|---|---|---|
| Override amount negative or not two-decimal money | would make a year's amount negative / is not a valid Money_String | `depreciation_overrides.<year>` |
| Override for a year not in the Computed_Schedule | no row to pin; tail absorption can't target a phantom year | `depreciation_overrides.<year>` |
| Sum of overrides > `cost_basis` | tail would have to go negative to keep the sum at `cost_basis` | `depreciation_overrides` |
| Tail-year amount would be negative after absorbing the delta (`base_tail + delta < 0`) | monotonicity would break | `depreciation_overrides` |
| Tail year is itself overridden **and** overrides don't already sum to `cost_basis` | no non-overridden year remains to absorb the delta | `depreciation_overrides.<tailYear>` |

### Validation placement (Req 3)

Validation extends the existing `DepreciationService._validate`, which already returns normalized field values or the first field-identifying failure. A new `_coerce_overrides(raw, placed_in_service_date, recovery_period_years, cost_basis)` helper:

1. Treats `None`/absent as `{}` (Req 5.2) and returns success with an empty map.
2. Parses each value with `to_money`; a parse failure or a value `< 0` → failure on `depreciation_overrides.<year>` (Req 3.1).
3. Derives the schedule's **year span without materializing** — `first_year = year(placed_in_service_date)`, `num_years = ceil(recovery_period_years) + 1`, span = `[first_year, first_year + num_years - 1]` (identical to the engine). Any override year outside the span → failure on `depreciation_overrides.<year>` (Req 3.2).
4. Checks `sum(overrides) <= cost_basis` → else failure on `depreciation_overrides` (Req 3.3).
5. Computes the tail reconciliation the engine will do and checks the resulting tail amount is `>= 0`; when the tail is itself overridden, checks the overrides already sum to `cost_basis`. Else failure on `depreciation_overrides` / `depreciation_overrides.<tailYear>` (Req 3.4, 3.5).

`_coerce_overrides` needs the base per-year amounts for the tail check (step 5); it computes them by calling `compute_schedule_rows` on an override-free copy of the asset, or equivalently reuses the already-computed base rows. `create_asset`, `update_asset`, `_materialize_schedule`, `delete_asset` are otherwise unchanged — overrides flow through because the validated map is stored on the asset and `compute_schedule_rows` reads it.

### Whole-dollar formatter algorithm (Req 8)

```
formatMoneyWholeDollars(amount):
  if amount is null | undefined | ""      -> ""            # Req 8.4, same as formatMoney
  value = Number(amount)
  if not Number.isFinite(value)           -> return amount  # non-numeric passthrough
  cents       = toCents(amount)            # exact integer cents, no float (Req 8.3)
  sign        = cents < 0 ? -1 : 1
  absCents    = Math.abs(cents)
  wholeDollars= Math.floor(absCents / 100)
  remainder   = absCents % 100             # 0..99
  if remainder >= 50: wholeDollars += 1    # Req 8.1 half-up by magnitude; Req 8.2 not ceiling
  roundedDollars = sign * wholeDollars
  return roundedDollars.toLocaleString("en-US",
           { style: "currency", currency: "USD",
             minimumFractionDigits: 0, maximumFractionDigits: 0 })
```

The round is on **integer cents** (`remainder` is an integer 0..99), never on a float derived from `Number(amount)`. Sign is preserved by rounding the magnitude and reapplying the sign (Req 8.5). `maximumFractionDigits: 0` / `minimumFractionDigits: 0` render e.g. `"5090.91"` → `$5,091`, `"5090.10"` → `$5,090`, `"5090.50"` → `$5,091`, `"-125.50"` → `-$126`.

## Components and Interfaces

### Backend

**`models/depreciation.py`** — add the override map to both the asset and its input. Default is an empty dict (Req 1.1, 5.2), so every existing construction site is unaffected.

```python
@dataclass
class AssetInput:
    property_id: str | None
    description: str | None
    cost_basis: Decimal | None
    placed_in_service_date: str | None
    recovery_period_years: Decimal | None = None
    # Req 1.1: optional per-year overrides; tax_year -> two-decimal amount.
    depreciation_overrides: dict[int, Decimal] | None = None

@dataclass
class DepreciableAsset:
    id: str
    property_id: str
    description: str
    cost_basis: Decimal
    placed_in_service_date: str
    recovery_period_years: Decimal = DEFAULT_RECOVERY_PERIOD_YEARS
    # Req 1.1, 5.2: empty == no overrides. Keys are tax years; values money.
    depreciation_overrides: dict[int, Decimal] = field(default_factory=dict)
    created_at: str | None = None
    updated_at: str | None = None
```

**`services/depreciation.py`**

- `compute_schedule_rows(asset)` — unchanged base computation, then `return _apply_overrides(base_rows, asset.depreciation_overrides)`. A no-override asset returns the base rows unchanged (Req 5.1).
- `_apply_overrides(base_rows, overrides) -> list[DepreciationScheduleRow]` — the pure reconciliation above; importable for direct property testing like `compute_schedule_rows`.
- `_coerce_overrides(...) -> Result[dict[int, Decimal]]` — validation (Req 3), wired into `_validate` as a new normalized field `depreciation_overrides`.
- `asset_to_item(asset)` — add `"depreciationOverrides"` rendered as a **Map of two-decimal strings** (see Data Models). Omitted when the map is empty so the stored item shape is unchanged for override-free assets (Req 5.3).
- `_from_item(item)` — parse `item.get("depreciationOverrides", {})` back into `dict[int, Decimal]` with `int` keys and `to_money` values; absent → `{}` (Req 5.2).
- `create_asset` / `update_asset` — carry the validated `depreciation_overrides` onto the constructed `DepreciableAsset`; everything else unchanged. `_materialize_schedule` and `delete_asset` need no change.

**Route** — no new routes (Req 1.2). `_asset_input` additionally maps the override map:

```python
def _asset_input(body, property_id):
    raw = body.get("depreciation_overrides", body.get("depreciationOverrides")) or {}
    overrides = {int(y): _decimal_or_none(v) for y, v in raw.items()}  # strings -> Decimal
    return AssetInput(..., depreciation_overrides=overrides or None)
```

The asset response already serializes via `_to_jsonable`, which renders `depreciation_overrides: dict[int, Decimal]` as `{ "<year>": "<two-decimal string>" }` (Req 1.4). Reads/writes stay scoped to the property passed from the authenticated user's path (Req 1.5) — unchanged from today.

### Frontend

**`api/assets.ts`** — add the override map as an optional field of money **strings** keyed by year, and include it in create/update bodies. Keys are `string` (the JSON object-key form the backend emits and accepts); values are two-decimal money strings, never numbers, preserving the "no float" contract.

```ts
/** Per-year depreciation overrides: tax-year string -> two-decimal money string. */
export type DepreciationOverrides = Record<string, string>;

export interface DepreciableAsset {
  // …existing fields…
  /** Absent/empty == no overrides. */
  depreciation_overrides?: DepreciationOverrides;
}
export interface CreateAssetInput { /* … */ depreciation_overrides?: DepreciationOverrides; }
export interface UpdateAssetInput { /* … */ depreciation_overrides?: DepreciationOverrides; }
```

`Record<string, string>` (not `Record<number, string>`) is chosen because JSON object keys are strings end-to-end and `_to_jsonable` emits string keys; this avoids a lossy `number`-key fiction in the type.

**`components/assets/ScheduleTable.tsx`** — the surface that renders the schedule gains optional override affordances, driven by props so the page owns persistence:

```ts
interface ScheduleTableProps {
  caption: string;
  rows: ScheduleRow[];
  overrides?: DepreciationOverrides;                 // current map for marking
  onOverrideChange?: (taxYear: number, amount: string | null) => void; // null = clear
  overrideErrors?: Record<string, string>;           // year -> inline validation message
  editable?: boolean;                                 // false keeps today's read-only table
}
```

- Each row gains a per-year override input and a "Clear" control when `editable` (Req 6.1, 6.3).
- A year whose amount comes from an override shows an `Override_Marker` — a short **textual** badge (e.g. "Filed value") so the distinction never rests on color alone (Req 7.1) — plus a one-line note that the year is pinned to reproduce a filed return value (Req 7.2). With no overrides the table renders exactly as today (Req 7.3).
- Override amounts are handled as strings through `toMoneyString`/`toCents`; no float math (Req 6.5).
- A rejected override surfaces its message inline next to that year's control from `overrideErrors[year]`, and the table does not present the override as saved (Req 6.4).

**`pages/AssetsPage.tsx`** — builds the updated override map and sends it via `updateAsset`, then reloads the schedule (Req 6.2, 6.3). On a 400 with field `depreciation_overrides.<year>` it maps the message into `overrideErrors` for the offending year (Req 6.4), reusing the existing `toFieldErrors` pattern (extended to split the dotted field into `{ year, message }`).

**`lib/money.ts`** — add `formatMoneyWholeDollars(amount: string | null | undefined): string` (algorithm above). Signature and passthrough mirror `formatMoney` so call sites swap one name for another.

## Data Models

No new item types, no new keys, no new routes. One optional attribute is added to the existing asset item.

**Asset item (`PK=PROPERTY#<id>`, `SK=ASSET#<assetId>`)** gains:

```
depreciationOverrides = { "<taxYear>": "<two-decimal string>", … }   # DynamoDB Map (M) of String (S)
```

- **Single attribute** satisfying Req 1.2 (no extra items/keys/routes/tables).
- **Map of two-decimal strings**, not Numbers: money never stored as a DynamoDB `Number`. Because the repository's `money_attrs` serializer only inspects **top-level** attribute names and does not recurse into a Map, `asset_to_item` renders each value with `money_to_str(...)` so the inner values are already strings when boto3's `TypeSerializer` writes the Map; `_from_item` parses each back with `to_money(...)`. The top-level asset write keeps `money_attrs={"costBasis"}` unchanged — `depreciationOverrides` is deliberately **not** added to that set, so the serializer never tries to money-coerce the Map as a scalar and corrupt it.
- **Sparse / backward compatible (Req 5.2, 5.3).** When the map is empty, `asset_to_item` omits the attribute (returns `None` for it, which the repository drops), so an override-free asset's stored shape is byte-for-byte what it is today. On read, an absent attribute parses to `{}`.

Why a Map rather than a JSON string: a Map keeps each override individually visible/queryable in the item and round-trips through the existing `put_item`/`get_item`/`_to_jsonable` machinery with no bespoke JSON (de)serialization, while still storing money as strings. A JSON string would also work but adds a parse/serialize step and hides the values inside an opaque blob; the Map is the smaller, more consistent choice given the repository already handles nested maps of strings.

**Transport.** `DepreciableAsset.depreciation_overrides: dict[int, Decimal]` serializes through `_to_jsonable` to `{ "<year>": "<two-decimal string>" }` (Req 1.4); the frontend types it as `Record<string, string>`.

## Correctness Properties

*A property is a characteristic or behavior that should hold true across all valid executions of a system — essentially, a formal statement about what the system should do. Properties serve as the bridge between human-readable specifications and machine-verifiable correctness guarantees.*

### Property 1: Invariant_Sum holds for arbitrary valid override maps

*For any* asset (positive two-decimal `cost_basis`, any placed-in-service month, any recovery period) and *any* valid Override_Map (every amount a non-negative two-decimal Money_String, every year within the computed span, sum ≤ `cost_basis`, tail reconcilable), the Effective_Schedule's per-year `amount` values sum to exactly the asset's `cost_basis`, as exact two-decimal `Decimal` values with no float.

**Validates: Requirements 2.3, 2.6, 4.4**

### Property 2: Invariant_Monotonic holds for arbitrary valid override maps

*For any* asset and *any* valid Override_Map, every Effective_Schedule row's `amount` is ≥ `0.00`, each `remaining_basis` equals `cost_basis` minus the cumulative amount through that year, `remaining_basis` is non-increasing across the ascending schedule, and the final row's `remaining_basis` is exactly `0.00` — all as exact two-decimal `Decimal`.

**Validates: Requirements 2.4, 2.6**

### Property 3: A no-override asset is identical to today

*For any* asset, `compute_schedule_rows` applied with an empty Override_Map produces a schedule identical, row for row and value for value (tax year, amount, remaining basis, method, convention), to the schedule the engine produces with the override step removed (the pre-feature behavior).

**Validates: Requirements 1.3, 5.1**

### Property 4: An overridden year's amount equals the override exactly

*For any* asset and *any* valid Override_Map, each overridden Tax_Year's Effective_Schedule `amount` equals that year's Override_Amount exactly — including when the overridden year is the Tail_Year (accepted only when the whole map already reconciles to `cost_basis`).

**Validates: Requirements 2.1, 2.2, 2.5**

### Property 5: Validation rejects every unsatisfiable override and persists nothing

*For any* asset and *any* Override_Map that falls into an unsatisfiable case — a negative or non-two-decimal amount; a year outside the computed span; a sum exceeding `cost_basis`; a tail that would be forced negative; or the Tail_Year overridden with no absorbing year and a map that does not already sum to `cost_basis` — the Depreciation_Service returns a `Result` `validation` failure whose `field` identifies the offending input (`depreciation_overrides` or `depreciation_overrides.<year>`), and no asset or schedule-row change is persisted.

**Validates: Requirements 3.1, 3.2, 3.3, 3.4, 3.5, 3.6**

### Property 6: Whole-dollar formatter rounds to the nearest dollar, half-up by magnitude, sign-preserving, integer-cents only

*For any* Money_String `s` (positive, negative, or zero), `formatMoneyWholeDollars(s)` renders the value whose whole-dollar magnitude equals `floor(abs(toCents(s)) / 100)` incremented by one when the cents remainder is ≥ 50 (and unchanged when < 50), carrying the sign of `s`, formatted as `en-US` USD with no fractional digits. The result equals the output computed by an independent integer-cents oracle for the same input, confirming no floating-point arithmetic and non-ceiling rounding.

**Validates: Requirements 8.1, 8.2, 8.3, 8.5, 8.6**

### Property 7: Formatter passthrough for empty, null, and non-numeric input

*For any* input that is `null`, `undefined`, or the empty string, `formatMoneyWholeDollars` returns `""`; *for any* non-numeric string, it returns that string unchanged — the same passthrough contract as `formatMoney`.

**Validates: Requirements 8.4**

### Property 8 (storage round-trip): overrides survive persistence unchanged

*For any* asset with *any* valid Override_Map, writing the asset and reading it back yields an Override_Map equal to the normalized (two-decimal) written map, with integer tax-year keys and `Decimal` values; an asset written with no Override_Map reads back with an empty map and a stored item shape identical to a pre-feature asset.

**Validates: Requirements 1.3, 5.2, 5.3**

## Error Handling

- **Invalid override amount** (negative, non-numeric, wrong precision) → `Result.failure("validation", "<message>", field="depreciation_overrides.<year>")` → 400 with the field; nothing persisted (Req 3.1).
- **Override for a non-schedule year** → `validation` failure on `depreciation_overrides.<year>` → 400; nothing persisted (Req 3.2).
- **Sum of overrides exceeds `cost_basis`** → `validation` failure on `depreciation_overrides` → 400; nothing persisted (Req 3.3).
- **Tail would be negative** / **tail overridden with no absorber** → `validation` failure on `depreciation_overrides` / `depreciation_overrides.<tailYear>` → 400; nothing persisted (Req 3.4, 3.5).
- **Absent / empty override map** → treated as no overrides everywhere (model default, `_coerce_overrides`, `_from_item`); never an error (Req 5.2).
- **Frontend** surfaces a rejected override inline next to the offending year's control via `overrideErrors[year]`, parsed from the 400 body's dotted `field`; the table does not present the override as saved (Req 6.4). A generic save failure falls back to the existing form/toast error path.
- **Whole-dollar formatter** never throws: empty/null/undefined → `""`, non-numeric → passthrough (Req 8.4), identical to `formatMoney`.
- **Unauthenticated / unconfigured** behavior is unchanged — the asset routes already gate auth and resolve the depreciation service as today.

## Backward Compatibility

- `DepreciableAsset.depreciation_overrides` defaults to `{}` and `AssetInput.depreciation_overrides` defaults to `None`, so every existing construction site and caller compiles and behaves unchanged.
- `asset_to_item` omits `depreciationOverrides` when the map is empty, so an override-free asset's stored item is byte-for-byte identical to today (Req 5.3); `_from_item` reads an absent attribute as `{}` (Req 5.2).
- `compute_schedule_rows` returns the base rows unchanged for an empty map (Property 3), so every existing schedule, the materialized rows, `property_depreciation_for_year`, the Schedule E report, the dashboard, and the passive-loss-carryforward reconciliation are unaffected (Req 5.1, 9.2).
- Whole-dollar rounding is display-only: no stored value, API payload, or computed value changes, and the API keeps serializing two-decimal Money_Strings (Req 9.1, 9.3). Excluded surfaces (TransactionsPage, AssetList cost-basis echo) keep `formatMoney` (Req 11.5).

## Testing Strategy

### Property-based tests (Hypothesis, backend)

Realize Properties 1–5 and 8 with the existing conventions (moto-backed DynamoDB with GSI2, the real `DepreciationService`, `@settings(max_examples≥100)`, tag `# Feature: depreciation-override-and-whole-dollar-display, Property N: <text>`), mirroring `test_property_year_depreciation_property.py` and `test_depreciation_schedule.py`:

- **Generators**: positive two-decimal `cost_basis`, placed-in-service dates across all months/years, a mix of recovery periods (`27.5`, `5`, `7`, `15`, `39`), and a **valid-override strategy** that draws a subset of the computed years and assigns non-negative two-decimal amounts whose sum ≤ `cost_basis` and whose tail reconciliation stays ≥ 0 (compose from the base schedule so generated maps are accepted). A separate **invalid-override strategy** deliberately produces each unsatisfiable case for Property 5.
- **P1/P2** run on the pure `compute_schedule_rows` (and once through the real `create_asset` → `schedule_for` → `property_depreciation_for_year` path to cover Req 4.4 materialization).
- **P3** compares the empty-map result against a reference computation with the override step disabled.
- **P4** asserts each overridden year's amount equals the override (including tail-year overrides that reconcile).
- **P5** drives the invalid strategy and asserts `Result.failure("validation", field=…)` and that no item was written (query the asset + schedule rows before/after).
- **P8** writes and reads assets (with/without overrides) asserting map equality and the unchanged item shape.

### Property-based tests (fast-check, frontend)

Realize Properties 6–7 in `frontend/src/lib/money.property.test.ts` alongside the existing money properties, reusing the `moneyString` arbitrary (extended to include negatives and zero) and tag `// Feature: depreciation-override-and-whole-dollar-display, Property N: <text>`, `numRuns: 100`:

- **P6** compares `formatMoneyWholeDollars(s)` against an independent integer-cents oracle (parse digits → round magnitude at 50 → reapply sign → format), over positive, negative, and zero inputs, asserting no decimal point in the output and correct `$`/grouping.
- **P7** asserts `""` for empty/null/undefined and passthrough for non-numeric strings.

### Unit / example tests (backend)

- Engine examples pinning the motivating case: a June-2010, $140,000, 27.5-year asset with `{2010: "1952.00"}` → 2010 amount `1952.00`, tail absorbs the delta, sum == `140000.00`, remaining basis monotone to `0.00`.
- `_coerce_overrides` per branch (negative, out-of-span, sum-exceeds, negative-tail, tail-no-absorber) with the exact field names.
- `create_asset` / `update_asset` / clear (empty map) / `delete_asset` through moto: persisted rows equal the Effective_Schedule; delete cascades (Req 4.1–4.3, 4.5).
- Item-shape test: an override-free asset item has no `depreciationOverrides` attribute (Req 5.3); `_asset_input` maps both snake_case and camelCase override bodies.
- Route example: `_to_jsonable` serializes the override map as `{ "<year>": "<two-decimal string>" }` (Req 1.4).

### Unit / example tests (frontend, RTL + Vitest)

- `ScheduleTable`: per-year override input + Clear control render when `editable`; an overridden year shows the textual `Override_Marker` and note (Req 7.1, 7.2); no marker with an empty map (Req 7.3); an `overrideErrors[year]` message renders inline (Req 6.4); amounts handled as strings (Req 6.5).
- `AssetsPage`: submitting/clearing an override calls `updateAsset` with the updated map and reloads the schedule (Req 6.2, 6.3); a 400 `depreciation_overrides.<year>` maps to the year's inline error.
- `formatMoneyWholeDollars` unit examples: `"5090.91"`→`$5,091`, `"5090.10"`→`$5,090`, `"5090.50"`→`$5,091`, `"-125.50"`→`-$126`, `""`/`null`/`undefined`→`""`, `"abc"`→`"abc"` (Req 8.1–8.6).
- Switched-site RTL asserting whole-dollar output **and** retained `tabular-nums` + `isLoss` cues: ReportView, ScheduleELineTable, OtherItemsList, ScheduleTable, DashboardPage (depreciation tile, net headline, net-by-property), CarryforwardPage money cells (Req 10.1, 10.2, 11.1–11.4).
- Excluded-site RTL asserting cents are retained via `formatMoney`: TransactionsPage transaction amounts, AssetList cost-basis echo (Req 11.5).

### Suites-green / no-float guardrails

The full backend suite (including the existing Invariant_Sum / Invariant_Monotonic property tests) and the full frontend build + test suite remain green (Req 12.1, 12.4); the new backend properties prove the invariants under overrides and backward compatibility (Req 12.2, 12.3); all rounding is exact integer cents with no floating-point arithmetic introduced (Req 12.5).

### Design properties → tests mapping

Each Correctness Property above is realized by at least one Hypothesis (P1–P5, P8) or fast-check (P6–P7) test; each acceptance criterion is covered by a property test, an example/integration test, or an RTL test as listed.
