# Design Document

## Overview

This feature extends the existing **passive loss carryforward reconciliation** so that the portion of a year's rental loss that was actually **allowed** (deducted) on the filed return no longer inflates the running suspended-loss balance. Today the engine suspends every loss year in full, which produces a systematic, correct-but-permanent false `mismatch` for any year whose loss was allowed under the §25,000 special allowance (the motivating case: 2010, Schedule E net `-758.00`, entire loss allowed, true carryforward `0.00`, but the app expects `758.00`).

The change is small and surgical. It adds a **per-year, optional `Allowed_Loss` amount** and a **per-year `Fully_Allowed` toggle** to the reconciliation, stored as two new optional attributes on the **existing** `PLCF#<year>` per-year item. In the running-balance loop a loss year now carries only its **unallowed** portion onto the balance; because the balance rolls forward, reducing one year's contribution automatically recomputes the `Expected_Carryforward` for every later year with no separate recalculation step. With a correct allowed amount, the expected figure becomes the true carryforward and a correct reported value reconciles to `ok`.

It stays firmly a **reconciliation aid, not a tax engine**. The app NEVER computes the IRC §469 limitation: no MAGI, no active-participation determination, no $25,000-allowance or phase-out math. It only records the user's transcribed allowed amount from their already-filed Form 8582 Part II line 10 and subtracts it from the year's suspended loss. The allowed amount is an input the user supplies, never a figure the app derives. The existing persistent disclaimer continues to state this.

The feature is additive and backward compatible by construction:

- **Backend**: `CarryforwardService` gains an `Effective_Allowed_Amount` step in its running-balance loop, a shared per-year net helper reused by both `reconcile()` and a new allowed-data validator, and two new partial-update setters plus clears for the allowed attributes. `set_reported` / `clear_reported` switch from a full `put_item` to read-modify-write so they stop clobbering sibling attributes. No new keys, item types, or routes.
- **Frontend**: `ReconciliationRow` gains an allowed-loss control (amount input + fully-allowed toggle) rendered **only on loss rows** (`schedule_e_net < 0`). On save/clear/toggle it calls the extended per-year update and reloads the series so expected/status recompute for that year and all later years. The existing reported editor, status behavior, opening-balance control, disclaimer, and empty state are untouched.

### Design decisions and rationale

- **Two independent optional attributes on the existing item, not a new item.** Requirement 2.1 forbids any new key, item type, or route. `allowedLoss` (a two-decimal money string) and `fullyAllowed` (a DynamoDB BOOL) are added to the existing `PLCF#<year>` item alongside the existing `amount` (reported) and `taxYear`. Each of the three value attributes — `amount`, `allowedLoss`, `fullyAllowed` — is **independently optional** on the same item. This co-locates the per-year state, round-trips through the existing `put_item` / `get_item` path, and is sparse (absent attribute == default).

- **`allowedLoss` is a money STRING in the item's `money_attrs` set; `fullyAllowed` is a BOOL.** All money in Logstead is a two-decimal string, never a DynamoDB `Number` (floats/Numbers drift). The per-year write/read must therefore name `allowedLoss` in its `money_attrs` set so the repository serializes it via `money_to_str` and parses it back via `to_money`, exactly as it does `amount`. `fullyAllowed` is a plain boolean flag — not money — so it is **not** in `money_attrs`; boto3's `TypeSerializer`/`TypeDeserializer` round-trips it as a DynamoDB `BOOL`, and `_to_jsonable` emits it as a JSON `true`/`false`. Storing `fullyAllowed` as a flag (Req 4.1), never a snapshot of the loss into `allowedLoss`, is what lets it track the current loss magnitude dynamically (Req 4.2-4.4).

- **Partial updates are read-modify-write, because the repository has no `UpdateExpression` path.** The repository exposes `put_item`, `delete_item`, `transact_write`, `get_item`, and `query` — there is no partial-update primitive. Today `set_reported` does a full `put_item` of `{amount, taxYear}`, which would wipe `allowedLoss`/`fullyAllowed` if left as-is. The design switches every per-year setter and clear to **read the current item, merge the one attribute it owns, and write the full merged item back** (a single `get_item` + `put_item`). This preserves siblings deterministically with the existing primitives and no schema change. See "Per-year item lifecycle" for the exact merge/delete rules.

- **The item is deleted only when it would carry no state at all.** A per-year item is meaningful iff it carries at least one of `amount`, `allowedLoss`, or `fullyAllowed` (Req 2.5). A clear operation removes only its own attribute; if the merged item would then carry none of the three, the clear **deletes the item** rather than leaving a bare `{taxYear}` tombstone. This keeps the `query` enumeration clean (no empty rows) and keeps `has_data`/reconciliation reasoning identical to today. (A bare `{taxYear}` tombstone was the considered alternative; deleting is chosen because the read path already skips items lacking a meaningful attribute, and an empty row would otherwise linger forever.)

- **`Effective_Allowed_Amount` centralizes the precedence rules.** A single helper computes, per year: `0.00` for a `Non_Loss_Year`; the current `Loss_Magnitude` when `Fully_Allowed` is on (dynamic, precedence over any stored `allowedLoss`, Req 4.2-4.4); otherwise the stored `allowedLoss` defaulting to `0.00` (Req 1.5, 4.5). The loss branch becomes `suspended = max(Loss_Magnitude - effective_allowed, 0.00); balance += suspended`. The gain branch is unchanged. Because `fully_allowed` yields `effective_allowed == Loss_Magnitude`, `suspended == 0.00` exactly (Req 3.7, 8.3).

- **Backward compatibility is by construction.** Absent `allowedLoss` reads as `0.00`; absent `fullyAllowed` reads as `False`. With both absent, `effective_allowed == 0.00`, so the loss branch reduces to `balance += (-net)` — byte-for-byte today's series (Req 7). Items written before this feature (only `{amount, taxYear}`) reconcile identically.

- **Validation reuses the reconcile loop's net derivation.** Validating an allowed amount or a fully-allowed toggle requires that year's `Schedule_E_Net` (to know the `Loss_Magnitude` and whether the year is a loss year at all). The per-year net derivation is factored into a shared helper `_schedule_e_net_for(year, properties)` used by both `reconcile()` and the new validator, so validation and reconciliation agree to the cent and stay user-scoped (list the user's properties + `report_for` for that year).

- **The UI shows the control only on loss rows, derived from the net already on the wire.** The `GET /carryforward` response already carries `schedule_e_net`; the frontend derives `loss = isLoss(schedule_e_net)` (net < 0) and renders the allowed control only there (Req 6.1, 6.2). No new "is loss" flag is needed on the wire, though the response gains `allowed_loss` and `fully_allowed` per year so the control can render its current state.

- **No float, two-decimal strings on the wire, §469 never computed.** Unchanged guarantees. Every figure stays an exact two-decimal `Decimal` in Python and a fixed two-decimal `Money_String` over the wire; the derivation consumes only the user-entered allowed data and the derived nets.

### Research notes (grounded in the existing codebase)

- **Running-balance loop** (`services/carryforward.py`): `reconcile()` lists properties once, reads the opening balance (`get_item` on `PLCF_OPENING`) and every reported entry (`query` on the `PLCF#` prefix, which does **not** match the `PLCF_OPENING` singleton; it also skips items lacking `taxYear`/`amount`). Per year it sums `report_for(pid, year).value.totals.net` across properties (a non-ok report contributes `0.00`), then applies the loss/gain branch: `balance = balance + (-net)` on a loss, `balance = max(balance - net, 0.00)` on a gain. Status is `unreported` / `ok` / `mismatch`.
- **Per-year item shape**: `{PK: user_pk(userId), SK: plcf_year_sk(year), amount: "<two-decimal>", taxYear: <int>}`. `set_reported` currently does a full `put_item` of exactly those four fields; `clear_reported` does `delete_item`; `set_opening_balance` writes the `PLCF_OPENING` singleton. `_validate_amount` normalizes via `to_money` and rejects negatives with `Result.failure("validation", msg, field="amount")`.
- **Keys** (`repository/keys.py`): `PLCF_PREFIX = "PLCF#"`, `plcf_year_sk(year)`, `plcf_list_prefix()`, `PLCF_OPENING_SK = "PLCF_OPENING"`, `plcf_opening_sk()`. No new key helper is required.
- **Repository money handling** (`repository/dynamo_repo.py`): `_prepare_item` drops `None` values (sparse write) and renders any name in the call's `money_attrs` as a two-decimal `S`; all other attrs go through boto3's `TypeSerializer` (so a Python `bool` → DynamoDB `BOOL`). `_parse_item` parses `money_attrs` names back via `to_money` and everything else via `TypeDeserializer`. `money_attrs` is **per-call** (default `DEFAULT_MONEY_ATTRS = {"amount","costBasis","remainingBasis"}`); the per-year writes/reads must pass `money_attrs={"amount", "allowedLoss"}` so both money fields are strings and `fullyAllowed` stays a BOOL. The repo has **no** `update_item` — partial updates are read-modify-write.
- **Routes** (`router/handler.py`): `GET /carryforward` → `_carryforward_reconcile` → `_response(200, reconcile())`; `PUT /carryforward/years/{taxYear}` → `_set_carryforward_reported` reads `body["amount"]`; `DELETE` → `_clear_carryforward_reported`; `PUT /carryforward/opening-balance` → `_set_carryforward_opening`. `_int_param` guards non-integer `{taxYear}` → 400 before the service runs. `_result_response` maps `validation` → 400 (with `field`). `_to_jsonable` renders `Decimal` → exact string, dataclasses → field dicts (snake_case preserved), `bool` → JSON boolean.
- **Frontend** (`api/carryforward.ts`, `pages/CarryforwardPage.tsx`): `ReconciledYear` wire type has `tax_year`, `schedule_e_net`, `expected_carryforward`, `reported_carryforward`, `status`. `CarryforwardApi` has `getReconciliation` / `setReported(year, amount)` / `clearReported(year)` / `setOpeningBalance(amount)`. `ReconciliationRow` renders `ScheduleENetCell` (uses `isLoss` + `formatMoneyWholeDollars`), the expected cell, `ReportedEditor` (save/clear → parent `load()` refresh), and `StatusCell`. Money renders via `formatMoneyWholeDollars`; `isLoss(net)` already exists. `isNonNegativeAmount` validates input client-side; `amountErrorMessage` extracts the 400 `field`/`message`.

## Architecture

```
Carryforward_Page (frontend/src/pages/CarryforwardPage.tsx)
  │  allowed control on LOSS rows only (isLoss(schedule_e_net))
  │  save/clear/toggle → extended per-year update → reload series
  ▼
Carryforward_API (frontend/src/api/carryforward.ts)
  │  GET  /carryforward                   → series incl. allowed_loss, fully_allowed
  │  PUT  /carryforward/years/{taxYear}    → body may carry amount, allowed_loss, fully_allowed
  │  DELETE /carryforward/years/{taxYear}  → clear Reported_Carryforward (allowed preserved)
  │  PUT  /carryforward/opening-balance    → set Opening_Balance (unchanged)
  ▼
router/handler.py  (_set_carryforward_reported extended; others unchanged)
  ▼
CarryforwardService (backend/src/logstead/services/carryforward.py)
  │  reconcile():  derive nets → effective_allowed → roll balance → merge reported → status
  │  _schedule_e_net_for(year, properties)         (shared net derivation)
  │  _effective_allowed(net, allowed_loss, fully_allowed)  (precedence rules)
  │  set_reported / clear_reported                 (now read-modify-write; preserve siblings)
  │  set_allowed_loss / clear_allowed_loss         (new; partial update)
  │  set_fully_allowed(year, on)                   (new; partial update)
  │  set_opening_balance                           (unchanged)
  ├── ReportingService.report_for(pid, year)       (derived nets, reused)
  ├── PropertyService.list()                        (user's properties)
  └── DynamoRepository                              (PLCF# per-year items + PLCF_OPENING)
```

### Running-balance algorithm (Req 3, 4, 7, 8)

The loop differs from today only in computing `effective_allowed` and subtracting it from the loss magnitude before adding to the balance. All arithmetic is exact `Decimal` quantized to two places; the balance is a non-negative magnitude.

```
balance = opening_balance                 # non-negative magnitude, default 0.00
for year in sorted(data_years):           # ascending
    net = schedule_e_net(year)            # Decimal; negative = loss
    if net < 0:                           # Loss_Year
        loss_magnitude   = -net           # non-negative
        effective_allowed = effective_allowed_for(year)   # see below
        suspended = max(loss_magnitude - effective_allowed, 0.00)
        balance = balance + suspended     # only the unallowed portion carries
    else:                                 # Non_Loss_Year (gain or break-even)
        balance = max(balance - net, 0.00)  # unchanged; no allowed amount applies
    expected[year] = balance              # Expected_Carryforward for the year
    # status unchanged: unreported / ok / mismatch
```

where

```
effective_allowed_for(year):
    if net >= 0:                 return 0.00            # Non_Loss_Year (Req 3.2, 3.8)
    if fully_allowed[year]:      return -net            # current Loss_Magnitude (Req 4.2-4.4)
    return allowed_loss.get(year, 0.00)                 # stored amount or 0.00 (Req 1.5, 4.5)
```

**Why the invariants hold.**

- *Non-negativity (Req 3.4, 9.2).* `suspended = max(loss_magnitude - effective_allowed, 0.00) >= 0`, so a loss year only ever **adds** a non-negative amount to a balance that starts non-negative. The gain branch floors at `0.00`. Therefore `balance` and every `expected` stay `>= 0.00` for all inputs — including `effective_allowed > loss_magnitude` (defended against by validation, but the `max(..., 0)` floor makes it safe regardless).
- *Fully-allowed contributes exactly zero (Req 3.7, 8.3).* When `fully_allowed[year]` is on, `effective_allowed == -net == loss_magnitude`, so `suspended == max(0.00, 0.00) == 0.00`. The year adds nothing to the balance, and the explicit `allowed_loss == loss_magnitude` case produces the identical `suspended == 0.00` — so the fully-allowed toggle and the explicit full amount agree to the cent (Req 8.3).
- *Delta rolls forward (Req 3.3).* `expected[year]` is assigned as the running `balance` and carried into the next iteration unchanged. Reducing year N's `suspended` lowers `balance` from year N onward, so every later `expected` drops by the same delta automatically — no separate recalculation.
- *Backward compatibility (Req 7).* With no allowed data, `effective_allowed == 0.00` for every year, so the loss branch is `balance += (-net)` and the gain branch is unchanged — identical to today's loop, hence a byte-for-byte identical `Expected_Carryforward` series for the same nets and opening balance.

### Per-year item lifecycle (Req 1, 2)

The existing `PLCF#<year>` item now carries up to three independent value attributes. Every write is a **read-modify-write**: read the current item (`get_item` with `money_attrs={"amount","allowedLoss"}`), merge, and write back the full merged item (or delete when empty). All operations are confined to `user_pk(userId)` (Req 2.6, 9.6).

| Operation | Merge rule | Result when nothing remains |
|---|---|---|
| `set_reported(year, amount)` | validate; set `amount`; keep `allowedLoss`/`fullyAllowed` | n/a (always has `amount`) |
| `clear_reported(year)` | drop `amount`; keep `allowedLoss`/`fullyAllowed` | delete item if no `allowedLoss` and not `fullyAllowed` |
| `set_allowed_loss(year, amount)` | validate against loss; set `allowedLoss`; keep `amount`/`fullyAllowed` | n/a (always has `allowedLoss`) |
| `clear_allowed_loss(year)` | drop `allowedLoss`; keep `amount`/`fullyAllowed` | delete item if no `amount` and not `fullyAllowed` |
| `set_fully_allowed(year, true)` | validate year is a loss year; set `fullyAllowed=True`; keep `amount`/`allowedLoss` | n/a |
| `set_fully_allowed(year, false)` | drop `fullyAllowed` (treated as not fully allowed, Req 4.6); keep `amount`/`allowedLoss` | delete item if no `amount` and no `allowedLoss` |

The merged item is always written with `taxYear` set (so the read path's `query` enumeration sees it). An item carries state iff it has at least one of `amount`, `allowedLoss`, `fullyAllowed`; otherwise it is deleted (Req 2.5), never left as a bare `{taxYear}` tombstone.

Setting `fullyAllowed=False` stores **no** `fullyAllowed` attribute (sparse: absent == not fully allowed, Req 4.6), rather than persisting `fullyAllowed: false` — this keeps "off" and "never set" indistinguishable and the item sparse. `_prepare_item` already drops `None`, so passing `fullyAllowed=None` into the merged item omits it.

### Read path (Req 1.5, 2.2-2.5, 7.2)

`reconcile()` keeps reading the opening balance up front, then enumerates the `PLCF#` items once with `query(..., sk_begins_with=plcf_list_prefix(), money_attrs={"amount","allowedLoss"})`. For each enumerated item (skipping any lacking `taxYear`, as today, and noting the `PLCF_OPENING` singleton is not matched by the prefix) it collects into three per-year maps, each independently optional:

```
reported[year]     = to_money(item["amount"])        if "amount" in item
allowed_loss[year] = to_money(item["allowedLoss"])   if "allowedLoss" in item   # else absent → 0.00
fully_allowed[year]= bool(item.get("fullyAllowed"))  # absent → False
```

An item may populate any subset (reported-only, allowed-only, both, allowed+fully, etc.). Absent `allowedLoss` → `0.00`; absent `fullyAllowed` → `False` (Req 1.5, 7.2). The loop then uses these maps via `effective_allowed_for`.

## Components and Interfaces

### Backend

**`CarryforwardService`** (`backend/src/logstead/services/carryforward.py`) — same constructor and collaborators; new/changed methods:

```python
def reconcile(self) -> ReconciliationSummary:
    """Derive nets for every Data_Year, compute each year's
    Effective_Allowed_Amount, roll the Expected_Carryforward forward
    (a loss adds only its unallowed portion; a gain is absorbed, floored at
    0.00), merge stored Reported_Carryforward entries, and classify each year.
    Never applies §469 (Req 3, 4, 7, 8)."""

# --- shared derivation (factored out of reconcile) ---
def _schedule_e_net_for(self, tax_year: int, properties: list) -> Money:
    """Exact-cent sum across the user's properties of
    report_for(pid, tax_year).value.totals.net; a non-ok report contributes
    0.00 (mirrors the dashboard skip). Used by reconcile() AND validation so
    both agree to the cent (Req 5.2)."""

@staticmethod
def _effective_allowed(net: Money, allowed_loss: Money | None, fully_allowed: bool) -> Money:
    """0.00 for a Non_Loss_Year; -net when fully_allowed (current Loss_Magnitude,
    precedence); else allowed_loss or 0.00 (Req 3.2, 4.2-4.6)."""

# --- new partial-update setters/clears (read-modify-write) ---
def set_allowed_loss(self, tax_year: int, amount: str) -> Result[None]:
    """Validate a non-negative two-decimal amount, derive the year's net, reject
    allowed>loss_magnitude or allowed>0 on a Non_Loss_Year (field="allowedLoss"),
    then merge allowedLoss onto the per-year item preserving amount/fullyAllowed
    (Req 1.1-1.3, 2.2-2.3, 5)."""

def clear_allowed_loss(self, tax_year: int) -> Result[None]:
    """Remove only allowedLoss; preserve amount/fullyAllowed; delete the item if
    it would then carry no state. Idempotent (Req 1.4, 2.4, 2.5)."""

def set_fully_allowed(self, tax_year: int, on: bool) -> Result[None]:
    """Turning on: validate the year is a Loss_Year (else field="fullyAllowed"),
    merge fullyAllowed=True preserving amount/allowedLoss (NOT snapshotting the
    loss, Req 4.1). Turning off: drop fullyAllowed, delete the item if empty
    (Req 4.5, 4.6, 5.4)."""

# --- changed: now preserve siblings via read-modify-write ---
def set_reported(self, tax_year: int, amount: str) -> Result[None]:
    """As today, but merges amount onto the existing item preserving
    allowedLoss/fullyAllowed instead of a full put_item (Req 2.3)."""

def clear_reported(self, tax_year: int) -> Result[None]:
    """Remove only amount; preserve allowedLoss/fullyAllowed; delete the item if
    it would then carry no state (Req 2.4, 2.5)."""
```

Validation helpers (Req 5): a new `_validate_allowed(tax_year, amount, properties)`:

1. Normalize `amount` via the existing `_validate_amount` shape → reject negative / non-two-decimal with `field="allowedLoss"` (Req 5.1, 5.6).
2. Derive the year's net via `_schedule_e_net_for` (Req 5.2).
3. If the year is a `Non_Loss_Year` (`net >= 0`) and `amount > 0.00` → reject with `field="allowedLoss"` (Req 5.4).
4. If `amount > loss_magnitude` (`-net`) → reject with `field="allowedLoss"` (Req 5.3).
5. Else accept (`0.00 <= amount <= loss_magnitude`, Req 5.5).

`set_fully_allowed(year, True)` derives the year's net and rejects on a `Non_Loss_Year` with `field="fullyAllowed"` (Req 5.4). Every rejection persists nothing and uses `Result.failure("validation", message, field=...)` (Req 5.6). Deriving the net lists the user's properties and calls `report_for` for that year, exactly as `reconcile()` does — kept user-scoped.

**Routes** (`router/handler.py`): no new routes (Req 2.1). Only `_set_carryforward_reported` changes, to read the optional allowed fields from the body and route them to the right setter(s):

```python
def _set_carryforward_reported(wiring, user, params, body, query):
    service = _carryforward_service_or_503(wiring, user)
    tax_year = _int_param(params["taxYear"], "taxYear")
    # Each field is independently optional. A present "amount" sets/updates the
    # reported value; "allowed_loss" (string) sets it, JSON null clears it;
    # "fully_allowed" (bool) toggles. Omitted fields are left untouched. The
    # first validation failure short-circuits and is returned via _result_response
    # so nothing is persisted on a bad submission (Req 5, 6.5).
    ...
    return _result_response(result)
```

Body contract for `PUT /carryforward/years/{taxYear}`:

| Field | Type | Meaning | Omitted |
|---|---|---|---|
| `amount` | string (money) | set/replace Reported_Carryforward | leave reported untouched |
| `allowed_loss` | string (money) \| `null` | string sets it; `null` **clears** it | leave allowed untouched |
| `fully_allowed` | boolean | `true` turns on, `false` turns off | leave flag untouched |

"Clear allowed" is expressed as `allowed_loss: null` (explicit), distinct from omitting the field (leave as-is). `DELETE /carryforward/years/{taxYear}` continues to clear **only** the reported value (`clear_reported`), preserving allowed data (Req 2.4). `_result_response` maps a `validation` failure to 400 with its `field` (`allowedLoss`/`fullyAllowed`/`amount`).

The `GET /carryforward` response gains two per-year fields via the `ReconciledYear` dataclass (serialized by `_to_jsonable`): `allowed_loss` (two-decimal `Money_String`, `"0.00"` when none) and `fully_allowed` (JSON boolean). `schedule_e_net`, `expected_carryforward`, `reported_carryforward`, and `status` are unchanged. The UI derives loss-vs-gain from `schedule_e_net` (net < 0), so no separate "is loss" flag is added to the wire.

### Frontend

**`Carryforward_API`** (`frontend/src/api/carryforward.ts`): extend the `ReconciledYear` wire type and the per-year update.

```ts
export interface ReconciledYear {
  readonly tax_year: number;
  readonly schedule_e_net: string;         // Money_String; negative = loss
  readonly expected_carryforward: string;  // Money_String, non-negative
  readonly reported_carryforward: string | null;
  readonly allowed_loss: string;           // Money_String, non-negative ("0.00" when none)
  readonly fully_allowed: boolean;         // whole loss allowed for the year
  readonly status: "ok" | "mismatch" | "unreported";
}

// Extend the existing per-year setter to carry optional allowed fields.
// `allowed_loss: null` clears; omitting a field leaves it untouched.
setYear(
  taxYear: number,
  patch: { amount?: string; allowed_loss?: string | null; fully_allowed?: boolean },
  signal?: AbortSignal,
): Promise<void>;
```

`setReported`/`clearReported`/`setOpeningBalance` keep their signatures (so the existing reported editor is untouched); `setReported` is a thin wrapper over `setYear(year, { amount })`. New convenience wrappers `setAllowedLoss(year, amount)` → `setYear(year, { allowed_loss })`, `clearAllowedLoss(year)` → `setYear(year, { allowed_loss: null })`, and `setFullyAllowed(year, on)` → `setYear(year, { fully_allowed: on })` keep the page's call sites readable. All go to the existing `PUT /carryforward/years/{taxYear}` (no new route).

**`Carryforward_Page`** (`frontend/src/pages/CarryforwardPage.tsx`): `ReconciliationRow` gains an `AllowedLossControl` rendered **only when `isLoss(year.schedule_e_net)`** (Req 6.1, 6.2). The control holds:

- A **fully-allowed toggle** (checkbox/switch) bound to `year.fully_allowed`. While on, it indicates the full loss is allowed and the explicit amount input is made **moot** — disabled or hidden (Req 6.3).
- An **allowed-amount input** + Save/Clear, validated client-side with the existing `isNonNegativeAmount` (and surfacing the server's 400 `allowed_loss`/`allowedLoss` field error via a parallel of `amountErrorMessage`). Inline error announced with `role="alert"` and tied via `aria-describedby`, next to the offending control (Req 6.5).

On save/clear/toggle the control calls the extended API (`setAllowedLoss`/`clearAllowedLoss`/`setFullyAllowed`) and then triggers the page's existing `load()` so the whole series refreshes in place — expected and status recompute for that year and every later year without a full reload (Req 6.4). Non-loss rows render no control (Req 6.2). Money renders through the existing `formatMoneyWholeDollars` (and the allowed input echoes the stored two-decimal string); no float is introduced (Req 6.7, 9.4). The existing reported editor, `ok`/`mismatch`/`unreported` status, opening-balance control, disclaimer, and empty state are all retained (Req 6.6).

## Data Models

No new item types, no new keys, no new routes. Two optional attributes are added to the existing per-year item.

**Per_Year_Item (`PK=USER#<userId>`, `SK=PLCF#<taxYear>`)** — each value attribute independently optional:

```
PK          = USER#<userId>
SK          = PLCF#<taxYear>
taxYear     = <int>                      # always present while the item exists
amount      = "<two-decimal string>"     # Reported_Carryforward (optional)
allowedLoss = "<two-decimal string>"     # Allowed_Loss amount (optional)   ← new, money string
fullyAllowed= true                        # Fully_Allowed flag (optional)    ← new, DynamoDB BOOL
```

- `allowedLoss` is serialized/parsed as money by passing `money_attrs={"amount", "allowedLoss"}` on the per-year `put_item`/`get_item`/`query`. Never a DynamoDB `Number`.
- `fullyAllowed` is a boolean: present and `true` means fully allowed; **absent** means not fully allowed (sparse; `false` is never stored, Req 4.6). It is NOT in `money_attrs`; boto3 serializes a Python `bool` as `BOOL`.
- The item exists iff it carries at least one of `amount` / `allowedLoss` / `fullyAllowed` (Req 2.5). `_prepare_item` drops `None`, so the merged write is sparse and backward compatible (an untouched pre-feature item is exactly `{amount, taxYear}`).
- The `PLCF_OPENING` singleton is unchanged and still not matched by the `PLCF#` prefix query.

**Backend transport dataclasses** (`services/carryforward.py`) — `ReconciledYear` gains two fields; money as `util.money.Money`, serialized to strings/booleans by the router:

```python
@dataclass(frozen=True)
class ReconciledYear:
    tax_year: int
    schedule_e_net: Money
    expected_carryforward: Money
    reported_carryforward: Money | None
    allowed_loss: Money            # non-negative; 0.00 when none stored   ← new
    fully_allowed: bool            # whole loss allowed for the year       ← new
    status: Literal["ok", "mismatch", "unreported"]

@dataclass(frozen=True)
class ReconciliationSummary:
    years: tuple[ReconciledYear, ...]
    opening_balance: Money
    has_data: bool
```

`allowed_loss` surfaces the stored amount (`0.00` when absent); `fully_allowed` surfaces the flag. These let the frontend render the control's current state and decide loss-vs-gain (via `schedule_e_net`). `_to_jsonable` renders `allowed_loss` as `"0.00"`-style strings and `fully_allowed` as a JSON boolean.

## Correctness Properties

*A property is a characteristic or behavior that should hold true across all valid executions of a system — essentially, a formal statement about what the system should do. Properties serve as the bridge between human-readable specifications and machine-verifiable correctness guarantees.*

### Property 1: Suspended loss is the floored unallowed portion and the balance stays non-negative

*For any* Opening_Balance, sequence of per-year nets (losses and gains), and per-year allowed data (arbitrary non-negative allowed amounts and arbitrary fully-allowed flags), processing the years ascending yields, for each Loss_Year, `suspended == max((-net) - effective_allowed, 0.00)` with `balance += suspended`; for each Non_Loss_Year, `balance == max(prior_balance - net, 0.00)`; and every `Expected_Carryforward` and the running balance are `>= 0.00`, as exact two-decimal `Decimal`.

**Validates: Requirements 3.1, 3.2, 3.4, 3.5, 9.2**

### Property 2: Backward compatibility — no allowed data reproduces today's series exactly

*For any* Opening_Balance and sequence of per-year nets, when no year has any stored `Allowed_Loss` and no year is `Fully_Allowed`, the `Expected_Carryforward` series and every `Reconciliation_Status` are byte-for-byte identical to the pre-feature running-balance recurrence (a loss adds its full magnitude; a gain is absorbed, floored at `0.00`) over the same nets and opening balance.

**Validates: Requirements 7.1, 7.2, 7.3, 9.3**

### Property 3: Fully-allowed contributes zero and equals the explicit-full-amount case

*For any* Loss_Year, turning on `Fully_Allowed` makes that year contribute `0.00` to the `Suspended_Loss_Balance` (its `suspended == 0.00`), and the resulting `Expected_Carryforward` equals the one produced by instead storing an explicit `Allowed_Loss` equal to that year's current `Loss_Magnitude` — even when the year's net later changes (the flag tracks the current magnitude dynamically, taking precedence over any stored `Allowed_Loss`).

**Validates: Requirements 3.7, 4.2, 4.3, 4.4, 8.3**

### Property 4: Monotonic roll-forward of a year's allowed amount

*For any* reconciliation, increasing a single Loss_Year's `Effective_Allowed_Amount` (up to its `Loss_Magnitude`) never increases — and strictly decreases while that year's `suspended` is positive — that year's and every later year's `Expected_Carryforward`; decreasing it never decreases them. (The delta rolls forward with no separate recalculation.)

**Validates: Requirements 3.1, 3.3**

### Property 5: Validation rejects impossible allowed data and persists nothing

*For any* submission, an `Allowed_Loss` that is negative or not a two-decimal money value, or that exceeds the year's `Loss_Magnitude`, or an `Allowed_Loss > 0.00` or `Fully_Allowed = true` on a Non_Loss_Year, is rejected with a `Result` `validation` failure whose `field` identifies the offending input (`allowedLoss` or `fullyAllowed`), and no per-year item attribute is created or changed; an amount in `[0.00, Loss_Magnitude]` on a Loss_Year is accepted and persisted.

**Validates: Requirements 5.1, 5.2, 5.3, 5.4, 5.5, 5.6**

### Property 6: Persistence round-trip — allowed data and reported value are independent, siblings never clobbered

*For any* per-year item, writing then reading back yields each of `amount`, `allowedLoss`, and `fullyAllowed` equal to its normalized written value (two-decimal money for the amounts, boolean for the flag); setting or clearing any one attribute preserves the other two unchanged; clearing the last remaining attribute deletes the item; and an item written with only a reported value (the pre-feature shape) reads back with `allowed_loss == 0.00` and `fully_allowed == false`.

**Validates: Requirements 1.1, 1.2, 1.3, 1.4, 2.2, 2.3, 2.4, 2.5, 4.1, 7.2**

### Property 7: The 2010 acceptance scenario reconciles to ok, both ways

*For* a Loss_Year with `Schedule_E_Net == -758.00` carried into from a `0.00` balance: recording `Allowed_Loss == 758.00` produces `Expected_Carryforward == 0.00`; turning on `Fully_Allowed` (with no explicit amount) also produces `Expected_Carryforward == 0.00`; and in either case recording `Reported_Carryforward == 0.00` assigns the year the `ok` status.

**Validates: Requirements 8.1, 8.2, 8.3**

### Property 8: Every figure is a two-decimal money string; the flag is a boolean

In the serialized `GET /carryforward` body, `schedule_e_net`, `expected_carryforward`, every non-null `reported_carryforward`, and `allowed_loss` match `^-?\d+\.\d{2}$`; `fully_allowed` is a JSON boolean; `tax_year` is an integer; `status` is a known literal — and the `Expected_Carryforward` depends only on the nets, the opening balance, and the user-entered allowed data (no §469 allowance/phase-out logic influences it).

**Validates: Requirements 1.6, 3.5, 3.6, 9.4, 9.5**

## Error Handling

- **Bad `Allowed_Loss` amount** (negative, non-numeric, wrong precision) on `set_allowed_loss` / the extended per-year PUT → `Result.failure("validation", ..., field="allowedLoss")` → 400 with the field; nothing persisted (Req 5.1, 5.6).
- **`Allowed_Loss` exceeds the year's `Loss_Magnitude`** → `validation` failure on `allowedLoss` → 400; nothing persisted (Req 5.3).
- **`Allowed_Loss > 0.00` or `Fully_Allowed = true` on a Non_Loss_Year** → `validation` failure on the offending field (`allowedLoss` / `fullyAllowed`) → 400; nothing persisted (Req 5.4).
- **Clearing an absent `Allowed_Loss` or toggling `Fully_Allowed` off when already off** → success (idempotent), the item unchanged or deleted when it carries no remaining state (Req 1.4, 2.5, 4.6).
- **Clearing the reported value on a year that still has allowed data** → the reported `amount` is removed, `allowedLoss`/`fullyAllowed` preserved; the item is not deleted (Req 2.4).
- **Non-integer `{taxYear}`** → 400 via the existing `_int_param` guard, before the service runs.
- **A user-owned property whose `report_for` is not ok** for a year → contributes `0.00` to that year's net; reconciliation and validation never raise (mirrors the dashboard skip).
- **Unconfigured dependency / unauthenticated** → the existing 503 / 401 paths, unchanged.
- **Frontend** surfaces a rejected allowed submission inline next to the offending control (`role="alert"`, `aria-describedby`) and does not alter the displayed reconciliation (Req 6.5); a load failure keeps the disclaimer visible.

## Backward Compatibility

- `ReconciledYear` gains `allowed_loss` (default `0.00` for a year with no stored amount) and `fully_allowed` (default `false`); the pre-existing fields and the `ok`/`mismatch`/`unreported` rules are preserved (Req 7.4).
- Absent `allowedLoss` reads as `0.00`; absent `fullyAllowed` reads as `False`; a pre-feature `{amount, taxYear}` item reconciles exactly as before (Req 7.2).
- With no allowed data anywhere, `effective_allowed == 0.00` every year, so the running-balance loop is identical to today — a byte-for-byte identical `Expected_Carryforward` series for the same Schedule E data and opening balance (Req 7.1, 7.3, 9.3).
- The per-year item stays sparse: `set_fully_allowed(..., False)` and every clear drop the attribute (never store `false`), and an item with no value attribute is deleted, so no new empty rows appear in the `PLCF#` enumeration.
- No stored value, route shape, or wire money representation changes form: money stays two-decimal strings; the one added non-money field is a boolean (Req 9.1, 9.4). The §469 boundary and disclaimer are unchanged (Req 9.5).

## Testing Strategy

### Property-based tests (Hypothesis, backend)

Realize Properties 1–8 against a `moto`-backed single-table DynamoDB (base + GSI1 + GSI2) + S3 bucket with the real composed `CarryforwardService` / `PropertyService` / `ReportingService` / `TransactionService` / `DepreciationService` stack, mirroring the existing `test_carryforward_running_balance_property.py` and `test_carryforward_persistence_property.py` (per-example provisioning, `deadline=None`, `@settings(max_examples=100)`, tag `# Feature: carryforward-allowed-loss, Property N: <text>`):

- **Generators**: properties/transactions producing varied per-year nets (mixed losses and gains across non-contiguous years), opening balances, per-year allowed amounts (non-negative two-decimal, drawn in `[0, loss_magnitude]` for the valid strategy and out of range for the invalid strategy), and fully-allowed flags. A **valid-allowed strategy** pairs each Loss_Year with an amount `<= loss_magnitude`; an **invalid-allowed strategy** deliberately produces each unsatisfiable case for Property 5 (negative, non-two-decimal, `> loss_magnitude`, non-loss-year with amount/flag).
- **P1/P4** run through the real `reconcile()` over generated data, comparing against an independent integer-/`Decimal`-cents recurrence that applies `effective_allowed` exactly, and asserting non-negativity and the monotonic roll-forward under single-year allowed perturbations.
- **P2** disables all allowed data and asserts the series equals the pre-feature recurrence over the same returned nets.
- **P3** sets a Loss_Year fully-allowed and compares against the same year with an explicit amount equal to its (possibly re-derived) `Loss_Magnitude`, including a net change between runs to prove dynamic tracking.
- **P5** drives the invalid strategy through `set_allowed_loss` / `set_fully_allowed` and asserts `Result.failure("validation", field=…)` and that the per-year item is unchanged (query before/after).
- **P6** writes/reads per-year items with every subset of `{amount, allowedLoss, fullyAllowed}`, asserting independent round-trip, sibling preservation across single-attribute set/clear, item deletion when empty, and the pre-feature-shape default read.
- **P7** pins the `-758.00` scenario both ways (explicit `758.00` and fully-allowed) → expected `0.00` → reported `0.00` → `ok`.
- **P8** asserts the serialized `GET /carryforward` money-string regex, the boolean `fully_allowed`, and §469-independence (expected equals the allowed-aware recurrence over the nets + opening balance alone).

### Property-based tests (fast-check, frontend)

In `frontend/src/pages/` / `src/api/` alongside the existing money/property tests (tag `// Feature: carryforward-allowed-loss, Property N: <text>`, `numRuns: 100`): a frontend property asserting that for any generated `ReconciledYear`, the `AllowedLossControl` renders **iff** `isLoss(schedule_e_net)`, and that saving/clearing/toggling calls the extended per-year update with the expected patch shape (`{ amount }` / `{ allowed_loss }` / `{ allowed_loss: null }` / `{ fully_allowed }`) and then reloads the series.

### Unit / example tests (backend)

- `reconcile` on a hand-built fixture: a partially-allowed loss year, a fully-allowed loss year, a year with allowed data but no reported value (and vice versa), a non-contiguous gap year, and an opening balance — asserting exact `Expected_Carryforward`, `allowed_loss`, `fully_allowed`, and statuses, including the delta rolling onto later years.
- `set_allowed_loss` / `clear_allowed_loss` / `set_fully_allowed` / `set_reported` / `clear_reported`: persistence, replace, sibling preservation, empty-item deletion, idempotent clear, validation rejection with exact field names, user scoping.
- Route example tests: the extended `PUT /carryforward/years/{taxYear}` with each field subset (200 shapes, 400 on bad `allowed_loss`/`fully_allowed` with the right `field`, non-integer year), `allowed_loss: null` clears while preserving reported, and `DELETE` clears only reported; `GET /carryforward` body carries `allowed_loss` (money string) and `fully_allowed` (boolean).

### Unit / example tests (frontend, RTL + Vitest)

- `CarryforwardPage`: the allowed control appears only on loss rows and is hidden/disabled on gain/break-even rows (Req 6.1, 6.2); while fully-allowed is on, the amount input is moot (Req 6.3); save/clear/toggle calls the extended API and reloads so expected/status update for the year and later years (Req 6.4); a 400 `allowed_loss` error renders inline next to the control and leaves the reconciliation unchanged (Req 6.5); the reported editor, status labels, opening-balance control, disclaimer, and empty state remain intact (Req 6.6); money renders via `formatMoneyWholeDollars` (Req 6.7).
- `api/carryforward` unit tests: `setYear`/`setAllowedLoss`/`clearAllowedLoss`/`setFullyAllowed` hit `PUT /carryforward/years/{taxYear}` with the expected body (money as strings, `allowed_loss: null` to clear, `fully_allowed` boolean) and no new route; `ReconciledYear` types `allowed_loss: string` and `fully_allowed: boolean`.

### Suites-green / no-float / §469 guardrails

The full backend suite (including the existing carryforward running-balance, persistence, status, and money-string property tests) and the full frontend build + test suite remain green (Req 9.1); the new properties prove the non-negativity and backward-compatibility invariants (Req 9.2, 9.3); all arithmetic stays exact two-decimal `Decimal` / integer-cents with no float introduced (Req 9.4); and the derivation consumes only the user-entered allowed data and the derived nets, never computing the §469 limitation (Req 9.5), with every read/write confined to the authenticated user's partition (Req 9.6).

### Design properties → tests mapping

Each Correctness Property above is realized by at least one Hypothesis (P1–P8) or fast-check (frontend) test; each acceptance criterion is covered by a property test, an example/route test, or an RTL test as listed.
