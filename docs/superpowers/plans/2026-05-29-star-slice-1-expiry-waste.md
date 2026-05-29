# Star Slice 1 — Expiry Input + Waste Dashboard Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Let the operator set/clear expiry dates on pantry items, act on expired items via a manual-confirm nudge, and see an honest waste tally — without ever fabricating a waste number.

**Architecture:** Three layers. (1) `KitchenStore` gains `set_expiry`, double-count guards on `mark_expired`/`consume_item`, and an additive `by_item` in `waste_tally`. (2) FastAPI gains `PUT …/expiry` + `POST …/expire` routes. (3) The Preact PWA gains expiry signals/helpers, a per-row date control, an actionable expired-item nudge, and a collapsible waste dashboard. No `ranking.py` changes — the dormant 0.20 `expiration_urgency` signal activates for free once dates exist.

**Tech Stack:** Python 3 + FastAPI + plain SQLite (`KitchenStore`); Preact + @preact/signals + Vite; pytest (run via `/usr/bin/python3 -m pytest`, NOT the Pi venv); vitest (node env).

**Critical conventions:**
- Run Python tests with `/usr/bin/python3 -m pytest` (the `.venv` is a uv-venv with no pytest). `ruff` is on PATH.
- Subagents MUST use specific `git add <paths>` — **never `git add -A`**.
- Do NOT edit `ranking.py`. Do NOT add OFF shelf-life inference.
- The **waste invariant**: a `discard`/`expire` event is logged only on the transition *into* `used_up`.

---

### Task 1: Store — `set_expiry`

**Files:**
- Modify: `pantryatlas/store/kitchen.py` (add method after `mark_expired`, ~line 409)
- Test: `tests/navigator/test_kitchen_store.py`

- [ ] **Step 1: Write the failing tests**

Append to `tests/navigator/test_kitchen_store.py`:

```python
def test_set_expiry_sets_and_clears(tmp_path):
    from datetime import date
    store = KitchenStore(tmp_path / "kitchen.db")
    store.add_item(Ing(canonical_name="milk", raw_text="milk"))

    # Set a date — stored as pure YYYY-MM-DD
    item = store.set_expiry("milk", date(2099, 1, 2))
    assert item is not None
    assert item["expires_at"] == "2099-01-02"

    # Clear the date — expires_at drops out of the dict
    item = store.set_expiry("milk", None)
    assert item is not None
    assert "expires_at" not in item


def test_set_expiry_unknown_item_returns_none(tmp_path):
    from datetime import date
    store = KitchenStore(tmp_path / "kitchen.db")
    assert store.set_expiry("ghost", date(2099, 1, 1)) is None


def test_set_expiry_event_is_not_waste(tmp_path):
    from datetime import date
    store = KitchenStore(tmp_path / "kitchen.db")
    store.add_item(Ing(canonical_name="milk", raw_text="milk"))
    store.set_expiry("milk", date(2099, 1, 1))
    tally = store.waste_tally(window_days=30)
    assert tally["total"] == 0  # set_expiry must never count as waste
```

- [ ] **Step 2: Run tests to verify they fail**

Run: `cd /home/craigm26/pantryatlas && /usr/bin/python3 -m pytest tests/navigator/test_kitchen_store.py -k set_expiry -v`
Expected: FAIL with `AttributeError: 'KitchenStore' object has no attribute 'set_expiry'`

- [ ] **Step 3: Implement `set_expiry`**

Insert immediately after the `mark_expired` method (after its `return self.get_item(...)`, ~line 409) in `pantryatlas/store/kitchen.py`:

```python
    def set_expiry(self, canonical_name: str, expires_at: date | None,
                   source: str = "manual") -> dict[str, Any] | None:
        """Set or clear an item's expiry date.

        Stored as a pure ``YYYY-MM-DD`` string (or NULL when cleared) — the web
        ``parseLocalDate`` splits on ``-`` and would NaN on a full ISO datetime.
        Logs a ``set_expiry`` event, which is NOT a waste event.
        """
        iso = expires_at.isoformat() if expires_at is not None else None
        with self._lock:
            cur = self._conn.execute(
                "UPDATE pantry_items SET expires_at=?, updated_at=? WHERE canonical_name=?",
                (iso, _now_iso(), canonical_name),
            )
            if not cur.rowcount:
                return None
            self._log_event(canonical_name, "set_expiry", source, {"expires_at": iso})
            self._conn.commit()
            return self.get_item(canonical_name)
```

- [ ] **Step 4: Run tests to verify they pass**

Run: `cd /home/craigm26/pantryatlas && /usr/bin/python3 -m pytest tests/navigator/test_kitchen_store.py -k set_expiry -v`
Expected: PASS (3 tests)

- [ ] **Step 5: Commit**

```bash
git add pantryatlas/store/kitchen.py tests/navigator/test_kitchen_store.py
git commit -m "feat(store): set_expiry to set/clear pantry item expiry date"
```

---

### Task 2: Store — double-count guards (the waste invariant)

**Files:**
- Modify: `pantryatlas/store/kitchen.py` (`mark_expired` ~line 398, `consume_item` ~line 295)
- Test: `tests/navigator/test_kitchen_store.py`

- [ ] **Step 1: Write the failing tests**

Append to `tests/navigator/test_kitchen_store.py`:

```python
def test_mark_expired_is_idempotent(tmp_path):
    store = KitchenStore(tmp_path / "kitchen.db")
    store.add_item(Ing(canonical_name="eggs", raw_text="eggs"))
    store.mark_expired("eggs")   # first: present -> used_up, logs expire
    store.mark_expired("eggs")   # second: already used_up -> no-op, no log
    tally = store.waste_tally(window_days=30)
    assert tally["expired"] == 1, "a second mark_expired must not double-count"
    assert tally["total"] == 1


def test_discard_does_not_double_count_when_already_used_up(tmp_path):
    store = KitchenStore(tmp_path / "kitchen.db")
    store.add_item(Ing(canonical_name="milk", raw_text="milk"))
    store.consume_item("milk", "discarded")  # present -> used_up, logs discard
    store.consume_item("milk", "discarded")  # already used_up -> no extra discard
    tally = store.waste_tally(window_days=30)
    assert tally["discarded"] == 1, "a second discard on a used_up item must not double-count"
    assert tally["total"] == 1
```

- [ ] **Step 2: Run tests to verify they fail**

Run: `cd /home/craigm26/pantryatlas && /usr/bin/python3 -m pytest tests/navigator/test_kitchen_store.py -k "idempotent or double_count" -v`
Expected: FAIL — `expired == 2` / `discarded == 2` (current code logs unconditionally)

- [ ] **Step 3a: Guard `mark_expired`**

Replace the body of `mark_expired` (currently ~lines 398-409) with:

```python
    def mark_expired(self, canonical_name: str, source: str = "manual") -> dict[str, Any] | None:
        with self._lock:
            row = self._conn.execute(
                "SELECT state FROM pantry_items WHERE canonical_name=?", (canonical_name,)
            ).fetchone()
            if row is None:
                return None
            if row[0] == "used_up":
                # Already off-hand — don't fabricate a second expire event.
                return self.get_item(canonical_name)
            self._conn.execute(
                "UPDATE pantry_items SET state='used_up', confidence=0.0, updated_at=? "
                "WHERE canonical_name=?",
                (_now_iso(), canonical_name),
            )
            self._log_event(canonical_name, "expire", source)
            self._conn.commit()
            return self.get_item(canonical_name)
```

- [ ] **Step 3b: Guard the discard log in `consume_item`**

In `consume_item` (~lines 295-313), the `row` variable already holds the prior
state (`row[0]`). Replace the logging block:

```python
            change_type = "discard" if coarse_amount == "discarded" else "consume"
            self._log_event(canonical_name, change_type, source,
                            {"coarse_amount": coarse_amount, "prev_state": row[0]})
```

with:

```python
            change_type = "discard" if coarse_amount == "discarded" else "consume"
            # Waste invariant: don't double-count a discard on an already-used_up item.
            if not (change_type == "discard" and row[0] == "used_up"):
                self._log_event(canonical_name, change_type, source,
                                {"coarse_amount": coarse_amount, "prev_state": row[0]})
```

- [ ] **Step 4: Run the full kitchen-store test file (regression + new)**

Run: `cd /home/craigm26/pantryatlas && /usr/bin/python3 -m pytest tests/navigator/test_kitchen_store.py -v`
Expected: PASS — new idempotency tests pass AND the existing
`test_waste_tally_counts_discards_and_expires` / `test_cook_event_discarded_counts_as_waste` still pass.

- [ ] **Step 5: Commit**

```bash
git add pantryatlas/store/kitchen.py tests/navigator/test_kitchen_store.py
git commit -m "fix(store): never double-count waste — log discard/expire only on transition into used_up"
```

---

### Task 3: Store — additive `by_item` in `waste_tally`

**Files:**
- Modify: `pantryatlas/store/kitchen.py` (`waste_tally` ~line 506)
- Test: `tests/navigator/test_kitchen_store.py`

- [ ] **Step 1: Write the failing test**

Append to `tests/navigator/test_kitchen_store.py`:

```python
def test_waste_tally_by_item_counts_sorted(tmp_path):
    store = KitchenStore(tmp_path / "kitchen.db")
    for n in ("milk", "eggs"):
        store.add_item(Ing(canonical_name=n, raw_text=n))
    store.consume_item("milk", "discarded")  # milk x1
    store.mark_expired("eggs")               # eggs x1
    store.add_item(Ing(canonical_name="milk", raw_text="milk"))  # re-add milk
    store.consume_item("milk", "discarded")  # milk x2
    tally = store.waste_tally(window_days=30)
    # items keeps its flat shape (backward-compatible)
    assert sorted(tally["items"]) == ["eggs", "milk", "milk"]
    # by_item: most-wasted first, then name
    assert tally["by_item"] == [{"name": "milk", "count": 2}, {"name": "eggs", "count": 1}]
```

- [ ] **Step 2: Run test to verify it fails**

Run: `cd /home/craigm26/pantryatlas && /usr/bin/python3 -m pytest tests/navigator/test_kitchen_store.py -k by_item -v`
Expected: FAIL with `KeyError: 'by_item'`

- [ ] **Step 3: Add `by_item` to `waste_tally`**

Replace the `return {...}` at the end of `waste_tally` (~lines 515-521) with:

```python
        counts: dict[str, int] = {}
        for r in rows:
            counts[r[0]] = counts.get(r[0], 0) + 1
        by_item = [
            {"name": n, "count": c}
            for n, c in sorted(counts.items(), key=lambda kv: (-kv[1], kv[0]))
        ]
        return {
            "window_days": window_days,
            "discarded": discarded,
            "expired": expired,
            "total": discarded + expired,
            "items": [r[0] for r in rows],
            "by_item": by_item,
        }
```

- [ ] **Step 4: Run test to verify it passes**

Run: `cd /home/craigm26/pantryatlas && /usr/bin/python3 -m pytest tests/navigator/test_kitchen_store.py -k by_item -v`
Expected: PASS

- [ ] **Step 5: Commit**

```bash
git add pantryatlas/store/kitchen.py tests/navigator/test_kitchen_store.py
git commit -m "feat(store): waste_tally returns additive by_item most-wasted counts"
```

---

### Task 4: API — expiry + expire routes

**Files:**
- Modify: `pantryatlas/navigator/server.py` (add `ExpiryIn` model near `ConsumeIn` ~line 140; add routes after the consume/restore routes ~line 396)
- Test: `tests/navigator/test_server.py`

- [ ] **Step 1: Write the failing tests**

The file already has a `client` fixture (`test_server.py:129`) that builds the app via `create_app(..., kitchen=KitchenStore(<tmp>/kitchen.db))` and returns a `TestClient`. Use it directly. Append these tests verbatim:

```python
def test_put_item_expiry_sets_date(client):
    client.post("/navigator/pantry/items", json={"raw_text": "milk", "canonical_name": "milk"})
    res = client.put("/navigator/pantry/items/milk/expiry", json={"expires_at": "2099-01-02"})
    assert res.status_code == 200
    assert res.json()["expires_at"] == "2099-01-02"


def test_put_item_expiry_clears_with_null(client):
    client.post("/navigator/pantry/items", json={"raw_text": "milk", "canonical_name": "milk"})
    client.put("/navigator/pantry/items/milk/expiry", json={"expires_at": "2099-01-02"})
    res = client.put("/navigator/pantry/items/milk/expiry", json={"expires_at": None})
    assert res.status_code == 200
    assert "expires_at" not in res.json()


def test_put_item_expiry_unknown_404(client):
    res = client.put("/navigator/pantry/items/ghost/expiry", json={"expires_at": "2099-01-02"})
    assert res.status_code == 404


def test_post_item_expire_marks_used_up(client):
    client.post("/navigator/pantry/items", json={"raw_text": "eggs", "canonical_name": "eggs"})
    res = client.post("/navigator/pantry/items/eggs/expire")
    assert res.status_code == 200
    assert res.json()["state"] == "used_up"
    waste = client.get("/navigator/waste").json()
    assert waste["expired"] == 1
    assert {"name": "eggs", "count": 1} in waste["by_item"]


def test_post_item_expire_unknown_404(client):
    res = client.post("/navigator/pantry/items/ghost/expire")
    assert res.status_code == 404
```

- [ ] **Step 2: Run tests to verify they fail**

Run: `cd /home/craigm26/pantryatlas && /usr/bin/python3 -m pytest tests/navigator/test_server.py -k "expiry or expire" -v`
Expected: FAIL with 404/405 (routes not defined) — NOT a fixture error. If the `client` fixture name differs, fix the test to match the file first.

- [ ] **Step 3a: Add the `ExpiryIn` model**

Insert after `ConsumeIn` (~line 140) in `pantryatlas/navigator/server.py`:

```python
class ExpiryIn(BaseModel):
    """Body for PUT /navigator/pantry/items/{name}/expiry."""

    expires_at: date | None = None  # null clears the date
```

(`date` is already imported — confirm `from datetime import date` is present near the top; `IngredientIn.expires_at: date` already uses it.)

- [ ] **Step 3b: Add the routes**

Insert after the `restore_pantry_item` route (~line 396, before the "Cook events" section) in the `create_app` body:

```python
    @app.put("/navigator/pantry/items/{name}/expiry")
    def put_pantry_item_expiry(name: str, body: ExpiryIn) -> dict[str, Any]:
        item = _get_kitchen(app).set_expiry(name, body.expires_at)
        if item is None:
            raise HTTPException(status_code=404, detail=f"No pantry item '{name}'.")
        return item

    @app.post("/navigator/pantry/items/{name}/expire")
    def post_pantry_item_expire(name: str) -> dict[str, Any]:
        item = _get_kitchen(app).mark_expired(name)
        if item is None:
            raise HTTPException(status_code=404, detail=f"No pantry item '{name}'.")
        return item
```

- [ ] **Step 4: Run tests to verify they pass**

Run: `cd /home/craigm26/pantryatlas && /usr/bin/python3 -m pytest tests/navigator/test_server.py -k "expiry or expire" -v`
Expected: PASS (5 tests)

- [ ] **Step 5: Commit**

```bash
git add pantryatlas/navigator/server.py tests/navigator/test_server.py
git commit -m "feat(api): PUT item expiry + POST item expire routes"
```

---

### Task 5: Web — expiry signals, helpers, computed, and unit tests

**Files:**
- Modify: `web/src/signals.ts`
- Create: `web/src/signals.expiry.test.ts`

- [ ] **Step 1: Write the failing tests**

Create `web/src/signals.expiry.test.ts`:

```ts
import { describe, it, expect, beforeEach } from 'vitest'
import {
  mostWasted,
  expired,
  expiringSoon,
  daysUntilExpiry,
  pantry,
  type WasteTally,
  type PantryItem,
} from './signals'

function isoFromOffset(days: number): string {
  const d = new Date()
  d.setHours(0, 0, 0, 0)
  d.setDate(d.getDate() + days)
  const y = d.getFullYear()
  const m = String(d.getMonth() + 1).padStart(2, '0')
  const day = String(d.getDate()).padStart(2, '0')
  return `${y}-${m}-${day}`
}

describe('mostWasted', () => {
  const tally: WasteTally = {
    window_days: 30, discarded: 3, expired: 1, total: 4,
    items: ['milk', 'milk', 'milk', 'eggs'],
    by_item: [{ name: 'milk', count: 3 }, { name: 'eggs', count: 1 }],
  }
  it('returns the top-N by_item rows', () => {
    expect(mostWasted(tally, 1)).toEqual([{ name: 'milk', count: 3 }])
  })
  it('handles null/empty safely', () => {
    expect(mostWasted(null)).toEqual([])
    expect(mostWasted({ ...tally, by_item: [] })).toEqual([])
  })
})

describe('expired / expiringSoon partition', () => {
  beforeEach(() => { pantry.value = [] })
  it('puts a past-date item in expired, not expiringSoon', () => {
    const item: PantryItem = { canonical_name: 'milk', raw_text: 'milk', expires_at: isoFromOffset(-2) }
    pantry.value = [item]
    expect(expired.value.map(i => i.canonical_name)).toEqual(['milk'])
    expect(expiringSoon.value.map(i => i.canonical_name)).toEqual([])
  })
  it('puts a soon item in expiringSoon, not expired', () => {
    pantry.value = [{ canonical_name: 'bread', raw_text: 'bread', expires_at: isoFromOffset(1) }]
    expect(expiringSoon.value.map(i => i.canonical_name)).toEqual(['bread'])
    expect(expired.value.map(i => i.canonical_name)).toEqual([])
  })
  it('excludes used_up items from both', () => {
    pantry.value = [{ canonical_name: 'milk', raw_text: 'milk', expires_at: isoFromOffset(-2), state: 'used_up' }]
    expect(expired.value).toEqual([])
    expect(expiringSoon.value).toEqual([])
  })
  it('daysUntilExpiry returns an integer for a YYYY-MM-DD date', () => {
    expect(daysUntilExpiry(isoFromOffset(-2))).toBe(-2)
  })
})
```

- [ ] **Step 2: Run tests to verify they fail**

Run: `cd /home/craigm26/pantryatlas/web && npx vitest run src/signals.expiry.test.ts`
Expected: FAIL — `mostWasted`, `expired`, `WasteTally` are not exported.

- [ ] **Step 3a: Add the `WasteTally` interface + waste signals**

In `web/src/signals.ts`, after the `CookEvent` interface (~line 39) add:

```ts
export interface WasteTally {
  window_days: number
  discarded: number
  expired: number
  total: number
  items: string[]
  by_item: { name: string; count: number }[]
}
```

After the `meals` signal / `fetchMeals` block and the existing `get_waste` consumer area (after `cookRecipe`/`restoreItem`, ~line 219) add:

```ts
// ---------------------------------------------------------------------------
// Expiry + waste
// ---------------------------------------------------------------------------

export const waste = signal<WasteTally | null>(null)
export const wasteWindow = signal<number>(30)
export const wasteOpen = signal<boolean>(false)

/** Set or clear an item's expiry date (ISO YYYY-MM-DD, or null to clear). */
export async function setExpiry(canonicalName: string, isoDate: string | null) {
  try {
    const res = await fetch(`/navigator/pantry/items/${encodeURIComponent(canonicalName)}/expiry`, {
      method: 'PUT',
      headers: { 'Content-Type': 'application/json' },
      body: JSON.stringify({ expires_at: isoDate }),
    })
    if (res.ok) await fetchPantry()
  } catch {
    // ignore — keep current state
  }
}

/** Manual-confirm: log that an item expired/spoiled (flips it to used_up). */
export async function expireItem(canonicalName: string) {
  try {
    const res = await fetch(`/navigator/pantry/items/${encodeURIComponent(canonicalName)}/expire`, {
      method: 'POST',
    })
    if (res.ok) await fetchPantry()
  } catch {
    // ignore
  }
}

export async function fetchWaste(windowDays: number = 30) {
  try {
    const res = await fetch(`/navigator/waste?window_days=${windowDays}`)
    if (res.ok) waste.value = await res.json()
  } catch {
    // keep existing
  }
}

/** Top-N most-wasted items from a tally (pure; safe on null/empty). */
export function mostWasted(tally: WasteTally | null, n: number = 3): { name: string; count: number }[] {
  if (!tally || !tally.by_item) return []
  return tally.by_item.slice(0, n)
}
```

- [ ] **Step 3b: Add the `expired` computed**

Immediately after the existing `expiringSoon` computed (~line 391) add:

```ts
export const expired = computed(() =>
  pantry.value.filter((i) => {
    if (i.state === 'used_up') return false
    const d = daysUntilExpiry(i.expires_at)
    return d !== null && d < 0
  })
)
```

- [ ] **Step 4: Run tests + typecheck to verify pass**

Run: `cd /home/craigm26/pantryatlas/web && npx vitest run src/signals.expiry.test.ts && npx tsc --noEmit`
Expected: PASS (vitest green) and tsc clean.

- [ ] **Step 5: Commit**

```bash
git add web/src/signals.ts web/src/signals.expiry.test.ts
git commit -m "feat(web): expiry/waste signals, expired computed, mostWasted helper"
```

---

### Task 6: Web — per-row expiry date control

**Files:**
- Modify: `web/src/pages/Navigator.tsx` (`PantryCard` ~line 868; import `setExpiry` from signals)

- [ ] **Step 1: Add the import**

In the `import { … } from '../signals'` block, add `setExpiry,` alongside the existing expiry imports (`daysUntilExpiry`, `expiringSoon`).

- [ ] **Step 2: Add the date control to `PantryCard`**

In the trailing controls `div` of `PantryCard` (the `div` at ~line 988 holding `PantryRowActions`, the pending chip, the expiry chip, and delete), insert a native date input BEFORE the expiry chip. The input shows/edits the current date; empty value clears it. Do not render it for `used_up` items (they are off-hand):

```tsx
        {/* Expiry date control — set/clear; native date picker */}
        {item.state !== 'used_up' && (
          <input
            type="date"
            value={item.expires_at ?? ''}
            data-expiry-input={item.canonical_name}
            aria-label={`Set expiry date for ${item.canonical_name}`}
            onChange={(e) =>
              setExpiry(item.canonical_name, (e.currentTarget as HTMLInputElement).value || null)
            }
            style={{
              minHeight: '36px',
              padding: '2px 6px',
              borderRadius: 'var(--md-sys-shape-corner-medium)',
              border: '1px solid var(--md-sys-color-outline-variant)',
              background: 'transparent',
              color: 'var(--md-sys-color-on-surface-variant)',
              fontFamily: 'var(--font)',
              fontSize: 'var(--md-sys-typescale-label-small-size)',
              colorScheme: 'light dark',
            }}
          />
        )}
```

- [ ] **Step 3: Build to verify it compiles**

Run: `cd /home/craigm26/pantryatlas/web && npx tsc --noEmit && npm run build`
Expected: tsc clean, vite build succeeds.

- [ ] **Step 4: Commit**

```bash
git add web/src/pages/Navigator.tsx
git commit -m "feat(web): per-row expiry date control on pantry cards"
```

---

### Task 7: Web — actionable manual-confirm expired nudge

**Files:**
- Modify: `web/src/pages/Navigator.tsx` (import `expired`, `expireItem`; add nudge after the existing expiry strip ~line 218)

- [ ] **Step 1: Add imports**

Add `expired,` and `expireItem,` to the `from '../signals'` import block (alongside `expiringSoon`, `consumeItem`).

- [ ] **Step 2: Add the actionable nudge**

In `Navigator()`'s JSX, immediately AFTER the existing `{expiringSoon.value.length > 0 && (…)}` block (closes ~line 218) and BEFORE `<RecipesSection />`, add:

```tsx
          {/* Actionable manual-confirm nudge for items already past their date */}
          {expired.value.length > 0 && (
            <div
              data-expired-nudge="true"
              style={{
                padding: '12px 16px',
                borderRadius: 'var(--md-sys-shape-corner-large)',
                background: 'var(--md-sys-color-error-container)',
                color: 'var(--md-sys-color-on-error-container)',
                fontFamily: 'var(--font)',
                fontSize: 'var(--md-sys-typescale-body-medium-size)',
                marginBottom: '12px',
                display: 'flex',
                flexDirection: 'column',
                gap: '8px',
              }}
            >
              <span>Past expiry — what happened to these?</span>
              <ul style={{ listStyle: 'none', display: 'flex', flexDirection: 'column', gap: '6px' }}>
                {expired.value.map((i) => (
                  <li
                    key={i.canonical_name}
                    style={{ display: 'flex', alignItems: 'center', gap: '8px', flexWrap: 'wrap' }}
                  >
                    <span style={{ fontWeight: 600 }}>{i.canonical_name}</span>
                    <button
                      type="button"
                      data-expired-action={`${i.canonical_name}:used`}
                      onClick={() => consumeItem(i.canonical_name, 'used_up')}
                      style={expiredBtnStyle}
                    >
                      Used it in time
                    </button>
                    <button
                      type="button"
                      data-expired-action={`${i.canonical_name}:tossed`}
                      onClick={() => consumeItem(i.canonical_name, 'discarded')}
                      style={expiredBtnStyle}
                    >
                      Threw it out
                    </button>
                    <button
                      type="button"
                      data-expired-action={`${i.canonical_name}:expired`}
                      onClick={() => expireItem(i.canonical_name)}
                      style={expiredBtnStyle}
                    >
                      Expired / spoiled
                    </button>
                  </li>
                ))}
              </ul>
            </div>
          )}
```

Add this shared style constant at module scope (near `showLog` ~line 48):

```tsx
const expiredBtnStyle = {
  minHeight: '36px',
  padding: '4px 12px',
  borderRadius: 'var(--md-sys-shape-corner-full)',
  background: 'var(--md-sys-color-surface)',
  border: '1px solid var(--md-sys-color-outline-variant)',
  color: 'var(--md-sys-color-on-surface)',
  fontFamily: 'var(--font)',
  fontSize: 'var(--md-sys-typescale-label-medium-size)',
  cursor: 'pointer',
  whiteSpace: 'nowrap' as const,
}
```

- [ ] **Step 3: Build to verify it compiles**

Run: `cd /home/craigm26/pantryatlas/web && npx tsc --noEmit && npm run build`
Expected: tsc clean, build succeeds.

- [ ] **Step 4: Commit**

```bash
git add web/src/pages/Navigator.tsx
git commit -m "feat(web): actionable manual-confirm nudge for expired items"
```

---

### Task 8: Web — collapsible waste dashboard + top-bar toggle

**Files:**
- Modify: `web/src/pages/Navigator.tsx` (import waste signals; add a `WasteDashboard` component; add a section toggled by `wasteOpen`; add a top-bar toggle button)

- [ ] **Step 1: Add imports**

Add `waste,`, `wasteWindow,`, `wasteOpen,`, `fetchWaste,`, `mostWasted,` to the `from '../signals'` import block.

- [ ] **Step 2: Add a top-bar toggle button**

In `TopBar()`, next to the existing "Log"/"Devices" toggle buttons (~lines 347-380), add a "Waste" toggle following the same pattern:

```tsx
      <button
        type="button"
        onClick={() => { wasteOpen.value = !wasteOpen.value }}
        aria-label={wasteOpen.value ? 'Hide waste dashboard' : 'Show waste dashboard'}
        style={{
          minHeight: '40px',
          padding: '4px 12px',
          borderRadius: 'var(--md-sys-shape-corner-full)',
          background: wasteOpen.value ? 'var(--md-sys-color-primary-container)' : 'transparent',
          border: 'none',
          cursor: 'pointer',
          fontFamily: 'var(--font)',
          fontSize: 'var(--md-sys-typescale-label-medium-size)',
          color: wasteOpen.value
            ? 'var(--md-sys-color-on-primary-container)'
            : 'var(--md-sys-color-on-surface-variant)',
        }}
      >
        Waste
      </button>
```

- [ ] **Step 3: Add the `WasteDashboard` component**

Add at module scope (e.g., after `MealLog` usage / near other section components):

```tsx
function WasteDashboard() {
  useEffect(() => { void fetchWaste(wasteWindow.value) }, [])
  const t = waste.value
  const top = mostWasted(t, 5)
  const setWindow = (days: number) => { wasteWindow.value = days; void fetchWaste(days) }
  const windows = [7, 30, 90]
  return (
    <div data-waste-dashboard="true" style={{ fontFamily: 'var(--font)', color: 'var(--md-sys-color-on-surface)' }}>
      <div style={{ display: 'flex', gap: '8px', marginBottom: '12px' }}>
        {windows.map((d) => (
          <button
            key={d}
            type="button"
            data-waste-window={d}
            onClick={() => setWindow(d)}
            style={{
              minHeight: '36px', padding: '4px 12px',
              borderRadius: 'var(--md-sys-shape-corner-full)',
              border: '1px solid var(--md-sys-color-outline-variant)',
              background: wasteWindow.value === d
                ? 'var(--md-sys-color-primary-container)' : 'transparent',
              color: wasteWindow.value === d
                ? 'var(--md-sys-color-on-primary-container)'
                : 'var(--md-sys-color-on-surface-variant)',
              cursor: 'pointer',
              fontFamily: 'var(--font)',
              fontSize: 'var(--md-sys-typescale-label-medium-size)',
            }}
          >
            {d}d
          </button>
        ))}
      </div>
      {t && t.total === 0 && (
        <p style={{ color: 'var(--md-sys-color-on-surface-variant)' }}>
          Nothing wasted in this window — nice.
        </p>
      )}
      {t && t.total > 0 && (
        <div>
          <p style={{ marginBottom: '8px' }}>
            <strong>{t.total}</strong> wasted · {t.discarded} thrown out · {t.expired} expired
          </p>
          <ul style={{ listStyle: 'none', display: 'flex', flexDirection: 'column', gap: '4px' }}>
            {top.map((row) => (
              <li key={row.name} data-waste-item={row.name}
                  style={{ display: 'flex', justifyContent: 'space-between',
                           color: 'var(--md-sys-color-on-surface-variant)' }}>
                <span>{row.name}</span><span>×{row.count}</span>
              </li>
            ))}
          </ul>
        </div>
      )}
    </div>
  )
}
```

- [ ] **Step 4: Render the collapsible section**

In `Navigator()`, alongside the other collapsible sections (after the Devices section block ~line 257), add:

```tsx
          {/* Section E3: Waste dashboard — collapsible (toggled via "Waste" in top bar) */}
          {wasteOpen.value && (
            <section aria-label="Waste dashboard" style={{ marginTop: '32px' }}>
              <p
                style={{
                  fontFamily: 'var(--font)',
                  fontSize: 'var(--md-sys-typescale-label-medium-size)',
                  fontWeight: 'var(--md-sys-typescale-label-medium-weight)',
                  color: 'var(--md-sys-color-on-surface-variant)',
                  marginBottom: '12px',
                }}
              >
                What you wasted
              </p>
              <WasteDashboard />
            </section>
          )}
```

- [ ] **Step 5: Build to verify it compiles**

Run: `cd /home/craigm26/pantryatlas/web && npx tsc --noEmit && npm run build`
Expected: tsc clean, build succeeds.

- [ ] **Step 6: Commit**

```bash
git add web/src/pages/Navigator.tsx
git commit -m "feat(web): collapsible waste dashboard with window selector + most-wasted"
```

---

### Final verification (after all tasks)

- [ ] **Full Python suite + lint:**
  `cd /home/craigm26/pantryatlas && /usr/bin/python3 -m pytest tests/ -q && ruff check pantryatlas/ tests/`
  Expected: all green; ruff clean.

- [ ] **Full web suite + build:**
  `cd /home/craigm26/pantryatlas/web && npx vitest run && npx tsc --noEmit && npm run build`
  Expected: all vitest green, tsc clean, build succeeds.

- [ ] **Runtime verification (Pi, headless, TEMP DB — never touch real `~/.pantryatlas`):**
  Boot the server against a temp kitchen DB, drive it through the loop:
  1. Add an item, `PUT …/expiry` a near-future date → GET pantry shows the chip; capture `from-pantry` ordering BEFORE and AFTER a date is set on an item a recipe uses (the dormant 0.20 `expiration_urgency` payoff — confirm ordering shifts, not over-rotates).
  2. `PUT …/expiry` a PAST date → item appears in `expired`; drive the nudge actions; confirm the item leaves the nudge and `GET /waste` reflects exactly one event (no double count on repeat).
  3. Open the dashboard, switch 7/30/90 windows, confirm counts + most-wasted.

- [ ] **Finish:** use superpowers:finishing-a-development-branch → **Option 2 (push + PR)**. Stop at PR + CI green; do NOT merge (operator merges).
