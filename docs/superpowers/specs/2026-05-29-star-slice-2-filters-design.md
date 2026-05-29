# Star Slice 2 — Cuisine / Diet / Time Filters (Design)

> Fourth and final star slice executed (sequence 1 → 3 → **2** → 4). Slices 1
> (expiry/waste) and 3 (flavor ranking) are merged. This slice adds query-time
> **filtering** of the from-pantry results by cuisine, diet (detection-based), and
> estimated time — all derived from unstructured recipe text (no DB migration).

**Date:** 2026-05-29
**Status:** Approved (design Q&A complete; grounded on the real 50k DB; advisor-reviewed)

---

## Problem

`recipes_meta` has only `id, title, language, ingredients_json, instructions` — **no
cuisine, diet, or cook-time columns**. The `cuisine` param is plumbed into
`rank_recipes` but inert (its `cultural_fit` term is a title-substring stub now at
weight 0, after slice 3 took the 0.10 for flavor). The web has **no filter UI at
all**. So users can't narrow "recipes I can cook" by the axes they actually think in.

## Goal

Let the operator filter the from-pantry results by **cuisine** (single select),
**diet excludes** (hide recipes containing detected meat / dairy / gluten), and
**max time** (≤30 / ≤60 / any). All facets are **derived at query time** from
title + ingredients + instructions via a pure, in-module classifier. Filters are a
**hard pre-filter** applied to candidates before ranking + top-k truncation.

## Grounding (measured on the real DB; drives the design)

- **Cuisine** needs precision-curated keywords. The naive set over-tagged "french"
  at 33% (generic "butter"). Curated, distinctive-marker sets eyeball as: **Mexican**
  (taco/tortilla/salsa) and **American** (meatloaf/cornbread/brisket) clean;
  **Italian** good (parmesan/mozzarella leak slightly); **Asian** mostly clean
  (stir-fry/teriyaki/hoisin); **Indian** noisy unless tightened to unambiguous markers
  (paneer/tikka/masala/naan/tandoori — drop curry-powder/ghee/basmati); **Greek**
  precise but thin; **Thai** bad (coconut-milk → smoothies/pies) and **French** thin
  → **both dropped for v1**. Ship the set that passes an eyeball precision bar.
- **Diet**: exclusion-by-detection only. Naive "no-meat" tags 68%, "no-gluten" 53%
  — these OVER-claim and a wrong "gluten-free"/"vegan" badge is a safety/ethics issue.
  So diet is reframed as **"hide recipes where we detect meat / dairy / gluten,"** a
  transparent best-effort filter, **never a dietary guarantee**.
- **Time**: 67% of recipes state explicit durations (median ~40 min). Extractable.
  But SUM over-counts passive time ("Strawberry Pie": 4min + 2hr + 8hr-chill = 604).
  So the estimate is honestly **total time including chilling/baking**; coarse buckets
  absorb the error; "every N minutes" frequency matches are ignored.
- **Empty results are common**: italian∩≤30min ≈ 252, indian∩≤30min ≈ 42 *before*
  pantry-overlap. Intersecting filters + a small pantry can return zero → an
  **empty-state + one-tap clear-filters is required**.

## Non-goals (deferred)

- No DB migration / re-ingest (facets derived at query time).
- No ranking-weight change. Cuisine is a **pre-filter**, not a score term.
  `cultural_fit` stays a reported field at weight 0; **stop passing `cuisine` into
  `rank_recipes`** so there aren't two half-classifiers (drop the cultural_fit pretense).
- No dietary *certification* — only detection-based hiding.
- No Thai/French cuisines in v1 (insufficient precision/volume in this corpus).

---

## Design

### A. New module `pantryatlas/navigator/facets.py` (pure, in-module constants)

All keyword/marker lists are **hardcoded Python constants** (no data file → no
dependency or shipping gap, learned from slice 3's two CI failures).

```python
CUISINES: dict[str, list[str]]   # cuisine -> distinctive markers (curated)
MEAT_MARKERS, DAIRY_MARKERS, GLUTEN_MARKERS: list[str]
```

**v1 shipped cuisine set:** `italian, mexican, asian, american, indian, greek`
(Thai + French dropped — insufficient precision/volume; Indian tightened to
unambiguous markers only). The eyeball precision fixture (Testing) is the gate — any
cuisine whose tagged sample doesn't read as plausibly that cuisine is dropped before
merge, and the UI chip list is generated from `CUISINES.keys()` so it stays in sync.

Functions:
- `classify_cuisine(title: str, ingredients: list[str]) -> str | None`
  - Lowercase `title + " " + " ".join(ingredients)`; return the cuisine whose markers
    appear, **most markers wins** (ties → a fixed priority order); `None` if none.
    Precision-first: a recipe with no distinctive marker is `None` (unclassified).
- `detect_excludes(ingredients: list[str]) -> set[str]`
  - Returns the subset of `{"meat", "dairy", "gluten"}` whose markers are detected in
    the ingredient list.
- `estimate_time_min(instructions: str) -> int | None`
  - Regex-sum stated durations (minutes/hours, ranges "30 to 40" counted once, hours
    ×60, "overnight"→480). **Skip durations preceded by "every"** (frequency, not
    duration). `None` when no duration is stated. Documented as a rough **total**
    estimate incl. passive time.

### B. Filtering — `pantryatlas/navigator/filtering.py` (or inline helper)

```python
def passes_filters(recipe: dict, *, cuisine: str | None,
                   exclude: set[str], max_time_min: int | None) -> bool
```
- **Cuisine (strict):** if `cuisine` set, keep only recipes where
  `classify_cuisine(...) == cuisine`. Unclassified and other-cuisine recipes are
  **hidden** (the user chose strict).
- **Diet excludes:** if `exclude` non-empty, hide the recipe when
  `detect_excludes(ingredients) & exclude` is non-empty.
- **Time:** if `max_time_min` set, hide the recipe only when its estimate is **known
  and exceeds** the cap. **Recipes with no estimate are KEPT** (never hide on missing
  data).

Applied in `post_recipes_from_pantry` to the `iter_overlapping` candidate list
**before** `rank_recipes` (so ranking + top-k operate on the filtered set and you get
a full page when possible). Same filtering in `post_recipes_refine`.

### C. API (`server.py`)

Extend both routes (replacing the inert `cuisine`-only param):
- `post_recipes_from_pantry(cuisine: str | None = None, exclude: str = "", max_time_min: int | None = None)`
  - `exclude` is a comma-separated string (e.g. `"meat,gluten"`) parsed to a set —
    simplest for a GET/POST query param; validated against `{"meat","dairy","gluten"}`
    (unknown values ignored).
- `post_recipes_refine(...)` gains the same three params.
- **Stop passing `cuisine=` into `rank_recipes`** (cuisine handled by the pre-filter).

### D. Web (`web/`)

A **filter bar** above the recipe results (`Navigator.tsx` recipes section):
- **Cuisine**: a single-select chip row of the shipped cuisines + "All".
- **Diet**: three toggle chips — "No meat" / "No dairy" / "No gluten". Tooltip/subtext:
  **"Hides recipes where we detect these — double-check ingredients yourself."** Never
  the words "vegan"/"gluten-free" as a guarantee.
- **Time**: chips "≤30 min" / "≤60 min" / "Any". Subtext: time is **estimated**.
- New signals `filterCuisine`, `filterExcludes`, `filterMaxTime` + a derived
  `filterParams`; `fetchRecipes`/from-pantry calls include them; changing any filter
  re-fetches (debounced like the pantry-driven refetch).
- **Empty state** when the filtered result set is empty: a clear message
  ("No recipes match these filters") + a **"Clear filters"** button that resets all
  three. Required — intersecting filters frequently yield zero.
- Optionally show the estimated time on a card via `estimate_time_min` (already have
  `cook_time_min` slot in `RankedRecipe`/card) — minor, can reuse the chip line.

---

## Data flow

```
user sets filters → signals → from-pantry POST (cuisine, exclude, max_time_min)
  iter_overlapping (pantry) → passes_filters(each candidate):
     cuisine strict (classify_cuisine == selected)
     diet  (detect_excludes ∩ selected == ∅)
     time  (estimate known and ≤ max, else keep)
  → rank_recipes (NO cuisine arg) → top-k → results
  empty? → empty-state + Clear filters
```

## Error handling / edge cases

- Unknown `exclude` tokens → ignored (validated subset).
- `classify_cuisine` `None` → hidden under a cuisine filter (strict), shown when "All".
- `estimate_time_min` `None` → kept under any time cap.
- All filters off → identical to today's from-pantry.
- Empty filtered set → 200 with `[]`; UI shows empty-state (not an error).

## Testing

**Python (`/usr/bin/python3 -m pytest`):**
- `tests/navigator/test_facets.py`:
  - **Cuisine eyeball/precision fixture**: assert distinctive titles classify right
    (`"Chicken Tikka Masala"`→indian, `"Beef Tacos"`→mexican, `"Spaghetti Carbonara"`
    →italian, `"BBQ Brisket"`→american) and that a generic recipe (`"Buttered Toast"`)
    → `None` (no butter→french). Pin the **shipped cuisine set**.
  - `detect_excludes`: chicken→{meat}; milk+cheese→{dairy}; flour/soy-sauce→{gluten};
    a produce-only recipe → ∅.
  - `estimate_time_min`: "bake 30 minutes"→30; "1 hour"→60; "30 to 40 minutes"→~35
    (range once, not 70); "stir every 2 minutes" → not counted; no-time → None.
- `tests/navigator/test_filtering.py` (or in test_server.py):
  - `passes_filters`: strict cuisine hides unclassified + other-cuisine; diet hides on
    detection; time keeps unknown, hides known-over-cap; all-off keeps everything.
- `tests/navigator/test_server.py`: from-pantry honors `cuisine`/`exclude`/
  `max_time_min`; unknown exclude ignored; empty filtered set → `[]` (200).

**Web (vitest):** a pure `buildFilterQuery(cuisine, excludes, maxTime)` helper +
`isFilterActive`/clear logic unit-tested; the cuisine list constant pinned.

**Runtime (Pi, real socket, real recipes.db, TEMP kitchen):**
- A pantry + each filter: confirm cuisine results look right (eyeball titles), diet
  excludes drop detected recipes, time cap drops long recipes + keeps unknown.
- Trigger an **empty** intersection → confirm `[]` + (in a quick UI check) the
  empty-state/clear path. Perf: filtering is cheap string ops; confirm from-pantry
  stays within budget. Real `~/.pantryatlas` untouched.

## Out-of-scope reminders for the implementer

- Keyword/marker lists are **in-module constants** — no data file.
- Cuisine is a **pre-filter**; do NOT re-weight `cultural_fit` or re-introduce
  `cuisine` into `rank_recipes`.
- Diet copy is **detection-framed**, never a guarantee (no "vegan"/"gluten-free" as a
  claim).
- Drop any cuisine that can't pass the eyeball precision fixture (Thai/French already
  dropped; tighten Indian to unambiguous markers).
- Subagents use **specific `git add <paths>`**, never `git add -A`.
- Stop at **PR + CI green**; operator merges.
