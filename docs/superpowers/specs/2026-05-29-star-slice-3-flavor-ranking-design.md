# Star Slice 3 — FlavorDB Compound-Overlap Ranking (Design)

> Third of the four star slices (sequence 1 → **3** → 2 → 4) building the
> "delicious recipes one tap away" north star. Slice 1 (expiry/waste) and its
> guard are merged. This slice finally **consumes the dormant `compounds.parquet`**
> (935 FlavorDB food entities) to make the ranker surface recipes that *taste*
> cohesive, not just ones you can cover.

**Date:** 2026-05-29
**Status:** Approved (design Q&A complete; grounded on the real data; advisor-reviewed)

---

## Problem

The "delicious" half of the north star is unbuilt. `pantryatlas/data/compounds.parquet`
(935 FlavorDB food entities, each with a `molecules_json` list of flavor molecules)
has **zero query-time consumers**. The ranker's flavor-adjacent term, `cultural_fit`
(weight 0.10), is a title-substring stub fed `cuisine=None` → it contributes 0 to
every score. So ranking is purely "can I make it / before it spoils," never "will
it taste good."

The food-pairing hypothesis (Ahn et al. 2011): two foods that share many flavor
molecules tend to pair well (in the Western culinary tradition). We use FlavorDB's
per-entity molecule sets to compute a **flavor sub-score** and give it the 0.10
weight currently wasted on `cultural_fit`.

## Goal

Add one **flavor sub-score** in `[0, 1]`, a *blend* of:
- **cohesion** — do the recipe's own ingredients share flavor molecules (a
  pantry-independent "well-composed dish" prior), and
- **affinity** — do the recipe's *non-pantry* ingredients pair with what's in the
  pantry ("tastes good with what I have"),

wire it into `rank_recipes` at weight **0.10** (taking over `cultural_fit`'s weight),
run it in **both** fast and refine mode, and surface a subtle "great pairing" badge
on recipe cards. No new dependencies (pandas already loads the parquet).

## Grounding (measured on the real 49,965-recipe DB + the parquet)

- Recipe `ingredients_json` are **noisy phrases** (`"ribs celery"`,
  `"can parmesan cheese"`), so exact-match lookup hits **1%**. A head-noun + token
  matcher reaches **~73% occurrence-weighted**; **97%** of recipes get ≥2 mapped
  entities (cohesion defined). Mean mapped-ingredient fraction/recipe ≈ **0.71**.
- **cohesion** distribution (mean-of-all-pairs Jaccard): p25 0.151, median 0.193,
  p75 0.244, p95 0.376.
- **affinity (fixed)** distribution (non-pantry recipe entities, best Jaccard to
  pantry entities): p25 0.166, median 0.245, p75 0.333, p95 0.494 — **comparable
  scale to cohesion**, so a 0.5/0.5 blend is balanced.
- **Self-match bug avoided:** affinity that includes pantry∩recipe entities
  correlates with coverage at **r=0.320** (it would just be re-counting coverage).
  The fixed affinity (exclude pantry entities / equal-entity pairs) correlates at
  **r=0.013** — genuinely orthogonal to coverage. **We use the fixed affinity.**
- **Perf:** a realistic 10-item pantry → **15,071** `iter_overlapping` candidates;
  flavor over *all* of them is **2.04s** — over the ~1s instant-paint budget. → the
  design caps flavor compute to the **top-N by non-flavor score** (see Perf below).

## Non-goals (deferred)

- `slerp.py` / `modes.py` (embedding-vector morphing) — a *different* dormant
  feature, not consumed here.
- Cuisine/diet/time filtering — that's **slice 2**. `cultural_fit` is kept as a
  reported field (weight 0) so slice 2 can revive it.
- Re-ingesting `recipes.db` to precompute a flavor column — query-time + caching is
  fast enough with the top-N cap; no migration of the shipped artifact.
- Correcting the Western-pairing bias of shared-compound matching — documented, not
  corrected, for v1.

---

## Design

### A. New module `pantryatlas/flavor/`

Mirrors `pantryatlas/geometry/`. Lazily loaded like the other stores so importing
the navigator stays side-effect-free (no parquet read at import).

**`pantryatlas/flavor/store.py` — `FlavorStore`:**

Construction loads `compounds.parquet` once and builds:
- `self._ent_mol: dict[int, frozenset[int]]` — entity_id → set of molecule
  `pubchem_id`s.
- `self._name2id: dict[str, int]` — normalized name → entity_id. Built from each
  entity's `compound_name` (lowercased, plus a crude singular when it ends in `s`),
  **longest/most-specific names registered so multiword entities win** (e.g.
  `"cream cheese"`, `"sweet potato"`, `"peanut butter"` are real entities).
- A small curated **`_ALIASES`** map and **`_BLOCKLIST`** set (see Matcher).

Methods (all pure, deterministic):

```python
def entity_for(self, phrase: str) -> int | None
def jaccard(self, e1: int, e2: int) -> float          # |∩| / |∪|, memoized
def cohesion(self, phrases: list[str]) -> float | None
def affinity(self, recipe_phrases: list[str], pantry_names: list[str]) -> float | None
def flavor_score(self, recipe_phrases: list[str], pantry_names: list[str]) -> float
```

A module-level lazy singleton + a `flavor_fn` factory the server injects into
`rank_recipes` (see C).

### B. The matcher — `entity_for` (the real work)

Order of attempts (first hit wins), with a per-string `@lru_cache`:
1. **Exact** normalized phrase in `_name2id`.
2. **Curated alias** in `_ALIASES` (e.g. handcrafted fixes for common foods).
3. **Blocklist** → return `None` (non-foods / known-bad: `"baking soda"`,
   `"baking powder"`, `"cream of tartar"`, …).
4. **Longest token-subsequence** entity name appearing as consecutive tokens in the
   phrase (so `"cream cheese"`→Cream Cheese, not Cream).
5. **Head noun** (last token) — **unless** it is in a generic-modifier **stoplist**
   `{milk, sauce, cream, oil, juice, syrup, powder, butter}`, in which case try the
   *modifier* token(s) first (so `"coconut milk"`→Coconut, `"almond milk"`→Almond,
   `"almond butter"`→Almond), then fall through to the head noun (so plain
   `"butter"`/`"milk"` with no modifier still map to Butter/Milk; multiword entities
   like `"peanut butter"`/`"cream cheese"` are already caught at step 4). The exact
   stoplist is tuned against the precision fixture (Testing).
6. **Any token** in `_name2id`.
7. Else `None`.

The stoplist/aliases/blocklist are tuned against a **30-phrase precision fixture**
(a test, see Testing) — known-good mappings asserted, known-bad asserted to `None`
or the correct modifier. Coverage (~73%) is already validated; this step fixes
*precision* so the "great pairing" badge is never embarrassing.

### C. Metrics

- **`jaccard(e1, e2)`** = `|m1 ∩ m2| / |m1 ∪ m2|` (0 if either set empty). Memoized
  on the sorted id pair.
- **`cohesion(phrases)`**: map → entities, drop `None`, **dedup**. If `<2` distinct
  entities → `None`. Else mean pairwise Jaccard over all unique pairs. Pantry-
  independent → memoizable per recipe.
- **`affinity(recipe_phrases, pantry_names)`**:
  - `pantry_entities = {entity_for(n) for n in pantry_names} − {None}`
  - `recipe_entities = dedup(non-None entity_for(p) for p in recipe_phrases)`
  - `non_pantry = [e for e in recipe_entities if e not in pantry_entities]`
  - If `non_pantry` empty **or** `pantry_entities` empty → `None`.
  - Else mean over `e ∈ non_pantry` of `max(jaccard(e, pe) for pe ∈ pantry_entities)`.
- **`flavor_score(...)`** = blend, both in `[0,1]`:
  - both `None` → **`0.0`** (missing data = no bonus, never a penalty; max foregone
    is ~0.05 at weight 0.10).
  - one `None` → the other.
  - both present → `0.5 * cohesion + 0.5 * affinity`.

### D. Ranking integration (`ranking.py` stays pure)

Add an injected parameter, mirroring `embed_fn`:

```python
def rank_recipes(..., flavor_fn: Callable[[list[str], list[str]], float] | None = None,
                 flavor_top_n: int = 250, ...) -> list[RankedRecipe]:
```

- `RankedRecipe` gains `flavor: float = 0.0`. `cultural_fit` is **kept** (still
  computed/reported) but its **weight becomes 0**; the 0.10 weight moves to flavor:

  ```
  score = 0.50*coverage + 0.20*expiration_urgency
        + 0.20*(1 - substitution_penalty) + 0.10*flavor
  ```
  (`_W_CULTURAL = 0.0`, new `_W_FLAVOR = 0.10`.)

- **When `flavor_fn is None`** → `flavor = 0.0` for all (back-compat: identical to
  today's behavior whenever `cuisine` was None, which is every production call).

- **Top-N cap (perf):** when `flavor_fn` is set, compute the provisional non-flavor
  score for every candidate, select the **top `flavor_top_n`** by it, compute
  `flavor` only for those (others stay `0.0`), then final-sort by full score. A
  0.10 tie-breaker cannot lift a recipe ranked below ~#250-by-coverage into the
  returned top-20, so this is correct; **`log`/return a note when the cap clips**
  (no silent truncation). In refine mode the candidate set is already ≤ the client's
  painted page, so all of them get flavor.

- Flavor is **identical across fast and refine** (only `substitution_penalty`
  changes on refine), so the "scores only ever drop on refine → cards settle
  downward" animation is preserved.

### E. Server wiring (`server.py`)

- Lazy `FlavorStore` accessor `_get_flavor(app)` (factory pattern like
  `_get_kitchen`); production factory loads `pantryatlas/data/compounds.parquet`.
- `post_recipes_from_pantry` (fast) and `post_recipes_refine` build
  `flavor_fn = lambda ings, pantry: _get_flavor(app).flavor_score(ings, pantry)` and
  pass it to `rank_recipes`. Pantry names = `[i.canonical_name for i in on_hand()]`.
- `_ranked_to_dict` adds `"flavor": r.flavor`.

### F. UI (`web/`) — subtle badge

- `RankedRecipe` wire type gains `flavor?: number`.
- On a recipe card, show a small **"great pairing"** chip (token-styled, like the
  existing chips) when `flavor >= FLAVOR_BADGE_THRESHOLD`. Default threshold **0.30**
  (≈ top quartile of the blended distribution; tunable). Pure, no new state.

---

## Data flow

```
from-pantry (fast):
  pantry on_hand → canonical names
  iter_overlapping → ~15k candidates
  rank_recipes(flavor_fn=…):
    pass 1: coverage, expiry  (all candidates)
    select top-250 by non-flavor score   ← perf cap (logged if clipped)
      flavor_fn(recipe_ings, pantry_names) for those:
        entity_for (cached) → cohesion (memoized) + affinity (fixed)
        → 0.5/0.5 blend  (others flavor=0)
    final score+sort → top 20  → API includes "flavor"
  card shows "great pairing" when flavor ≥ 0.30
```

## Error handling / edge cases

- Unmapped ingredients → `entity_for` returns `None`, silently skipped; <2 mapped →
  cohesion `None`; empty pantry → affinity `None`; both `None` → flavor 0.0.
- `flavor_fn is None` (tests, any non-wired caller) → flavor 0.0, scores unchanged.
- Parquet missing/corrupt at factory time → surface a clear error from the factory
  (don't crash import); the route returns 500 only if flavor is actually requested.
  (v1: assume the bundled parquet is present, as today.)

## Testing

**Python (`/usr/bin/python3 -m pytest`):**
- `tests/flavor/test_store.py`:
  - **Matcher precision fixture** (~30 phrases): assert exact (`garlic`→Garlic),
    multiword (`cream cheese`→Cream Cheese, `sweet potato`→Sweet Potato), modifier-
    over-generic (`coconut milk`→Coconut, `almond milk`→Almond), blocklist
    (`baking soda`→None, `cream of tartar`→None), head-noun (`ribs celery`→Celery).
  - `jaccard`: identical sets→1.0, disjoint→0.0, known partial; symmetric; empty→0.
  - `cohesion`: <2 mapped → None; ≥2 → mean pairwise in [0,1].
  - `affinity`: excludes pantry/equal entities (a recipe that only repeats pantry
    items → None, NOT 1.0); non-pantry pairing in [0,1]; empty pantry → None.
  - `flavor_score`: both None→0.0; one None→other; both→0.5/0.5 blend.
  - Lazy singleton loads the real parquet (1 integration test).
- `tests/navigator/test_ranking.py`:
  - New: with a fake `flavor_fn`, flavor reorders two recipes that tie on coverage.
  - New: `flavor_fn=None` → scores identical to pre-slice behavior (back-compat).
  - New: top-N cap — with `flavor_top_n=1`, only the top candidate gets flavor>0.
  - **Update** any existing test that asserted `cultural_fit`'s *score* contribution
    (now weight 0) — intentional change; `cultural_fit` field still reported.
- `tests/navigator/test_server.py`: `from-pantry` response includes a numeric
  `flavor` field; wiring smoke.

**Web (vitest, node):** `flavor` flows through the wire type; a pure
`shouldShowPairingBadge(flavor)` helper (threshold) is unit-tested.

**Runtime (Pi, real socket, real recipes.db, TEMP kitchen):**
- Benchmark `from-pantry` with flavor wired over the real ~15k-candidate set →
  confirm **instant paint stays within budget** with the top-N cap (target < ~1.2s).
- Capture a before/after ordering where flavor visibly promotes a more cohesive
  recipe among coverage-ties.
- Confirm the "great pairing" badge renders for high-flavor cards.
- Real `~/.pantryatlas` untouched (tmp kitchen + read-only recipes.db).

## Out-of-scope reminders for the implementer

- Do **not** consume `slerp.py`/`modes.py`. Do **not** touch the cuisine/filter path
  (slice 2). Do **not** re-ingest `recipes.db`.
- Subagents use **specific `git add <paths>`**, never `git add -A`.
- Keep `ranking.py` pure — flavor enters only via the injected `flavor_fn`.
- Stop at **PR + CI green**; operator merges.
