# Star Slice 1 — Expiry Input + Waste Dashboard (Design)

> Part of the "close the loop on food waste, delicious recipes one tap away" north
> star. First of the four star slices (sequence 1 → 3 → 2 → 4). Builds on the
> SP-A/B/C loop, barcode, and device-fabric work already on `main`.

**Date:** 2026-05-29
**Status:** Approved (design carried over from prior session; enriched with correctness constraints)

---

## Problem

The waste half of the loop is built but **dormant**, because nothing ever puts a
*date* on a pantry item:

- `pantry_items.expires_at` exists and is read everywhere (`_row_to_dict`,
  `on_hand`, the per-row expiry chip at `Navigator.tsx:869`, the `expiringSoon`
  computed, and the ranking's `expiration_urgency` signal). But the only writers
  are the full-replace `PUT /navigator/pantry` and the one-time JSON migration.
  The single-item add path never sets it, and there is **no UI control** to set or
  change a date. So in practice every item has `expires_at = null`.
- `KitchenStore.mark_expired()` (`kitchen.py:398`) flips an item to `used_up` and
  logs an `expire` event — but it is wired to **no route** and called from no UI.
- `GET /navigator/waste` (`server.py:423`) → `waste_tally()` returns real numbers,
  but has **zero web callers**. The user never sees their own waste.
- The expiry "nudge" in the UI (`Navigator.tsx:203`) is a passive text strip with
  no actions.

Net effect: the dormant **0.20 `expiration_urgency`** ranking weight contributes
nothing, the dashboard's data is invisible, and "what expired?" has no honest
answer.

## Goal

Let the operator put dates on pantry items, act on items that have passed their
date, and see an honest tally of what got wasted — **without ever fabricating a
waste number.** Truthful numbers are the whole point of the dashboard, which is
why expiry is *manual-confirm* (a tap, never an automatic mark) and why waste
events must be double-count-proof.

## Non-goals (explicitly deferred)

- **Open Food Facts shelf-life inference** (auto-suggesting an expiry date from a
  scanned product). Deferred — keep this slice about manual entry + reporting.
- **Quantity math / fine-grained waste weight.** The truth model stays coarse
  (counts of discard/expire events), consistent with the rest of the loop.
- **Ranking changes.** No edits to `ranking.py`. The 0.20 `expiration_urgency`
  signal comes alive *for free* once dates exist (see "Emergent payoff").
- **Notifications / scheduled reminders.** In-app nudge only.

## Emergent payoff (verify-time, not a code change)

`post_recipes_from_pantry` builds its `Pantry` via `KitchenStore.on_hand()`, which
already carries `expires_at` into each `Ingredient` (`kitchen.py:271`). The ranker's
`_compute_expiration_urgency` reads `pantry.expiring_within(...)`. So the moment any
item has a date within the window, the 0.20 expiry weight starts re-ordering recipes
toward "use this before it spoils" — with no ranking change at all. We capture the
before/after ordering shift when driving the app on the Pi.

> Caveat for verification: with a *single* dated item, urgency is binary (1.0 for
> recipes that use it, 0.0 otherwise). Don't read too much into magnitude with one
> date set; just confirm the ordering moves and doesn't over-rotate.

---

## Design

### A. Store layer (`pantryatlas/store/kitchen.py`)

**A1. `set_expiry(canonical_name, expires_at) -> dict | None`**

```python
def set_expiry(self, canonical_name: str, expires_at: date | None,
               source: str = "manual") -> dict[str, Any] | None:
    """Set or clear an item's expiry date. Returns the updated item, or None
    if no such item. Stores the date as a pure YYYY-MM-DD string (or NULL)."""
```

- Stores `expires_at.isoformat()` (pure `YYYY-MM-DD`) or `NULL` when cleared.
  **Date-format discipline matters:** the web `parseLocalDate` splits on `-`
  (`signals.ts:569`) and would `NaN` on a full ISO datetime. A Pydantic `date`
  guarantees the right shape.
- Logs a `set_expiry` inventory event (detail `{"expires_at": "..."}` or
  `{"expires_at": null}`). This is **not** a waste event and never touches
  `waste_tally`.
- Returns `None` for an unknown item (→ 404 at the route, mirroring consume/restore).

**A2. Double-count guard — the invariant that protects the numbers**

> **Invariant:** a *waste* event (`discard` or `expire`) is logged only on the
> transition **into** `used_up`. An item that is already `used_up` cannot be wasted
> again. This is the manual-confirm guarantee enforced at the store layer, immune
> to a stale client, a double-tap, or a direct duplicate API call.

- `mark_expired()` (`kitchen.py:398`): add an early guard — if the item's current
  state is already `used_up`, return the item **without** updating or logging a
  second `expire` event. (Preserves the existing test, where `eggs` is `present` on
  first call.)
- `consume_item()` (`kitchen.py:295`): when `coarse_amount == "discarded"` **and**
  the item's prior state is already `used_up`, skip the `discard` log (no waste
  re-count). The non-waste `consume` log path is unchanged — double-logging a
  non-waste event can't corrupt waste numbers, so we leave it alone to minimize
  blast radius.

**A3. `waste_tally()` — additive `by_item`**

`waste_tally` currently returns `items: [name, name, …]` (flat, with dupes), and a
test pins that shape (`test_kitchen_store.py:241`). **Keep `items` exactly as-is**
and **add**:

```python
"by_item": [{"name": <str>, "count": <int>}, ...]  # desc by count, then name
```

Counts are over the same `discard` + `expire` rows already gathered in the window.
This feeds "most wasted" in the dashboard without breaking any existing assertion.

### B. API layer (`pantryatlas/navigator/server.py`)

**B1. `PUT /navigator/pantry/items/{name}/expiry`**

```python
class ExpiryIn(BaseModel):
    expires_at: date | None = None   # null clears the date

@app.put("/navigator/pantry/items/{name}/expiry")
def put_pantry_item_expiry(name: str, body: ExpiryIn) -> dict[str, Any]:
    item = _get_kitchen(app).set_expiry(name, body.expires_at)
    if item is None:
        raise HTTPException(status_code=404, detail=f"No pantry item '{name}'.")
    return item
```

**B2. `POST /navigator/pantry/items/{name}/expire`** → `mark_expired`

```python
@app.post("/navigator/pantry/items/{name}/expire")
def post_pantry_item_expire(name: str) -> dict[str, Any]:
    item = _get_kitchen(app).mark_expired(name)
    if item is None:
        raise HTTPException(status_code=404, detail=f"No pantry item '{name}'.")
    return item
```

(The existing `GET /navigator/waste?window_days=` route is unchanged; it now simply
returns the additional `by_item` key.)

### C. Web layer

**C1. `signals.ts`**

- `setExpiry(canonicalName, isoDate | null)` — `PUT …/expiry`, then `fetchPantry()`.
  Online only for v1 (no offline queue entry); on network error keep current state.
- `expireItem(canonicalName)` — `POST …/expire`, then `fetchPantry()`.
- `fetchWaste(windowDays = 30)` — `GET /navigator/waste`, store into a
  `waste = signal<WasteTally | null>(null)` plus a `wasteWindow = signal(30)`.
- New computed **`expired`** (sibling of `expiringSoon`):
  ```ts
  export const expired = computed(() =>
    pantry.value.filter((i) => {
      if (i.state === 'used_up') return false
      const d = daysUntilExpiry(i.expires_at)
      return d !== null && d < 0
    })
  )
  ```
  Excluding `used_up` is what makes an item leave the actionable nudge after the
  operator acts — the UI half of the double-count defense (the store half is A2).
- Pure helper `mostWasted(tally, n = 3)` returning the top-N `by_item` rows — unit-
  testable in the node vitest environment (no DOM needed).

**C2. `Navigator.tsx` — per-row expiry control**

Add a small date control to each `PantryCard` (near the expiry chip). A native
`<input type="date">` styled to the token system:
- Value = `item.expires_at ?? ''`.
- `onChange` → `setExpiry(item.canonical_name, value || null)` (empty clears).
- Accessible label: `Set expiry date for {canonical_name}`.

The existing read-only expiry chip stays (it shows the computed days/expired state).

**C3. `Navigator.tsx` — actionable manual-confirm nudge**

Keep the existing 0–3-day "cook these first" soft strip as-is. **Add a separate,
actionable nudge** that renders when `expired.value.length > 0`. For each expired
item, three buttons mapping to three distinct ledger outcomes:

| Button label | Action | Ledger `change_type` | Counts as waste? |
|---|---|---|---|
| Used it in time | `consumeItem(name, 'used_up')` | `consume` | No |
| Threw it out | `consumeItem(name, 'discarded')` | `discard` | Yes |
| Expired / spoiled | `expireItem(name)` | `expire` | Yes |

All three flip the item to `used_up`, so it drops out of `expired` and leaves the
nudge. Nothing is auto-marked — a number is only ever written by an operator tap.

**C4. `Navigator.tsx` — collapsible Waste dashboard**

A collapsible section (pattern mirrors the existing Kitchen-log / Devices sections),
toggled from the top bar. When open:
- Window selector: 7 / 30 / 90 days → sets `wasteWindow`, calls `fetchWaste`.
- Headline counts: total wasted, of which discarded vs expired.
- "Most wasted" list: top-N from `mostWasted(waste.value)`.
- Empty state when `total === 0` ("Nothing wasted in this window — nice.").

---

## Data flow

```
Set a date:    date input → setExpiry → PUT /items/{name}/expiry
                 → set_expiry (store YYYY-MM-DD + set_expiry event) → fetchPantry
                 → chip + expiringSoon/expired recompute
                 → (emergent) on_hand carries date → ranking expiration_urgency live

Act on expired: expired computed → actionable nudge
                 used-it  → consumeItem('used_up')  → consume event (not waste)
                 tossed   → consumeItem('discarded') → discard event (waste)
                 spoiled  → expireItem → mark_expired → expire event (waste)
                 → item becomes used_up → leaves nudge

See the tally:  open dashboard → fetchWaste(window) → GET /waste
                 → counts + by_item (most wasted)
```

## Error handling

- Unknown item on `PUT …/expiry` or `POST …/expire` → 404 (mirrors consume/restore).
- Clearing a date → `expires_at = null`; chip and computeds drop the item silently.
- Web fetch failures → keep current state (consistent with `fetchPantry` etc.).
- Double action on an expired item → store guard (A2) makes the second a no-op for
  waste; UI guard (`expired` excludes `used_up`) makes it unreachable from the nudge.

## Testing

**Python (`/usr/bin/python3 -m pytest`; the Pi venv lacks pytest):**

- `set_expiry`: sets a `YYYY-MM-DD` string; round-trips via `get_item`; clearing with
  `None` nulls it; unknown item → `None`; emits a `set_expiry` event that does **not**
  appear in `waste_tally`.
- `mark_expired` idempotency: call twice → exactly **one** `expire` event; second call
  returns the item unchanged. First call on a `present` item still logs (regression
  guard for the existing test).
- `consume_item('discarded')` idempotency: on a `present` item logs one `discard`;
  a second `discarded` call on the now-`used_up` item logs **no** additional discard.
- Ledger distinctness: used_up → `consume` (not in waste), discarded → `discard`,
  mark_expired → `expire`; `waste_tally` counts discard+expire only.
- `waste_tally` additive: `items` keeps its flat shape (existing test passes);
  `by_item` returns `{name, count}` sorted desc by count.
- Routes: `PUT …/expiry` happy path + 404; `POST …/expire` happy path + 404;
  `GET /waste` returns `by_item`.

**Web (vitest, node env — pure functions only):**

- `mostWasted(tally, n)`: returns top-N by count; handles empty/short lists.
- `expired` / `expiringSoon` partition: an item with `d < 0` is in `expired`, not
  `expiringSoon`; a `used_up` item is in neither.
- `daysUntilExpiry` returns an integer for a `YYYY-MM-DD` set via `set_expiry`
  (date-format discipline lock).

**Runtime verification (Pi, headless):** set a date on a real item → chip updates →
recipe ordering shifts (capture before/after) → expire an item → it leaves the nudge
and appears in the dashboard tally. Use a **temp** kitchen DB; never touch the real
`~/.pantryatlas`.

## Out-of-scope reminders for the implementer

- Do **not** edit `ranking.py`.
- Do **not** add OFF shelf-life inference.
- Subagents must use **specific `git add <paths>`**, never `git add -A` — the working
  tree has untracked parallel-work dirs (`web/src/ondevice/`, `ops/dev/`,
  `pinas-dev-node`, `.claude/`) that must not be swept into commits.
- Stop at **PR + CI green**; do not merge to `main` (operator merges).
