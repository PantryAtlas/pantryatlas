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
        ▼  stored in ~/.pantryatlas/pantry.json
  POST /navigator/recipes/from-pantry
        │
        ▼  text-overlap pre-filter → rank_recipes()
  Ranked recipe list (score, coverage, missing)
```

The navigator consists of three parts:

- **FastAPI server** (`pantryatlas.navigator.server`) — 7 REST routes + static PWA serving
- **Ranking algorithm** (`pantryatlas.navigator.ranking`) — weighted scoring of candidate recipes
- **Ingestion CLI** (`pantryatlas.navigator.ingest`) — loads RecipeNLG data into the recipe store

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

The navigator server exposes 7 routes under the `/navigator` prefix. All request and response bodies are JSON.

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

Returns the current pantry as a list of ingredient objects, loaded from `~/.pantryatlas/pantry.json`.

**Response:** array of ingredient objects (see PUT /navigator/pantry for shape).

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

### The instant → refine → swaps flow

The navigator splits the expensive substitution embedding out of the critical path so results feel instant and agentic:

1. **Instant** — `/from-pantry` paints coverage-ranked cards in ~1s (no embedding).
2. **Refine** — the client immediately calls `/refine` with those cards; the UI shows a subtle "refining…" chip and the top cards re-order as real substitution scores arrive (~1s). Scores only move *down*, so the settle is stable.
3. **Swaps** — expanding a card calls `/swaps` for just that recipe's missing items, surfacing "try olive oil · 81% match" inline where the user decides to cook.

`/refine` and `/swaps` are network-only (never cached by the service worker) and degrade gracefully offline: the instant coverage results stand, the chip reads "offline · coverage order", and expanded cards show "swaps unavailable offline".

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

**No telemetry.** PantryAtlas sends no data off-device. The pantry is stored in `~/.pantryatlas/pantry.json`. The recipe database is stored in `~/.pantryatlas/recipes.db`. The server binds to your local network only; nothing is routed to the internet.

**RecipeNLG attribution.** Recipe data is sourced from the RecipeNLG corpus:

> Bień, M., Gilski, M., Maciejewska, M., Taisner, W., Wisniewski, D., & Lawrynowicz, A. (2020). RecipeNLG: A cooking recipes dataset for semi-structured text generation. In *Proceedings of the 13th International Conference on Natural Language Generation* (pp. 22–28). Association for Computational Linguistics.

The RecipeNLG corpus is licensed **CC-BY-NC-4.0** (Creative Commons Attribution–NonCommercial 4.0 International). PantryAtlas is a non-commercial, local-first system consistent with this license. The expanded recipe card in the PWA displays "From RecipeNLG · CC-BY-NC-4.0" on each recipe.

**FlavorDB attribution.** Flavor compound data (used for ingredient vocabulary construction) is sourced from FlavorDB, licensed **CC-BY-NC-3.0**.
