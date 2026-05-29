# Design — SP-A: Loop Foundation (first slice)

- **Date:** 2026-05-28
- **Status:** Approved (brainstorming) — ready for implementation planning
- **Parent vision:** [`2026-05-28-kitchen-mesh-vision-design.md`](./2026-05-28-kitchen-mesh-vision-design.md)
- **Scope:** The first buildable, fully-verifiable-on-the-Pi-today slice. Lands the shared data model
  the whole mesh needs and closes the loop **without any cameras, devices, barcodes, or mDNS.**

## Goal

Make the waste loop real with what we have today: evolve the pantry into a durable, concurrent-safe
store; add a **cook event** that fuses an auto-decrement with a dated cook-log; surface expiry /
running-low nudges and light waste analytics. After SP-A, a user can add items, get recipes (existing),
tap **"I cooked this"**, watch the pantry draw down, and see what they cooked and what they wasted.

## In scope

- Migrate the pantry off `pantry.json` into SQLite, with new per-item state/provenance fields.
- Append-only `inventory_events` ledger and `cook_events` (meal log) tables.
- `POST /navigator/cook` — atomic cook-event + soft-decrement.
- Coarse consume actions on pantry items ("used up / half left / threw away").
- `GET /navigator/meals` (timeline) and `GET /navigator/waste` (tally).
- Expiry / running-low signals feeding the existing recipe ranking + small UI nudges.
- Frontend: "I cooked this" + servings on a recipe card; a Kitchen-log timeline view; coarse consume
  controls; expiry nudges.

## Out of scope (later sub-projects)

Cameras, barcode/Open Food Facts, host vision, mDNS/discovery, the device fabric, sensor nodes, the
Coral, plate-photo, multi-device reconciliation, precise quantity accounting. The fields we add are
**forward-compatible** with those (e.g. `source`, `confidence`, `last_observed_at`) but SP-A only ever
writes `source = "manual" | "cook"`.

## Data model

New DB `~/.pantryatlas/kitchen.db` — **plain SQLite tables, no `sqlite-vec`**, so they run on this Pi's
Python 3.11 (which lacks `enable_load_extension`). Kept separate from the static `recipes.db`.

```sql
CREATE TABLE pantry_items (
  canonical_name    TEXT PRIMARY KEY,
  raw_text          TEXT NOT NULL,
  quantity_amount   REAL,
  quantity_unit     TEXT,
  expires_at        TEXT,                       -- ISO date
  state             TEXT NOT NULL DEFAULT 'present',  -- present | low | used_up
  confidence        REAL NOT NULL DEFAULT 1.0,        -- 0..1; cook lowers, observation raises
  last_observed_at  TEXT NOT NULL,              -- ISO datetime
  source            TEXT NOT NULL DEFAULT 'manual',   -- manual | cook (later: barcode | vision:<id>)
  added_at          TEXT NOT NULL,
  updated_at        TEXT NOT NULL
);

CREATE TABLE inventory_events (
  id              INTEGER PRIMARY KEY AUTOINCREMENT,
  ts              TEXT NOT NULL,
  canonical_name  TEXT NOT NULL,
  change_type     TEXT NOT NULL,   -- add | observe | consume | discard | expire | adjust
  detail_json     TEXT,            -- optional: {coarse_amount, prev_state, ...}
  source          TEXT NOT NULL,
  device_id       TEXT             -- NULL in SP-A; reserved for the mesh
);

CREATE TABLE cook_events (
  id            INTEGER PRIMARY KEY AUTOINCREMENT,
  recipe_id     TEXT,              -- NULL for off-app manual logs
  dish_name     TEXT NOT NULL,
  servings      REAL,
  cooked_at     TEXT NOT NULL,
  photo_path    TEXT,
  rating        INTEGER,           -- 1..5, optional
  notes         TEXT,
  consumed_json TEXT,              -- JSON [{canonical_name, coarse_amount}]
  source        TEXT NOT NULL      -- tap-to-cook | manual  (later: plate-photo)
);
```

### Migration (one-time, idempotent, non-destructive)

On store init, if `pantry_items` is empty and `pantry.json` exists, import every item:
`state='present'`, `confidence=1.0`, `last_observed_at = added_at = updated_at = now`,
`source='manual'`, preserving `quantity`/`expires_at`. **Rename `pantry.json` → `pantry.json.imported`
(do not delete)** so the operator keeps a backup and re-init is idempotent. Log an `add` inventory
event per imported item with `source='migration'`.

### Soft-decrement algorithm (the blend, coarse)

A `consume` with a `coarse_amount` maps to a state/confidence transition (never exact quantity math):

| coarse_amount | state transition | confidence | ledger event |
|---|---|---|---|
| `half` | `present → low` | × 0.5 | `consume` |
| `used_up` | `* → used_up` | 0.0 | `consume` |
| `discarded` | `* → used_up` | 0.0 | `discard` (counts as waste) |
| tap-to-cook default (per ingredient) | one notch down (`present→low`, `low→used_up`) | × 0.5 | `consume` |

`used_up` items stay in the table (the ledger needs the history) but are **excluded from the "on-hand"
set** used for recipe matching; the pantry view shows them dimmed with a one-tap "still have it" to
restore (`state='present'`, `confidence=1.0`, `observe` event). A future camera rescan reconciles by
writing `observe` events — the same restore path.

## API (extends `pantryatlas/navigator/server.py`)

Existing pantry routes are **repointed from `pantry.json` to the SQLite store** (same paths, same
request/response shapes plus the new optional fields):

- `GET /navigator/pantry` → items (adds `state`, `confidence`, `last_observed_at`, `source`).
- `PUT /navigator/pantry` → replace-all (preserves the existing semantic; writes a diff to the ledger).
- `POST /navigator/pantry/items` → add one (via existing `app.state.resolver`); logs `add`.
- `DELETE /navigator/pantry/items/{name}` → remove; logs `adjust`.

New:

- `POST /navigator/pantry/items/{name}/consume` — body `{coarse_amount}` → applies the transition above.
- `POST /navigator/cook` — body `{recipe_id?, dish_name, servings?, rating?, notes?, photo?, consumed?}`.
  **Atomic** (single SQLite transaction): insert a `cook_event`, and for each consumed ingredient that
  resolves (via `app.state.resolver`) to an on-hand item, apply the tap-to-cook soft-decrement + log a
  `consume` event. For `recipe_id`, derive `consumed` from the recipe's `ingredients_json`
  (`RecipeStore.get`) when the body omits it. Returns the new cook event + the affected items.
  **`servings` is recorded on the cook event** (for the log and future quantity-aware slices) **but does
  NOT scale the decrement in SP-A** — the decrement stays coarse (one notch per ingredient) by design.
  Do not wire `servings → quantity`; that reintroduces the precision this design deliberately rejects.
- `GET /navigator/meals?limit=` — cook-event timeline, newest first.
- `GET /navigator/waste?window=30d` — counts/items from `discard` + `expire` events in the window.

The existing `/recipes/from-pantry`, `/refine`, `/swaps` recompute keeps working unchanged except that
"on-hand" now = items with `state IN ('present','low')` (used_up excluded). Expiry already feeds
`rank_recipes` via `Pantry.expiring_within`; the loop nudges reuse that signal.

## Frontend (Preact — `web/src/`)

- **`RecipeCard.tsx` (expanded view):** an **"I cooked this"** button → a small sheet with a servings
  stepper (default = recipe servings or 2) + optional rating/notes → `POST /navigator/cook`. On
  success: optimistic toast, refresh pantry (now decremented), the meal lands in the timeline.
- **Kitchen-log timeline:** a new lightweight view reachable from the top bar (the single-screen
  design stays; add a small "log" affordance), rendering `GET /navigator/meals` (date, dish, photo,
  rating, notes). Mealie proves users want this.
- **Pantry items:** coarse consume control (overflow menu or swipe) → "used up / half left / threw
  away" → `POST .../consume`; dimmed `used_up` rows with "still have it" restore.
- **Expiry nudges:** items expiring soon get a badge; an "Expiring soon — cook these" strip links to
  recipes that use them (ranking already weights expiry). "Threw it away" on a nudge → `discard`.

## Error handling

- All writes go through a single transaction per request; on failure, roll back and return a typed
  error (no partial cook/decrement). Reuse the existing 422 pattern for unresolved ingredients.
- `cook` with no resolvable consumed items still records the cook event (the log is valuable even when
  nothing matches the pantry) — return which ingredients matched vs. didn't.
- Migration is guarded by the empty-table check so re-runs are no-ops; a corrupt `pantry.json` is
  logged and skipped (start empty), never fatal.

## Testing strategy

**Local-test reality on this Pi (verified 2026-05-28):**
- The `.venv` is **stale** — `python-multipart` and `Pillow` are *declared* in `pyproject.toml`
  (`:47`, `:51`) but absent from the venv, so `from ...server import app` raises
  `RuntimeError: Form data requires "python-multipart"` at import. **Refresh first:**
  `.venv/bin/pip install -e '.[dev]'` (or run under a clean env). This is the documented
  "Pi pre-installed deps mask undeclared bugs" lesson in reverse — a stale venv hides a declared dep.
- App construction is **lazy** (`server.py:265` — `store = None`; `_get_store()` fills from
  `store_factory` on first use). Importing `app` and hitting `kitchen.db`-only routes does **not**
  touch `recipes.db`/sqlite-vec, so it runs on this Pi's Python 3.11. The sqlite-vec wall is hit only
  when a route actually queries the recipe store.
- Therefore tests **inject a fake in-memory `store_factory`** (the pattern PR #4's registry tests
  proved) so `/cook` with a `recipe_id` exercises `RecipeStore.get` against a fake, never the live
  extension-loaded `recipes.db`. Expect gcov `*.gcda Cannot open` stderr noise; filter with
  `grep -v -E "profiling:|\.gcda:|Cannot open"`.

**Tests:**
- **Unit (run locally on 3.11 after the venv refresh; `kitchen.db` is plain SQLite, no extension):**
  schema round-trip; migration from a fixture `pantry.json` (idempotent, non-destructive, ledger
  entries, source-rename to `.imported`); soft-decrement transitions for every `coarse_amount` and the
  tap-to-cook default; cook-event atomicity + rollback; `recipe_id → consumed` derivation **via a fake
  store**; waste tally windowing; the `/cook` `/meals` `/waste` `/pantry` `/consume` handlers via
  FastAPI `TestClient` with an injected fake store.
- **Regression:** `/recipes/from-pantry` returns the same ranking for the same on-hand set, now reading
  SQLite; `used_up`/`confidence`-zero items are excluded from matching. The assertion against the
  **live** 50K `recipes.db` (real sqlite-vec) stays CI-gated or runs under `/usr/bin/python3` 3.13, per
  the project's known local-sqlite limitation; the logic itself is covered locally via the fake store.
- **Frontend (headless chromium, existing harness):** cook → pantry decrements + meal appears; coarse
  consume + restore; timeline renders; expiry nudge → discard logs waste.
- Lint/format clean: `ruff check .` (not just `ruff check pantryatlas/`) + `npm run build`. Verify a
  fresh `pip install -e '.[dev]'` succeeds before claiming CI-green (the v0.2 undeclared-dep lesson).

## Open questions (resolve during planning)

- Single-screen vs. a second route for the Kitchen-log timeline — follow `web/design/DESIGN.md`; lean
  toward an in-place expandable section over a new route to preserve the no-routes ethos.
- Photo on a cook event in SP-A: accept an uploaded file now (host stores it under `~/.pantryatlas/`)
  or defer photos to SP-B? Lean: accept an optional upload now (small, no vision needed) so the
  timeline is rich from day one.
- Should `PUT /navigator/pantry` (replace-all) diff against current state to emit precise ledger
  events, or log a coarse "bulk replace"? Lean: diff, so the ledger stays trustworthy.

## References

Parent vision + grounding brief (links above). Existing code touched: `pantryatlas/navigator/server.py`
(pantry/recipe routes, `_load_pantry`/`_save_pantry`, `app.state.resolver`), `pantryatlas/pantry/
models.py` (Quantity/Ingredient/Pantry), `pantryatlas/store/recipes.py` (`RecipeStore.get` for
`recipe_id → ingredients`), `web/src/components/RecipeCard.tsx`, `web/src/pages/Navigator.tsx`.
