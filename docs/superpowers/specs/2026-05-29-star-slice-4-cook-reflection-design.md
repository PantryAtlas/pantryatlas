# Star Slice 4 — Cook-reflection capture + history re-rank (Design)

> Final star slice (sequence 1 → 3 → 2 → **4**). Slices 1 (expiry/waste), 3
> (flavor ranking), and 2 (filters) are merged. This slice closes the loop: it
> lets the cook **rate + note** what they made and feeds that history back into
> ranking so recently-cooked dishes sink (variety) and loved dishes rise.

**Date:** 2026-05-29
**Status:** Approved (design Q&A complete; advisor-reviewed; grounded on the real code)

---

## Problem

`cook_events` already has `rating` and `notes` columns, `add_cook_event` already
stores them, and `GET /navigator/meals` already returns them — but **nothing ever
populates them**. The web "I cooked this" button (`handleCooked` →
`cookRecipe({dish_name, servings, consumed})`) never sends a rating or note, and
there is **no way to update an already-logged cook**. Meanwhile ranking has **no
cook-history term at all**: a dish you made last night ranks identically to one
you have never cooked, and a five-star favorite gets no lift. The reflection data
model exists; the capture UI and the feedback loop do not.

## Goal

1. **Capture:** after the existing one-tap log, let the cook optionally rate the
   meal (1–5 stars) and add a short note, attached to the logged cook event.
2. **Re-rank:** nudge pantry→recipe ranking by cook history — **demote
   recently-cooked** dishes and **boost highly-rated** ones — as a small, bounded
   adjustment that leaves the tuned slice 1–3 weights untouched and is a strict
   no-op when there is no history.

## Grounding (drives the design)

- **Join key must be the title.** `_ranked_to_dict` emits only
  `recipe = {title, ingredients, instructions}` — **no id**. `handleCooked` calls
  `cookRecipe` **without** `recipe_id`, so every existing/historical cook event has
  `recipe_id = NULL`. The refine round-trip rebuilds candidates as
  `{title, ingredients, instructions}` (no id). Therefore the only key that can
  match a candidate to its cook history on day one is the **normalized dish title**
  (`" ".join(s.lower().split())`). No `recipe_id` plumbing in v1.
- **The nudge must not break the settle animation.** Slice 3 guarantees `refine`
  can only *lower* scores, so cards settle downward smoothly. A history term present
  in `from-pantry` but absent/different in `refine`, or gated behind the
  `flavor_top_n=250` cap, would make cards *jump* on settle. So the adjustment is a
  cheap title lookup computed for **all** candidates inside the **non-flavor pass**
  (so top-N selection sees it), **identically in both routes**.
- **Empty history is byte-identical to today.** No cook events (or `history_fn=None`)
  → adjustment `0.0` for every candidate → ranking output is unchanged. This keeps
  every existing ranking test green and shrinks the blast radius to "users who have
  cooked things."
- **`ranking.py` stays pure / time-free.** `days_since_last_cook` needs "now";
  injecting a precomputed `history_fn` (title → adjustment) keeps the recency math
  and the wall clock in a separate, fully unit-testable module, mirroring how
  `flavor_fn` is injected.

## Non-goals (deferred)

- No DB migration (columns already exist; history derived at query time).
- No re-weighting of the 0.50/0.20/0.20/0.10 formula (history is a post-weight
  nudge, not a weighted term).
- No `recipe_id` threading through cook POST / refine / `_ranked_to_dict`.
- No per-card "cooked 2d ago / you loved this" explanation badge in v1 (the
  re-rank is behavioral; visible surfaces are the reflection panel + MealLog stars).
  Reconsider once the loop is in use.
- No edit/delete of notes after save beyond re-PATCHing (last write wins).

---

## Design

### A. Capture — one-tap log, then reflect

**A.1 Store (`pantryatlas/store/kitchen.py`)**

```python
def update_cook_event(self, event_id: int, *, rating: int | None = None,
                      notes: str | None = None) -> dict[str, Any] | None:
    """Attach a rating (1–5) and/or note to an existing cook event.

    Only provided (non-None) fields are written; the other is left unchanged.
    Returns the updated event dict, or None if event_id does not exist.
    Raises ValueError if rating is provided and out of 1..5.
    """
```

- Validate `rating` (when not None) is an int in `1..5`; else `ValueError`.
- `SELECT 1 FROM cook_events WHERE id=?`; if absent → return `None` (route → 404).
- Build a dynamic `SET` from the non-None fields; if both are None, return the
  current event unchanged (no-op). Run under `self._lock`.
- Return via the existing `_cook_row_to_dict` shape.

**A.2 API (`pantryatlas/navigator/server.py`)**

```python
class MealReflectIn(BaseModel):
    rating: int | None = None
    notes: str | None = None

@app.patch("/navigator/meals/{meal_id}")
def patch_meal(meal_id: int, body: MealReflectIn) -> dict[str, Any]:
    updated = _get_kitchen(app).update_cook_event(
        meal_id, rating=body.rating, notes=body.notes)
    if updated is None:
        raise HTTPException(status_code=404, detail="meal not found")
    return updated
```

- A `ValueError` from the store (bad rating) → `HTTPException(422)`.
- `post_cook` already returns the created event including its `id`; no change
  needed there beyond confirming the web reads it.

**A.3 Web (`web/`)**

- `signals.ts` `cookRecipe`: return the **created event** (`CookEvent | null`)
  instead of `boolean`, so the card learns the new `id`. Update the one caller.
- `signals.ts` add:
  ```ts
  export async function reflectMeal(id: number, rating: number | null,
                                    notes: string | null): Promise<boolean>
  ```
  POSTs `PATCH /navigator/meals/${id}` with `{rating, notes}`; on success
  `await fetchMeals()`; returns ok.
- `RecipeCard.tsx`: after `setCooked(true)` store `cookedEventId`. Replace the
  static `✓ Logged` terminal state with a compact **reflection panel**:
  - A row of five star buttons (`aria-label="Rate N stars"`, `aria-pressed`),
    a single-line note input (`maxLength` ~140, `aria-label="Add a note"`),
    and **Save** + **Skip** buttons.
  - **Save** → `reflectMeal(cookedEventId, rating, notes||null)`, then collapse to
    a quiet confirmation (e.g. `✓ Logged · ★N`). **Skip** → collapse with no PATCH
    (meal stays logged, rating null). Both keep the card in its `cooked` state
    (button stays disabled; no double-log).
  - Panel is keyboard-operable; the whole thing is optional.
- `MealLog.tsx`: when `m.rating` is set, render the star count; when `m.notes` is
  set, render the note under the dish line. Empty → unchanged.

### B. History re-rank — bounded post-weight nudge

**B.1 Pure module `pantryatlas/navigator/history.py`**

```python
_RECENCY_WINDOW_DAYS = 14
_MAX_PENALTY = 0.05
_MAX_BOOST = 0.05
_MAX_ADJUST = 0.05

def normalize_title(s: str) -> str:
    return " ".join(s.lower().split())

def build_history_adjuster(
    cook_events: list[dict],
    now: datetime,
    *,
    window_days: int = _RECENCY_WINDOW_DAYS,
    max_penalty: float = _MAX_PENALTY,
    max_boost: float = _MAX_BOOST,
    max_adjust: float = _MAX_ADJUST,
) -> Callable[[str], float]:
    """Return title -> bounded score adjustment in [-max_adjust, +max_adjust].

    Pure given `now` (no wall-clock read here). Builds, per normalized title:
      - most-recent cooked_at  -> recency_penalty
      - mean rating over rated cooks -> rating_term
    A title with no cook events -> 0.0 (strict no-op).
    """
```

Per title with ≥1 cook event:
- `days = (now - most_recent_cooked_at).total_days` (clamp ≥ 0).
- `recency_penalty = max_penalty * clamp((window_days - days) / window_days, 0, 1)`
  → cooked today: full `max_penalty`; cooked ≥`window_days` ago: 0.
- `rating_term`: over cooks of this title **with a non-null rating**, take the mean
  `r̄`; `rating_term = max_boost * clamp((r̄ - 3) / 2, -1, 1)` → 5★ → +max_boost,
  3★ → 0, 1★ → −max_boost. **No rated cooks → 0.**
- `adjustment = clamp(rating_term - recency_penalty, -max_adjust, +max_adjust)`.

Parse `cooked_at` (ISO-8601, as written by `_now_iso`); rows with an unparseable
or missing timestamp contribute no recency (treated as `days = ∞` → penalty 0) but
still contribute their rating. Use a per-title precomputed dict so each returned
closure call is an O(1) lookup.

**B.2 `rank_recipes` (`pantryatlas/navigator/ranking.py`)**

- New keyword param `history_fn: Callable[[str], float] | None = None`.
- In the **non-flavor** accumulation, after computing `nonflavor`:
  ```python
  adjustment = history_fn(recipe.get("title", "")) if history_fn else 0.0
  nonflavor = nonflavor + adjustment
  ```
  so the top-N-by-nonflavor flavor selection already accounts for the nudge.
- Final: `score = nonflavor + _W_FLAVOR * flavor`; then **clamp `score` to [0, 1]**
  (the only new clamp; without history it is a no-op since the weighted sum is
  already in range).
- `history_fn is None` → identical to current behavior (regression-tested).

**B.3 Wiring (`server.py`)**

In both `post_recipes_from_pantry` and `post_recipes_refine`, before ranking:
```python
from datetime import datetime, timezone
now = datetime.now(timezone.utc)
adjuster = build_history_adjuster(_get_kitchen(app).list_meals(limit=500), now)
```
Pass `history_fn=adjuster` to the respective `rank_recipes(...)` call. (Bump
`list_meals` limit to 500 for this read so the adjuster sees enough history;
existing `GET /navigator/meals` default stays 50.)

---

## Data flow

```
cook → POST /navigator/cook  → returns {id, ...}
   web stores cookedEventId, reveals reflection panel
reflect (optional) → PATCH /navigator/meals/{id} {rating, notes}
   → update_cook_event → fetchMeals (MealLog shows ★ + note)

next from-pantry / refine:
   now = utcnow()
   adjuster = build_history_adjuster(list_meals(500), now)
   rank_recipes(..., history_fn=adjuster)
     non-flavor score += clamp(rating_term - recency_penalty, ±0.05)
     (all candidates; both routes; top-N flavor selection sees it)
   → recently-cooked sink, loved rise; no history → unchanged
```

## Error handling / edge cases

- `PATCH` unknown `meal_id` → 404; rating out of 1..5 → 422; both fields null →
  no-op returns current event (200).
- `cookRecipe` network failure → returns `null`; card does not enter reflect state.
- Unparseable `cooked_at` → no recency penalty, rating still counts.
- `history_fn=None` or empty cook log → ranking byte-identical to today.
- Final score clamp guarantees `score ∈ [0, 1]` even at the nudge extremes.

## Testing

**Python (`/usr/bin/python3 -m pytest`):**
- `tests/navigator/test_history.py` (pure, injected `now`):
  - empty events → adjuster returns 0.0 for any title;
  - title normalization (`"Beef Tacos"` vs `" beef   tacos "` collide);
  - recency: cooked `now` → `-max_penalty` (no rating); cooked `window_days` ago
    → ~0; cooked beyond window → 0;
  - rating: 5★ (cooked long ago) → `+max_boost`; 1★ → `-max_boost`; 3★ → 0;
    unrated → 0 rating_term;
  - combined clamp: 5★ cooked today → `clamp(boost - penalty, ±max_adjust)`;
  - unparseable `cooked_at` → no penalty, rating still applies.
- `tests/navigator/test_ranking.py`: **regression** — `rank_recipes(...)` with
  `history_fn=None` returns identical scores/order to before; with a stub
  `history_fn` that boosts one title, that recipe's score rises by the boost and
  ordering reflects it; score stays ≤ 1.0 at the boost ceiling.
- `tests/navigator/test_kitchen_store.py`: `update_cook_event` happy path (rating
  + notes), partial (notes only leaves rating), unknown id → None, bad rating
  (0 / 6 / non-int) → ValueError.
- `tests/navigator/test_server.py`: `PATCH /navigator/meals/{id}` updates + returns
  the event; unknown id → 404; bad rating → 422; and a from-pantry call after
  seeding a recent cook of a candidate's title returns that candidate with a lower
  score than the same call with no history (history demotes).

**Web (vitest):** a pure helper for the reflection panel state if extracted
(`buildReflectPayload(rating, notes)` → `{rating, notes|null}`, empty note → null);
`cookRecipe` returns the event shape (mocked fetch). Keep logic in small testable
units.

**Runtime (Pi, real socket, real recipes.db, TEMP kitchen — never touch real
`~/.pantryatlas`):**
- Seed 2–3 cooks against a temp kitchen with varying rating + recency (one cooked
  "now" highly rated, one cooked recently unrated, one old 5★). Call from-pantry
  with a pantry that surfaces those dish titles as candidates; confirm the recent
  one sinks, the old-loved one rises, vs a baseline call against an empty kitchen.
- PATCH a logged meal, GET /navigator/meals, confirm rating + note persisted.
- Confirm empty-history from-pantry equals the pre-slice ordering for the same
  pantry (no-op proof).

**Deploy to pi-nas for testing (`pantrydev`, :8090):** after CI-green + PR, push
via the existing `ops/dev/pa-deploy.sh` runbook (`pip install -e .` is load-bearing
for the PWA; rebuild `web/dist` each push). Smoke the reflection panel + a seeded
re-rank on the deployed node.

## Out-of-scope reminders for the implementer

- Join on **normalized title**, not `recipe_id` (existing events have NULL id).
- History adjustment computed for **all** candidates in the **non-flavor** pass,
  **identically in both routes**; empty/None history must be a **strict no-op**.
- Keep `ranking.py` pure — `now` is injected via `build_history_adjuster`.
- Do not re-weight the 0.50/0.20/0.20/0.10 formula; clamp final score to [0,1].
- Subagents use **specific `git add <paths>`**, never `git add -A`.
- Any new `import X` needs `X` in `pyproject` deps; any new data file must be
  committed (slice-3 CI lesson). This slice adds **no** new deps or data files
  (stdlib `datetime`/`re` only).
- Stop at **PR + CI green**; operator merges.
