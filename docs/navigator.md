# PantryAtlas Navigator

The navigator is the v0.2.0 submodule of PantryAtlas: it turns a pantry list into ranked recipes, entirely on-device.

---

## Overview

The navigator accepts whatever is on the shelf (typed or photographed) and returns recipes ranked by how well your pantry covers them. No internet connection, no account, no cloud call. All inference — embedding, resolution, ranking — runs on the Raspberry Pi 5.

Data flow:

```
Pantry items (typed / photographed)
        │
        ▼  POST /navigator/pantry/items
  Ingredient resolution (exact → fuzzy → semantic)
        │
        ▼  stored in ~/.pantryatlas/kitchen.db (KitchenStore)
  POST /navigator/recipes/from-pantry
        │
        ▼  text-overlap pre-filter → rank_recipes()
  Ranked recipe list (score, coverage, missing)
        │
        ▼  POST /navigator/cook  ("I cooked this")
  Cook event logged + on-hand items soft-decremented
        │
        ▼  GET /navigator/meals · GET /navigator/waste
  Meal-log timeline + waste tally
```

The navigator consists of four parts:

- **FastAPI server** (`pantryatlas.navigator.server`) — REST routes under `/navigator` + static PWA serving
- **Ranking algorithm** (`pantryatlas.navigator.ranking`) — weighted scoring of candidate recipes
- **Ingestion CLI** (`pantryatlas.navigator.ingest`) — loads RecipeNLG data into the recipe store
- **Kitchen store** (`pantryatlas.store.kitchen.KitchenStore`) — mutable user state (pantry + event ledger + cook log) in `~/.pantryatlas/kitchen.db`, the source of truth that closes the food-waste loop (see *Kitchen store + the cook loop* below)

---

## Ingestion

Recipes are loaded from the [RecipeNLG](https://recipenlg.cs.put.poznan.pl/) corpus (licensed CC-BY-NC-4.0) via a staged parquet file.

### Staging the parquet

Download the RecipeNLG dataset and place it at:

```
pantryatlas/data/_staging/recipenlg.raw.parquet
```

### Running the CLI

```bash
# Dry run — parse + curate, no DB writes
python -m pantryatlas.navigator.ingest --limit 50000 --dry-run

# Full run — writes to ~/.pantryatlas/recipes.db by default
python -m pantryatlas.navigator.ingest --limit 50000 --target-db ~/.pantryatlas/recipes.db

# Custom staging parquet
python -m pantryatlas.navigator.ingest \
  --limit 50000 \
  --staging-parquet /path/to/recipenlg.raw.parquet
```

### Flags

| Flag | Default | Description |
|---|---|---|
| `--limit N` | required | Target number of curated recipes to select |
| `--dry-run` | off | Print summary; do not write to DB |
| `--target-db PATH` | `~/.pantryatlas/recipes.db` | Target database path (ignored in dry-run) |
| `--staging-parquet PATH` | `pantryatlas/data/_staging/recipenlg.raw.parquet` | Path to RecipeNLG staged parquet |

### Curation rules

The CLI applies ingredient-count curation before writing:

- Recipes with fewer than 3 distinct ingredients are discarded.
- Accepted recipes are bucketed by ingredient count: **3–5**, **6–8**, **9+**.
- The CLI samples to balance across buckets (`limit ÷ 3` per bucket target), then redistributes leftover quota from under-filled buckets.
- The output is sorted by title for reproducibility.

The CLI prints a summary line for each bucket and each discard reason. Embedding of recipes for semantic pre-filter is handled at write time (T-002 layer).

---

## Running

### Development

```bash
# Backend (in one terminal)
uvicorn pantryatlas.navigator.server:app --reload --port 8090

# Frontend (in another terminal, from the web/ directory)
cd web && npm run dev
```

The API is available at `http://localhost:8090`. The Vite dev server proxies API calls to `localhost:8090` and serves the PWA on its own port (default 5173).

### Production (systemd)

The production unit is at `ops/systemd/pantryatlas-navigator.service`. It runs as the `pantryatlas` user and binds to all interfaces on port 8090:

```ini
ExecStart=/home/pantryatlas/pantryatlas/venv/bin/uvicorn \
    pantryatlas.navigator.server:app \
    --host 0.0.0.0 --port 8090
```

The unit starts after `pantryatlas-embeddings.service` and `pantryatlas-gemma.service`.

Enable and start:

```bash
sudo systemctl enable pantryatlas-navigator
sudo systemctl start pantryatlas-navigator
```

Once running, the navigator is reachable at `http://pantryatlas.local:8090` from any device on the same Wi-Fi. The root path (`/`) serves the built PWA (`web/dist/index.html`) if it exists.

---

## PWA install

Open `http://pantryatlas.local:8090` in a browser on any phone or laptop on the same Wi-Fi.

**iOS (Safari):** Share → Add to Home Screen → Add. The navigator appears as a full-screen app on your home screen.

**Android (Chrome):** Three-dot menu → Install app, or tap the banner if Chrome offers it.

### What you get

The navigator is a single-screen app — pantry on top, recipes below, no tabs or bottom nav.

**Dual-modality input (Section B):** There is one pill-shaped input row at the top of the screen. You can type an ingredient (Enter to submit) or tap the camera icon to photograph the shelf. Both flows feed the same pantry list. During ingredient resolution a cool-blue radial pulse indicates the server is working. On unrecognized input, the field shakes and prompts in a conversational tone.

**Home / Community Kitchen mode:** A mode chip in the top bar lets you choose between Home Kitchen (4–10 servings) and Community Kitchen (50–500 servings). The mode persists to device settings. Ranking adapts under the hood; there is no separate advanced mode or override affordance.

---

## API reference

The navigator server exposes a set of routes under the `/navigator` prefix. All request and response bodies are JSON.

---

`GET /navigator/health`

Returns service health and the number of recipes loaded in the store.

**Response:**
```json
{
  "status": "ok",
  "recipe_count": 48321
}
```

---

`GET /navigator/pantry`

Returns the current pantry as a list of ingredient objects, loaded from the `KitchenStore` (`~/.pantryatlas/kitchen.db`). Each item carries a coarse `state` (`present` / `low` / `used_up`) and `confidence` alongside the editable fields.

**Response:** array of ingredient objects (see PUT /navigator/pantry for the editable shape; reads additionally include `state`, `confidence`, `source`, and `last_observed_at`).

---

`PUT /navigator/pantry`

Replaces the entire pantry with the supplied list (Pydantic-validated). Returns the saved pantry.

**Request body:** array of ingredient objects:
```json
[
  {
    "canonical_name": "butternut squash",
    "raw_text": "half a squash",
    "quantity": { "amount": 0.5, "unit": "whole" },
    "expires_at": "2026-05-30"
  }
]
```

`quantity` and `expires_at` are optional. `expires_at` is an ISO 8601 date string.

**Response:** the saved pantry (same shape as request body).

---

`POST /navigator/pantry/items`

Adds one ingredient from raw text. The server resolves the text to a canonical name using the ingredient matcher (exact → fuzzy → semantic). Returns 201 on success, 422 if the text cannot be resolved.

**Request body:**
```json
{ "raw_text": "wilting kale" }
```

**Response (201):**
```json
{
  "canonical_name": "kale",
  "raw_text": "wilting kale"
}
```

**Error (422):** `{"detail": "Cannot resolve 'wilting kale' to a canonical ingredient."}`

---

`DELETE /navigator/pantry/items/{name}`

Removes an ingredient by canonical name. No-op if the name is not present (does not error).

**Path parameter:** `name` — the canonical ingredient name (e.g. `kale`).

**Response:**
```json
{ "removed": "kale" }
```

---

`POST /navigator/pantry/resolve`

Resolves raw text to a canonical ingredient name **without** modifying the pantry. Intended for live UI feedback as the user types (debounced resolution). Returns 404 if the text cannot be resolved.

**Request body:**
```json
{ "raw": "butternut" }
```

**Response:**
```json
{ "canonical_name": "butternut squash" }
```

**Error (404):** `{"detail": "Cannot resolve 'butternut' to a canonical ingredient."}`

---

`POST /navigator/recipes/from-pantry`

**Instant, fast mode.** Pre-filters candidate recipes by text overlap against the current pantry and ranks them by coverage + expiration + cultural fit only — **no embedding**, so it returns in ~1s even against a 50K-recipe store. `substitution_penalty` is `0.0` (optimistic) for every result. The client then calls `/refine` to settle the ordering with real substitution scores (see *The instant → refine → swaps flow* below).

**Query parameter (optional):** `cuisine` — cuisine string (e.g. `italian`). When supplied, recipes whose title contains this string receive `cultural_fit = 1.0`.

**Response:** array of ranked recipe objects (`instructions` is a list of step strings):
```json
[
  {
    "recipe": {
      "title": "Butternut & Kale Stew",
      "ingredients": ["butternut squash", "kale", "garlic"],
      "instructions": ["Heat oil…", "Add squash…"]
    },
    "score": 0.74,
    "coverage": 0.83,
    "missing": ["garlic"],
    "expiration_urgency": 0.5,
    "substitution_penalty": 0.0,
    "cultural_fit": 0.0,
    "source": "RecipeNLG (CC-BY-NC-4.0)"
  }
]
```

Returns an empty array when no pantry items overlap any recipe in the store.

---

`POST /navigator/recipes/from-pantry/refine`

**Settle the ordering with real substitution scores.** The client sends back the recipes it already painted; the server recomputes their substitution penalty against the *current* pantry (embedding only the unique missing ingredients across the supplied recipes, in one batch) and returns them re-ranked. Because fast mode was optimistic, refining can only *lower* scores — cards converge downward into a stable settle.

**Request body:** a JSON array of recipe objects `{title, ingredients, instructions}` (the `recipe` field of each `/from-pantry` result).

**Query parameter (optional):** `cuisine` — same as `/from-pantry`.

**Response:** same ranked-recipe shape as `/from-pantry`, re-sorted, with real `substitution_penalty` values.

---

`POST /navigator/recipes/swaps`

**Lazy per-recipe swap suggestions**, fired when a recipe card is expanded. Embeds only that recipe's missing ingredients (typically 2–5) against the current pantry, so it is fast.

**Request body:**
```json
{ "ingredients": ["kale", "garlic", "soy sauce", "sesame oil"] }
```

**Response:** one entry per *missing* ingredient. `best_swap` is the closest pantry item when it clears the similarity floor (cosine ≥ 0.5), else `null` with a `reason`:
```json
{
  "swaps": [
    { "missing": "sesame oil", "best_swap": "olive oil", "similarity": 0.81, "reason": null },
    { "missing": "soy sauce", "best_swap": null, "similarity": 0.31, "reason": "no_close_match" }
  ]
}
```
`reason` is `"no_close_match"` when nothing clears the floor, or `"no_pantry"` when the pantry is empty.

---

`POST /navigator/pantry/items/{name}/consume`

Applies a **coarse consume transition** to one pantry item (manual "used some / used it up / threw it away" controls on the pantry row). Returns the updated item, or 404 if there is no such item. Each transition appends an `inventory_events` ledger row.

**Path parameter:** `name` — the canonical ingredient name.

**Request body:**
```json
{ "coarse_amount": "half" }
```

`coarse_amount` is one of:

| `coarse_amount` | Effect | Ledger `change_type` |
|---|---|---|
| `half` | "used some" — `present → low` (`confidence → 0.5`); already-`low` stays `low` | `consume` |
| `used_up` | "used it up" — any state → `used_up` (`confidence → 0.0`) | `consume` |
| `discarded` | "threw it away" — any state → `used_up`, counted as waste | `discard` |
| `cook` | one notch down (`present → low → used_up`); the tap-to-cook default | `consume` |

**Response (200):** the updated item object (same shape as `GET /navigator/pantry`).

**Error (404):** `{"detail": "No pantry item 'kale'."}`

---

`POST /navigator/pantry/items/{name}/restore`

Restores a consumed/expired item back to `present` (`confidence → 1.0`) — the undo for an accidental consume or a camera rescan that finds the item still on the shelf. Appends an `observe` ledger row. Returns the updated item, or 404 if there is no such item.

**Response (200):** the updated item object. **Error (404):** `{"detail": "No pantry item 'kale'."}`

---

`POST /navigator/cook`

**"I cooked this."** Atomically logs a cook event *and* soft-decrements the consumed on-hand items, in a single SQLite transaction. This is the route the recipe card's "I cooked this" button calls.

The button derives `consumed` from the recipe's **covered** ingredients (present in the pantry), each at `coarse_amount: "cook"` — so cooking a recipe drops every ingredient it used one notch (`present → low`, `low → used_up`). If `consumed` is omitted but `recipe_id` is supplied, the server resolves that recipe's ingredients and decrements the on-hand subset. Any consumed name that is **not** on-hand is reported under `unmatched` and left untouched (the event still logs).

> **`servings` is logged but does not scale the decrement in SP-A.** The cook event records `servings` for the meal-log timeline, but every covered ingredient drops exactly one coarse notch regardless of how many servings were made. This is coarse-by-design: SP-A tracks *presence*, not quantity. A future camera rescan reconciles the true amount (see the blend truth-model below).

**Request body:**
```json
{
  "dish_name": "Garlic Kale Stir-Fry",
  "recipe_id": "r1",
  "servings": 2,
  "rating": 5,
  "notes": "extra garlic",
  "consumed": [
    { "canonical_name": "garlic", "coarse_amount": "cook" },
    { "canonical_name": "kale", "coarse_amount": "cook" }
  ]
}
```

Only `dish_name` is required. `recipe_id`, `servings`, `rating`, `notes`, and `consumed` are all optional.

**Response (201):**
```json
{
  "id": 1,
  "dish_name": "Garlic Kale Stir-Fry",
  "matched": ["garlic", "kale"],
  "unmatched": []
}
```

---

`GET /navigator/meals`

Returns the cook-event timeline, newest first — the meal-log view.

**Query parameter (optional):** `limit` — max events to return (default 50).

**Response:** array of cook-event objects:
```json
[
  {
    "id": 2,
    "recipe_id": "r1",
    "dish_name": "Garlic Kale Stir-Fry",
    "servings": 2,
    "cooked_at": "2026-05-28T18:30:00+00:00",
    "rating": 5,
    "notes": "extra garlic",
    "consumed": [{ "canonical_name": "garlic", "coarse_amount": "cook" }],
    "source": "tap-to-cook"
  }
]
```

---

`GET /navigator/waste`

Returns a **waste tally** — items that were discarded or expired within a rolling window, counted from the `inventory_events` ledger. Items merely *used up* through cooking are not waste.

**Query parameter (optional):** `window_days` — rolling window in days (default 30).

**Response:**
```json
{
  "window_days": 30,
  "discarded": 1,
  "expired": 1,
  "total": 2,
  "items": ["milk", "eggs"]
}
```

---

### The instant → refine → swaps flow

The navigator splits the expensive substitution embedding out of the critical path so results feel instant and agentic:

1. **Instant** — `/from-pantry` paints coverage-ranked cards in ~1s (no embedding).
2. **Refine** — the client immediately calls `/refine` with those cards; the UI shows a subtle "refining…" chip and the top cards re-order as real substitution scores arrive (~1s). Scores only move *down*, so the settle is stable.
3. **Swaps** — expanding a card calls `/swaps` for just that recipe's missing items, surfacing "try olive oil · 81% match" inline where the user decides to cook.

`/refine` and `/swaps` are network-only (never cached by the service worker) and degrade gracefully offline: the instant coverage results stand, the chip reads "offline · coverage order", and expanded cards show "swaps unavailable offline".

---

## Kitchen store + the cook loop

The `KitchenStore` (`pantryatlas.store.kitchen.KitchenStore`) holds all **mutable user state** in `~/.pantryatlas/kitchen.db`. It is plain SQLite — **no `sqlite-vec`** — so it runs on every Python including the Pi's 3.11 build that lacks `enable_load_extension`. It is kept deliberately separate from the static, embedding-bearing `recipes.db`.

It is wired into `create_app` with the same lazy-init pattern as `RecipeStore` (`kitchen` / `kitchen_factory` params + a `_get_kitchen` accessor), so importing the server module stays side-effect-free — the db is opened on first request, not at import.

### Schema

Three tables:

| Table | Holds |
|---|---|
| `pantry_items` | One row per ingredient: editable fields (`raw_text`, `quantity_*`, `expires_at`) plus the coarse-state model (`state`, `confidence`, `last_observed_at`, `source`). |
| `inventory_events` | Append-only ledger: one row per `add` / `consume` / `discard` / `expire` / `observe` / `adjust`, tagged with `source` and an optional `detail_json`. The waste tally and audit trail read from here. |
| `cook_events` | One row per "I cooked this": `dish_name`, `recipe_id`, `servings`, `rating`, `notes`, `cooked_at`, and the `consumed_json` snapshot. Drives the meal-log timeline. |

### Migration from `pantry.json`

Earlier versions stored the pantry as a flat `~/.pantryatlas/pantry.json` file. On first open, `KitchenStore` performs a **one-time, non-destructive migration**: if `pantry_items` is empty and `pantry.json` still exists, it imports every item (state `present`, confidence `1.0`, source `manual`), writes one `add` ledger row per item tagged `source='migration'`, then **renames** the file to `pantry.json.imported`. Because the rename removes the trigger and the populated table short-circuits the import, re-opening the store is a no-op — the migration cannot run twice or duplicate items. A corrupt/unreadable `pantry.json` is skipped (the store simply starts empty); it is never fatal.

### Coarse-state model

A pantry item's presence is tracked at three coarse levels, not as a precise quantity:

| `state` | `confidence` | Meaning |
|---|---|---|
| `present` | 1.0 | On hand. Counts toward recipe coverage. |
| `low` | 0.5 | Running low — one notch consumed. Still counts as on-hand for ranking. |
| `used_up` | 0.0 | Gone. Excluded from recipe ranking; the row is dimmed in the UI. |

Only `present` and `low` items feed `on_hand()` (and therefore recipe ranking). `used_up` items are retained (not deleted) so they can be restored or reconciled.

### Blend truth-model

The loop blends two sources of truth so it can run with **no new hardware**:

- **Cook soft-decrements.** Tapping "I cooked this" (or a manual consume control) moves items one coarse notch down. This is fast, cheap, and approximate — it assumes you used what the recipe covers. It deliberately does **not** scale by `servings`; `servings` is recorded on the cook event for the timeline only.
- **Future camera rescans reconcile.** A subsequent shelf scan is authoritative: it can promote a `used_up` item back to `present` (via the restore path) or confirm it really is gone, correcting any drift the soft-decrement introduced.

The append-only `inventory_events` ledger preserves the full history regardless of which source wrote a given change, so reconciliation never loses information.

---

## Ranking algorithm

Candidate recipes are scored by a weighted formula. All sub-scores are in [0, 1].

```
score = 0.50 × coverage
      + 0.20 × expiration_urgency
      + 0.20 × (1 − substitution_penalty)
      + 0.10 × cultural_fit
```

### Terms

**`coverage` (weight 0.50)**
Fraction of the recipe's ingredients that are present in the pantry:

```
coverage = (# recipe ingredients in pantry) / (# recipe ingredients)
```

Coverage uses direct string membership against canonical names. Recipes are pre-filtered before ranking by text-overlap so candidates already share at least one ingredient with the pantry.

**`expiration_urgency` (weight 0.20)**
Fraction of items expiring within the next 7 days that this recipe would consume:

```
expiration_urgency = (# expiring pantry items the recipe uses) / (# expiring pantry items)
```

0 when no pantry items have an `expires_at` date set. Promotes recipes that clear expiring stock.

**`(1 − substitution_penalty)` (weight 0.20)**
For each ingredient the recipe requires that is **missing** from the pantry, the algorithm computes the maximum cosine similarity between that missing ingredient's embedding and every item currently in the pantry. `penalty_i = 1 − max_cosine`. The substitution penalty is the mean across all missing ingredients. A recipe where every missing ingredient has a close pantry substitute scores high on this term; a recipe requiring exotic items that have no pantry analog scores low.

This is the only term that needs the embedding model. `rank_recipes(..., compute_substitution=False)` (**fast mode**, used by `/from-pantry`) skips it and sets `substitution_penalty = 0.0`; `compute_substitution=True` (**refine mode**, used by `/refine` and `/swaps`) embeds every unique missing ingredient across the candidate set in a *single* batched call, since the embedder is the slow part on a Pi (~16 short strings/sec).

**`cultural_fit` (weight 0.10)**
1.0 if the requested `cuisine` string (lowercased) appears in the recipe title (lowercased); 0.0 otherwise. Always 0.0 when no `cuisine` query parameter is supplied.

### Result set

Results are sorted descending by score. The endpoint returns at most 20 recipes (`k=20`). Each result carries all four sub-scores alongside the recipe for UI display and debugging.

---

## Privacy + attribution

**No telemetry.** PantryAtlas sends no data off-device. Mutable user state — the pantry, the inventory-event ledger, and the cook log — is stored in `~/.pantryatlas/kitchen.db` (migrated once from the legacy `~/.pantryatlas/pantry.json`, which is then renamed to `pantry.json.imported`). The static recipe database is stored in `~/.pantryatlas/recipes.db`. The server binds to your local network only; nothing is routed to the internet.

**RecipeNLG attribution.** Recipe data is sourced from the RecipeNLG corpus:

> Bień, M., Gilski, M., Maciejewska, M., Taisner, W., Wisniewski, D., & Lawrynowicz, A. (2020). RecipeNLG: A cooking recipes dataset for semi-structured text generation. In *Proceedings of the 13th International Conference on Natural Language Generation* (pp. 22–28). Association for Computational Linguistics.

The RecipeNLG corpus is licensed **CC-BY-NC-4.0** (Creative Commons Attribution–NonCommercial 4.0 International). PantryAtlas is a non-commercial, local-first system consistent with this license. The expanded recipe card in the PWA displays "From RecipeNLG · CC-BY-NC-4.0" on each recipe.

**FlavorDB attribution.** Flavor compound data (used for ingredient vocabulary construction) is sourced from FlavorDB, licensed **CC-BY-NC-3.0**.
