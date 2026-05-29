# Star Slice 2 — Cuisine / Diet / Time Filters Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Filter from-pantry results by cuisine (strict, precision-curated), diet (detection-based "hide meat/dairy/gluten"), and estimated time — derived at query time, hard pre-filter before rank, with an empty-state + clear-filters.

**Architecture:** New pure `pantryatlas/navigator/facets.py` (in-module keyword constants → no data file). Server applies `passes_filters` to `iter_overlapping` candidates before `rank_recipes`, and stops passing `cuisine` into ranking (cuisine is now a pre-filter). Filters travel as query params. Web adds a filter bar + empty state.

**Tech Stack:** Python 3 + FastAPI; Preact + @preact/signals + Vite; pytest via `/usr/bin/python3 -m pytest`; vitest.

**Critical conventions:**
- Run Python tests with `/usr/bin/python3 -m pytest …` (the `.venv` has no pytest). `ruff` on PATH.
- Subagents use **specific `git add <paths>`**, never `git add -A`.
- Keyword/marker lists are **in-module Python constants** — NO data file (avoids the slice-3 dependency/shipping traps).
- Diet copy is **detection-framed**, never a guarantee.
- Do NOT re-introduce `cuisine` into `rank_recipes`; do NOT re-weight `cultural_fit`.

---

### Task 1: `facets.py` — cuisine / diet / time derivation

**Files:**
- Create: `pantryatlas/navigator/facets.py`
- Test: `tests/navigator/test_facets.py`

- [ ] **Step 1: Write the failing tests** (`tests/navigator/test_facets.py`)

```python
from __future__ import annotations

from pantryatlas.navigator.facets import (
    CUISINES,
    classify_cuisine,
    detect_excludes,
    estimate_time_min,
)


def test_cuisine_precision():
    assert classify_cuisine("Beef Tacos", ["ground beef", "tortilla", "salsa"]) == "mexican"
    assert classify_cuisine("Spaghetti Carbonara", ["spaghetti", "pancetta", "parmesan"]) == "italian"
    assert classify_cuisine("Chicken Tikka Masala", ["chicken", "garam masala", "paneer"]) == "indian"
    assert classify_cuisine("BBQ Brisket", ["brisket", "bbq sauce"]) == "american"
    assert classify_cuisine("Greek Salad", ["feta", "olive", "tomato"]) == "greek"
    assert classify_cuisine("Chicken Stir-Fry", ["chicken", "soy sauce", "bok choy"]) == "asian"
    # generic recipe → None (no butter→french false positive)
    assert classify_cuisine("Buttered Toast", ["bread", "butter"]) is None
    # shipped set is exactly these six (Thai/French dropped)
    assert set(CUISINES) == {"italian", "mexican", "asian", "american", "indian", "greek"}


def test_detect_excludes():
    assert detect_excludes(["chicken breast", "onion"]) == {"meat"}
    assert "dairy" in detect_excludes(["milk", "cheddar cheese"])
    assert "gluten" in detect_excludes(["all-purpose flour", "sugar"])
    assert detect_excludes(["soy sauce", "rice"]) >= {"gluten"}  # soy sauce has gluten
    assert detect_excludes(["apple", "carrot", "lettuce"]) == set()


def test_estimate_time_min():
    assert estimate_time_min("Bake for 30 minutes.") == 30
    assert estimate_time_min("Simmer 1 hour.") == 60
    assert estimate_time_min("Cook 30 to 40 minutes.") == 35  # range counted once
    assert estimate_time_min("Stir every 2 minutes while baking 20 minutes.") == 20  # 'every 2' skipped
    assert estimate_time_min("Chill overnight.") == 480
    assert estimate_time_min("Mix well and serve.") is None  # no duration
```

- [ ] **Step 2: Run to verify they fail**

Run: `cd /home/craigm26/pantryatlas && /usr/bin/python3 -m pytest tests/navigator/test_facets.py -v`
Expected: FAIL — `ModuleNotFoundError: ...facets`.

- [ ] **Step 3: Implement `pantryatlas/navigator/facets.py`**

```python
"""Query-time recipe facets: cuisine / diet / time, derived from unstructured text.

All keyword lists are in-module constants (no data file → no dependency or
shipping gap). Precision-first: a recipe with no distinctive marker is unclassified.
"""
from __future__ import annotations

import re

# Distinctive cuisine markers (curated for precision; generic cooking words excluded).
# Thai/French dropped (insufficient precision/volume); Indian limited to unambiguous markers.
CUISINES: dict[str, list[str]] = {
    "italian": [
        "spaghetti", "lasagna", "lasagne", "risotto", "marinara", "parmesan",
        "parmigiano", "mozzarella", "ricotta", "prosciutto", "pesto", "fettuccine",
        "gnocchi", "cannoli", "manicotti", "pancetta", "ziti", "alfredo",
    ],
    "mexican": [
        "taco", "tortilla", "salsa", "enchilada", "quesadilla", "guacamole",
        "fajita", "chipotle", "tostada", "burrito", "refried", "tomatillo",
    ],
    "asian": [
        "soy sauce", "hoisin", "teriyaki", "miso", "bok choy", "wonton", "szechuan",
        "sichuan", "stir-fry", "stir fry", "oyster sauce", "five spice", "lo mein",
        "chow mein", "sesame oil", "sriracha",
    ],
    "indian": [
        "garam masala", "paneer", "tikka", "tandoori", "naan", "biryani", "korma",
        "masala",
    ],
    "greek": [
        "feta", "tzatziki", "hummus", "falafel", "pita", "tahini", "gyro",
        "baklava", "spanakopita", "dolma",
    ],
    "american": [
        "cornbread", "meatloaf", "grits", "sloppy joe", "bbq sauce",
        "barbecue sauce", "jambalaya", "pot roast", "buttermilk biscuit",
    ],
}

# Tie-break priority when a recipe matches multiple cuisines by equal marker count.
_CUISINE_PRIORITY = ["indian", "mexican", "greek", "asian", "italian", "american"]

MEAT_MARKERS: list[str] = [
    "beef", "chicken", "pork", "bacon", "sausage", "ham ", "turkey", "lamb",
    "steak", "veal", "prosciutto", "pancetta", "pepperoni", "salami", "duck",
    "fish", "salmon", "tuna", "shrimp", "crab", "anchovy", "gelatin",
    "chicken broth", "beef broth", "fish sauce",
]
DAIRY_MARKERS: list[str] = [
    "milk", "cheese", "butter", "cream", "yogurt", "parmesan", "mozzarella",
    "cheddar", "ricotta", "ghee", "buttermilk", "custard", "half and half",
]
GLUTEN_MARKERS: list[str] = [
    "flour", "bread", "pasta", "wheat", "barley", "rye", "soy sauce", "breadcrumb",
    "bread crumb", "cracker", "noodle", "tortilla", "couscous", "semolina",
    "beer", "malt",
]

_EXCLUDE_MARKERS = {"meat": MEAT_MARKERS, "dairy": DAIRY_MARKERS, "gluten": GLUTEN_MARKERS}
VALID_EXCLUDES = frozenset(_EXCLUDE_MARKERS)

# Durations not preceded by "every" (frequency, not duration).
_TIME_RE = re.compile(
    r"(?<!every )(\d+)\s*(?:to|-|–)?\s*(\d+)?\s*(minutes?|mins?|hours?|hrs?)\b", re.I
)
_OVERNIGHT_RE = re.compile(r"over\s*night", re.I)


def _blob(title: str, ingredients: list[str]) -> str:
    return (title + " " + " ".join(ingredients)).lower()


def classify_cuisine(title: str, ingredients: list[str]) -> str | None:
    """Return the single best-matching cuisine, or None if no distinctive marker."""
    blob = _blob(title, ingredients)
    scores: dict[str, int] = {}
    for cuisine, markers in CUISINES.items():
        n = sum(1 for m in markers if m in blob)
        if n:
            scores[cuisine] = n
    if not scores:
        return None
    best = max(scores.values())
    tied = [c for c, n in scores.items() if n == best]
    if len(tied) == 1:
        return tied[0]
    for c in _CUISINE_PRIORITY:
        if c in tied:
            return c
    return tied[0]


def detect_excludes(ingredients: list[str]) -> set[str]:
    """Return the subset of {meat, dairy, gluten} detected in the ingredient list."""
    blob = " ".join(ingredients).lower()
    return {name for name, markers in _EXCLUDE_MARKERS.items() if any(m in blob for m in markers)}


def estimate_time_min(instructions: str) -> int | None:
    """Rough TOTAL time estimate (incl. passive chill/bake) in minutes, or None.

    Sums stated durations (ranges counted once, hours ×60); 'overnight' → 480;
    durations preceded by 'every' (a frequency) are ignored.
    """
    if not instructions:
        return None
    total = 0.0
    found = False
    for m in _TIME_RE.finditer(instructions):
        found = True
        lo = int(m.group(1))
        hi = int(m.group(2)) if m.group(2) else lo
        val = (lo + hi) / 2
        if m.group(3).lower().startswith("h"):
            val *= 60
        total += val
    if _OVERNIGHT_RE.search(instructions):
        found = True
        total += 480
    return int(round(total)) if found else None


def passes_filters(
    recipe: dict,
    *,
    cuisine: str | None = None,
    exclude: set[str] | None = None,
    max_time_min: int | None = None,
) -> bool:
    """True if a candidate recipe dict ({title, ingredients, instructions}) passes
    all active filters. Cuisine is STRICT (unclassified hidden); diet hides on
    detection; time keeps unknown-estimate recipes."""
    ingredients = recipe.get("ingredients", []) or []
    if cuisine:
        if classify_cuisine(recipe.get("title", ""), ingredients) != cuisine:
            return False
    if exclude:
        if detect_excludes(ingredients) & exclude:
            return False
    if max_time_min is not None:
        instr = recipe.get("instructions", []) or []
        if isinstance(instr, list):
            instr = " ".join(instr)
        est = estimate_time_min(instr)
        if est is not None and est > max_time_min:
            return False
    return True
```

- [ ] **Step 4: Run to verify pass + tune precision**

Run: `cd /home/craigm26/pantryatlas && /usr/bin/python3 -m pytest tests/navigator/test_facets.py -v`
Expected: PASS. If a `test_cuisine_precision` assertion fails, fix the CUISINES markers (do not weaken assertions). Then eyeball-tune against the real DB:
```bash
/usr/bin/python3 - <<'PY'
import sqlite3, json
from pathlib import Path
from pantryatlas.navigator.facets import classify_cuisine, CUISINES
c = sqlite3.connect(Path.home()/".pantryatlas"/"recipes.db")
from collections import defaultdict
ex = defaultdict(list)
for t, ij in c.execute("SELECT title, ingredients_json FROM recipes_meta LIMIT 12000"):
    cz = classify_cuisine(t, json.loads(ij))
    if cz and len(ex[cz]) < 12: ex[cz].append(t[:46])
for k in CUISINES:
    print(k, "->", ex[k][:8])
PY
```
Read each cuisine's sample titles. If a cuisine's tagged titles don't read as plausibly that cuisine, tighten its markers or drop it. Document any drop.

- [ ] **Step 5: ruff + commit**

```bash
ruff check pantryatlas/navigator/facets.py tests/navigator/test_facets.py
git add pantryatlas/navigator/facets.py tests/navigator/test_facets.py
git commit -m "feat(facets): query-time cuisine/diet/time derivation + passes_filters"
```

---

### Task 2: Server wiring — apply filters, drop cuisine→ranking

**Files:**
- Modify: `pantryatlas/navigator/server.py`
- Modify: `tests/navigator/test_server.py`

- [ ] **Step 1: Write the failing tests** (append to `tests/navigator/test_server.py`)

```python
def _seed_pantry(client, *names):
    for n in names:
        client.post("/navigator/pantry/items", json={"raw_text": n, "canonical_name": n})


def test_from_pantry_cuisine_filter(client):
    _seed_pantry(client, "tortilla", "salsa", "cheese", "beef")
    res = client.post("/navigator/recipes/from-pantry", params={"cuisine": "mexican"})
    assert res.status_code == 200
    from pantryatlas.navigator.facets import classify_cuisine
    for r in res.json():
        assert classify_cuisine(r["recipe"]["title"], r["recipe"]["ingredients"]) == "mexican"


def test_from_pantry_exclude_filter(client):
    _seed_pantry(client, "flour", "sugar", "egg", "butter")
    res = client.post("/navigator/recipes/from-pantry", params={"exclude": "gluten"})
    assert res.status_code == 200
    from pantryatlas.navigator.facets import detect_excludes
    for r in res.json():
        assert "gluten" not in detect_excludes(r["recipe"]["ingredients"])


def test_from_pantry_unknown_exclude_ignored(client):
    _seed_pantry(client, "tomato", "onion")
    res = client.post("/navigator/recipes/from-pantry", params={"exclude": "bogus"})
    assert res.status_code == 200  # unknown token ignored, not an error


def test_from_pantry_no_filters_unchanged(client):
    _seed_pantry(client, "tomato", "onion", "garlic")
    a = client.post("/navigator/recipes/from-pantry").json()
    assert isinstance(a, list)
```

- [ ] **Step 2: Run to verify they fail**

Run: `cd /home/craigm26/pantryatlas && /usr/bin/python3 -m pytest tests/navigator/test_server.py -k "filter or exclude or no_filters" -v`
Expected: FAIL — the cuisine filter test fails because cuisine currently only affects (zeroed) ranking, not membership; exclude param not accepted.

- [ ] **Step 3: Implement**

In `pantryatlas/navigator/server.py`:

(a) Import the facet helpers near the other navigator imports:
```python
from pantryatlas.navigator.facets import VALID_EXCLUDES, passes_filters
```

(b) Replace `post_recipes_from_pantry`'s signature + body. New signature:
```python
    @app.post("/navigator/recipes/from-pantry")
    def post_recipes_from_pantry(
        cuisine: str | None = None,
        exclude: str = "",
        max_time_min: int | None = None,
    ) -> list[dict[str, Any]]:
```
After `candidates = _get_store(app).iter_overlapping(canonical_names)` and the
empty guard, insert the pre-filter (before `rank_recipes`):
```python
        exclude_set = {e.strip() for e in exclude.split(",") if e.strip()} & VALID_EXCLUDES
        if cuisine or exclude_set or max_time_min is not None:
            candidates = [
                c for c in candidates
                if passes_filters(c, cuisine=cuisine, exclude=exclude_set,
                                  max_time_min=max_time_min)
            ]
            if not candidates:
                return []
```
Then change the `rank_recipes(...)` call to **drop the `cuisine=` argument** (keep
`compute_substitution=False` and `flavor_fn=...`):
```python
        ranked: list[RankedRecipe] = rank_recipes(
            pantry,
            candidates,
            compute_substitution=False,
            flavor_fn=_get_flavor(app).flavor_score,
        )
```

(c) Apply the same three params + pre-filter to `post_recipes_refine`. Its candidates
come from the client-sent `recipes` body; build candidate dicts as today, then filter:
```python
    @app.post("/navigator/recipes/from-pantry/refine")
    def post_recipes_refine(
        recipes: list[RecipeIn],
        cuisine: str | None = None,
        exclude: str = "",
        max_time_min: int | None = None,
    ) -> list[dict[str, Any]]:
        ...
        candidates = [
            {"title": r.title, "ingredients": r.ingredients, "instructions": r.instructions}
            for r in recipes
        ]
        exclude_set = {e.strip() for e in exclude.split(",") if e.strip()} & VALID_EXCLUDES
        if cuisine or exclude_set or max_time_min is not None:
            candidates = [
                c for c in candidates
                if passes_filters(c, cuisine=cuisine, exclude=exclude_set,
                                  max_time_min=max_time_min)
            ]
        if not candidates:
            return []
        ranked = rank_recipes(
            pantry, candidates, app.state.embed_fn, k=len(candidates),
            compute_substitution=True, flavor_fn=_get_flavor(app).flavor_score,
        )
```
(Drop the `cuisine=` arg from this `rank_recipes` call too.)

- [ ] **Step 4: Run to verify pass**

Run: `cd /home/craigm26/pantryatlas && /usr/bin/python3 -m pytest tests/navigator/test_server.py -k "filter or exclude or no_filters or from_pantry or refine" -v`
Expected: PASS. Then run the FULL `tests/navigator/test_server.py` (no regressions — the old `test_cultural_fit`/cuisine server behavior, if any, still holds since ranking no longer gets cuisine). Then `ruff check pantryatlas/navigator/server.py tests/navigator/test_server.py`.

- [ ] **Step 5: Commit**

```bash
git add pantryatlas/navigator/server.py tests/navigator/test_server.py
git commit -m "feat(api): cuisine/diet/time pre-filter on from-pantry + refine"
```

---

### Task 3: Web — filter bar, signals, empty state, clear

**Files:**
- Create: `web/src/lib/filters.ts`
- Create: `web/src/lib/filters.test.ts`
- Modify: `web/src/signals.ts`
- Modify: `web/src/pages/Navigator.tsx`

- [ ] **Step 1: Write the failing test** (`web/src/lib/filters.test.ts`)

```ts
import { describe, it, expect } from 'vitest'
import { buildFilterQuery, CUISINE_OPTIONS, hasActiveFilters } from './filters'

describe('buildFilterQuery', () => {
  it('empty when no filters', () => {
    expect(buildFilterQuery(null, new Set(), null)).toBe('')
  })
  it('encodes cuisine + excludes + time', () => {
    const q = buildFilterQuery('italian', new Set(['meat', 'gluten']), 30)
    expect(q).toContain('cuisine=italian')
    expect(q).toMatch(/exclude=meat%2Cgluten|exclude=gluten%2Cmeat/)
    expect(q).toContain('max_time_min=30')
    expect(q.startsWith('?')).toBe(true)
  })
})

describe('hasActiveFilters', () => {
  it('false when all empty, true otherwise', () => {
    expect(hasActiveFilters(null, new Set(), null)).toBe(false)
    expect(hasActiveFilters('mexican', new Set(), null)).toBe(true)
    expect(hasActiveFilters(null, new Set(['dairy']), null)).toBe(true)
    expect(hasActiveFilters(null, new Set(), 60)).toBe(true)
  })
})

describe('CUISINE_OPTIONS', () => {
  it('is the shipped six', () => {
    expect(CUISINE_OPTIONS).toEqual(['italian', 'mexican', 'asian', 'american', 'indian', 'greek'])
  })
})
```

- [ ] **Step 2: Run to verify it fails**

Run: `cd /home/craigm26/pantryatlas/web && npx vitest run src/lib/filters.test.ts`
Expected: FAIL — module not found.

- [ ] **Step 3: Implement the helper** (`web/src/lib/filters.ts`)

```ts
export const CUISINE_OPTIONS = ['italian', 'mexican', 'asian', 'american', 'indian', 'greek'] as const
export type Cuisine = (typeof CUISINE_OPTIONS)[number]
export const EXCLUDE_OPTIONS = ['meat', 'dairy', 'gluten'] as const
export const TIME_OPTIONS = [30, 60] as const

export function hasActiveFilters(
  cuisine: string | null,
  excludes: Set<string>,
  maxTime: number | null,
): boolean {
  return cuisine != null || excludes.size > 0 || maxTime != null
}

export function buildFilterQuery(
  cuisine: string | null,
  excludes: Set<string>,
  maxTime: number | null,
): string {
  const p = new URLSearchParams()
  if (cuisine) p.set('cuisine', cuisine)
  if (excludes.size) p.set('exclude', [...excludes].join(','))
  if (maxTime != null) p.set('max_time_min', String(maxTime))
  const s = p.toString()
  return s ? `?${s}` : ''
}
```

- [ ] **Step 4: Add filter signals + thread the query into fetches** (`web/src/signals.ts`)

Add near the recipe signals:
```ts
import { buildFilterQuery } from './lib/filters'

export const filterCuisine = signal<string | null>(null)
export const filterExcludes = signal<Set<string>>(new Set())
export const filterMaxTime = signal<number | null>(null)
```
In `fetchRecipes`, append the query to the from-pantry URL:
```ts
    const q = buildFilterQuery(filterCuisine.value, filterExcludes.value, filterMaxTime.value)
    const res = await fetch(`/navigator/recipes/from-pantry${q}`, {
```
In `refineRecipes` (the `/refine` fetch), append the same `q` to that URL too (build it the same way from the signals).

- [ ] **Step 5: Filter bar UI + empty state** (`web/src/pages/Navigator.tsx`)

In the recipes section (`RecipesSection`), above the results list, render a filter bar:
chip row for `CUISINE_OPTIONS` (single-select; tapping the active one clears it),
three "No meat / No dairy / No gluten" toggle chips (subtext: "Hides recipes where we detect these — double-check ingredients"), and time chips "≤30 min / ≤60 min / Any". Each control sets its signal; a `useSignalEffect`/existing recompute re-runs `fetchRecipes`. Use the established token chip styling (mirror `PantryRowActions`/expiry chips). When `recipes.value.length === 0 && recipeLoadState.value === 'done'` and `hasActiveFilters(...)`, show an empty-state block: "No recipes match these filters." + a **"Clear filters"** button that resets all three signals (then re-fetch). Wire the controls so changing any filter triggers the same debounced `fetchRecipes` path the pantry uses.

- [ ] **Step 6: Verify**

Run: `cd /home/craigm26/pantryatlas/web && npx vitest run && npx tsc --noEmit && npm run build`
Expected: vitest green, tsc clean, build OK.

- [ ] **Step 7: Commit**

```bash
git add web/src/lib/filters.ts web/src/lib/filters.test.ts web/src/signals.ts web/src/pages/Navigator.tsx
git commit -m "feat(web): cuisine/diet/time filter bar + empty-state/clear"
```

---

### Final verification (after all tasks)

- [ ] **Full Python suite + lint:** `cd /home/craigm26/pantryatlas && /usr/bin/python3 -m pytest tests/ -q && ruff check pantryatlas/ tests/` — all green.
- [ ] **Full web suite + build:** `cd /home/craigm26/pantryatlas/web && npx vitest run && npx tsc --noEmit && npm run build` — green/clean.
- [ ] **Runtime (Pi, real socket, real recipes.db, TEMP kitchen — never touch `~/.pantryatlas`):**
  1. Pantry + `cuisine=mexican` → eyeball that returned titles read Mexican; confirm every result classifies mexican.
  2. `exclude=meat` → confirm no returned recipe has detected meat.
  3. `max_time_min=30` → confirm no result has an estimate > 30 (unknown-estimate kept).
  4. Force an empty intersection (small pantry + narrow cuisine + `max_time_min=30`) → confirm `[]` (and the UI empty-state/clear path in a quick headless check if feasible).
  5. Perf: from-pantry with filters stays within budget. Real `~/.pantryatlas` untouched.
- [ ] **Finish:** superpowers:finishing-a-development-branch → Option 2 (push + PR). Stop at PR + CI green; do NOT merge (operator merges).
