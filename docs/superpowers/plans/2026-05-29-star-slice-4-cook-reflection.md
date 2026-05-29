# Star Slice 4 — Cook-reflection capture + history re-rank Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Let cooks rate + note what they made, and feed that history back into pantry→recipe ranking (recently-cooked sink, loved rise) as a bounded, no-op-when-empty nudge.

**Architecture:** A new pure `history.py` builds a `title → adjustment` closure from the cook log + an injected `now`; `rank_recipes` adds the adjustment in its non-flavor pass (both routes, all candidates); the web adds an optional star/note reflection panel after the existing one-tap log, persisted via a new `PATCH /navigator/meals/{id}`. Backend storage already exists.

**Tech Stack:** Python 3.11 (FastAPI, stdlib `datetime`/`re`, numpy), Preact + `@preact/signals`, SQLite. Tests: pytest (`/usr/bin/python3 -m pytest`), vitest (`cd web && npx vitest run`).

---

### Task 1: Pure history-adjuster module

**Files:**
- Create: `pantryatlas/navigator/history.py`
- Test: `tests/navigator/test_history.py`

- [ ] **Step 1: Write the failing tests**

```python
# tests/navigator/test_history.py
from __future__ import annotations

from datetime import datetime, timedelta, timezone

from pantryatlas.navigator.history import build_history_adjuster, normalize_title

NOW = datetime(2026, 5, 29, 12, 0, 0, tzinfo=timezone.utc)


def _evt(title, *, days_ago=0.0, rating=None):
    cooked = (NOW - timedelta(days=days_ago)).isoformat()
    return {"dish_name": title, "cooked_at": cooked, "rating": rating}


def test_normalize_title_collapses_case_and_space():
    assert normalize_title("Beef Tacos") == normalize_title("  beef   tacos ")


def test_empty_history_is_noop():
    adj = build_history_adjuster([], NOW)
    assert adj("anything") == 0.0


def test_recency_cooked_now_full_penalty_no_rating():
    adj = build_history_adjuster([_evt("Stew", days_ago=0.0)], NOW)
    assert adj("Stew") == -0.05  # full max_penalty, no rating term


def test_recency_decays_to_zero_at_window():
    adj = build_history_adjuster([_evt("Stew", days_ago=14.0)], NOW)
    assert abs(adj("Stew")) < 1e-9


def test_recency_beyond_window_zero():
    adj = build_history_adjuster([_evt("Stew", days_ago=30.0)], NOW)
    assert adj("Stew") == 0.0


def test_rating_five_old_is_full_boost():
    adj = build_history_adjuster([_evt("Cake", days_ago=30.0, rating=5)], NOW)
    assert abs(adj("Cake") - 0.05) < 1e-9


def test_rating_one_old_is_full_penalty():
    adj = build_history_adjuster([_evt("Gruel", days_ago=30.0, rating=1)], NOW)
    assert abs(adj("Gruel") - (-0.05)) < 1e-9


def test_rating_three_is_neutral():
    adj = build_history_adjuster([_evt("Meh", days_ago=30.0, rating=3)], NOW)
    assert abs(adj("Meh")) < 1e-9


def test_unrated_contributes_no_rating_term():
    adj = build_history_adjuster([_evt("Plain", days_ago=30.0, rating=None)], NOW)
    assert adj("Plain") == 0.0


def test_combined_clamped_to_max_adjust():
    # 5-star cooked today: boost(+0.05) - penalty(0.05) = 0.0, still within clamp
    adj = build_history_adjuster([_evt("Fave", days_ago=0.0, rating=5)], NOW)
    assert abs(adj("Fave")) < 1e-9


def test_mean_rating_over_multiple_cooks():
    evts = [_evt("Soup", days_ago=30.0, rating=5), _evt("Soup", days_ago=30.0, rating=1)]
    adj = build_history_adjuster(evts, NOW)  # mean 3 -> neutral
    assert abs(adj("Soup")) < 1e-9


def test_unparseable_cooked_at_no_penalty_keeps_rating():
    evts = [{"dish_name": "X", "cooked_at": "not-a-date", "rating": 5}]
    adj = build_history_adjuster(evts, NOW)
    assert abs(adj("X") - 0.05) < 1e-9  # no recency, full boost


def test_title_match_is_normalized():
    adj = build_history_adjuster([_evt("Beef Tacos", days_ago=0.0)], NOW)
    assert adj("  BEEF   tacos ") == -0.05
```

- [ ] **Step 2: Run tests to verify they fail**

Run: `/usr/bin/python3 -m pytest tests/navigator/test_history.py -q`
Expected: FAIL (`ModuleNotFoundError: pantryatlas.navigator.history`).

- [ ] **Step 3: Write the implementation**

```python
# pantryatlas/navigator/history.py
"""Cook-history → bounded ranking adjustment (slice 4).

Pure and time-free: callers inject ``now``. Builds, per normalized dish title, a
small additive score nudge that demotes recently-cooked dishes and boosts
highly-rated ones. A title with no cook events yields exactly ``0.0`` so ranking
is byte-identical to no-history behavior.
"""
from __future__ import annotations

from collections.abc import Callable
from datetime import datetime

_RECENCY_WINDOW_DAYS: int = 14
_MAX_PENALTY: float = 0.05
_MAX_BOOST: float = 0.05
_MAX_ADJUST: float = 0.05


def normalize_title(s: str) -> str:
    """Lowercase + collapse internal whitespace (the cook-event join key)."""
    return " ".join(s.lower().split())


def _clamp(x: float, lo: float, hi: float) -> float:
    return lo if x < lo else hi if x > hi else x


def build_history_adjuster(
    cook_events: list[dict],
    now: datetime,
    *,
    window_days: int = _RECENCY_WINDOW_DAYS,
    max_penalty: float = _MAX_PENALTY,
    max_boost: float = _MAX_BOOST,
    max_adjust: float = _MAX_ADJUST,
) -> Callable[[str], float]:
    """Return ``title -> adjustment`` in ``[-max_adjust, +max_adjust]``.

    Pure given ``now``. Per normalized title: recency penalty from the most-recent
    ``cooked_at`` (full ``max_penalty`` if cooked now, 0 at/after ``window_days``),
    and a rating term from the mean of *rated* cooks (5 -> +max_boost, 3 -> 0,
    1 -> -max_boost). Unparseable/missing ``cooked_at`` contributes no penalty but
    its rating still counts. Titles with no events map to ``0.0``.
    """
    # title -> [min_days_ago_or_None, sum_rating, n_rated]
    agg: dict[str, list] = {}
    for ev in cook_events:
        title = normalize_title(str(ev.get("dish_name", "")))
        if not title:
            continue
        slot = agg.setdefault(title, [None, 0.0, 0])
        raw = ev.get("cooked_at")
        days: float | None = None
        if isinstance(raw, str):
            try:
                cooked = datetime.fromisoformat(raw)
                days = max(0.0, (now - cooked).total_seconds() / 86400.0)
            except ValueError:
                days = None
        if days is not None and (slot[0] is None or days < slot[0]):
            slot[0] = days
        rating = ev.get("rating")
        if isinstance(rating, (int, float)) and rating is not None:
            slot[1] += float(rating)
            slot[2] += 1

    adjustments: dict[str, float] = {}
    for title, (min_days, sum_rating, n_rated) in agg.items():
        if min_days is None:
            recency_penalty = 0.0
        else:
            recency_penalty = max_penalty * _clamp(
                (window_days - min_days) / window_days, 0.0, 1.0
            )
        if n_rated:
            mean = sum_rating / n_rated
            rating_term = max_boost * _clamp((mean - 3.0) / 2.0, -1.0, 1.0)
        else:
            rating_term = 0.0
        adjustments[title] = _clamp(rating_term - recency_penalty, -max_adjust, max_adjust)

    def adjuster(title: str) -> float:
        return adjustments.get(normalize_title(title), 0.0)

    return adjuster
```

- [ ] **Step 4: Run tests to verify they pass**

Run: `/usr/bin/python3 -m pytest tests/navigator/test_history.py -q`
Expected: PASS (13 tests).

- [ ] **Step 5: Commit**

```bash
git add pantryatlas/navigator/history.py tests/navigator/test_history.py
git commit -m "feat(history): pure cook-history ranking adjuster (recency penalty + rating boost)"
```

---

### Task 2: Wire `history_fn` into `rank_recipes`

**Files:**
- Modify: `pantryatlas/navigator/ranking.py` (signature + non-flavor pass + final clamp)
- Test: `tests/navigator/test_ranking.py` (append regression + boost tests)

- [ ] **Step 1: Write the failing tests** (append to `tests/navigator/test_ranking.py`)

```python
def test_history_fn_none_is_identical(simple_pantry, simple_candidates):
    # Re-rank with and without a None history_fn -> identical scores + order.
    a = rank_recipes(simple_pantry, simple_candidates, compute_substitution=False)
    b = rank_recipes(simple_pantry, simple_candidates, compute_substitution=False,
                     history_fn=None)
    assert [r.recipe["title"] for r in a] == [r.recipe["title"] for r in b]
    assert [round(r.score, 9) for r in a] == [round(r.score, 9) for r in b]


def test_history_fn_boost_raises_score(simple_pantry, simple_candidates):
    base = rank_recipes(simple_pantry, simple_candidates, compute_substitution=False)
    target = base[0].recipe["title"]
    boosted = rank_recipes(
        simple_pantry, simple_candidates, compute_substitution=False,
        history_fn=lambda t: 0.05 if t == target else 0.0,
    )
    by_title = {r.recipe["title"]: r.score for r in boosted}
    base_by_title = {r.recipe["title"]: r.score for r in base}
    assert by_title[target] == min(1.0, base_by_title[target] + 0.05)


def test_history_fn_score_clamped_to_one(simple_pantry, simple_candidates):
    ranked = rank_recipes(simple_pantry, simple_candidates, compute_substitution=False,
                          history_fn=lambda t: 0.05)
    assert all(r.score <= 1.0 for r in ranked)
```

> If fixtures `simple_pantry` / `simple_candidates` don't already exist in this
> test module, reuse the existing pantry + candidate construction pattern already
> present in `test_ranking.py` (match its naming) rather than inventing new ones.

- [ ] **Step 2: Run to verify they fail**

Run: `/usr/bin/python3 -m pytest tests/navigator/test_ranking.py -q`
Expected: FAIL (`rank_recipes() got an unexpected keyword argument 'history_fn'`).

- [ ] **Step 3: Implement in `ranking.py`**

Add the parameter to the signature (after `flavor_top_n`):

```python
    flavor_fn: Callable[[list[str], list[str]], float] | None = None,
    flavor_top_n: int = 250,
    history_fn: Callable[[str], float] | None = None,
) -> list[RankedRecipe]:
```

In Phase A, fold the adjustment into `nonflavor` (so top-N flavor selection sees it):

```python
    for recipe, coverage, missing, expiration_urgency, cultural_fit in prelim:
        substitution_penalty = (
            _penalty_from_matches(missing, pantry_names, matches)
            if compute_substitution
            else 0.0
        )
        nonflavor = (
            _W_COVERAGE * coverage
            + _W_EXPIRY * expiration_urgency
            + _W_SUBSTITUTION * (1.0 - substitution_penalty)
            + _W_CULTURAL * cultural_fit
        )
        if history_fn is not None:
            nonflavor += history_fn(recipe.get("title", ""))
        scored.append(
            (recipe, coverage, missing, expiration_urgency, cultural_fit,
             substitution_penalty, nonflavor)
        )
```

In Phase B, clamp the final score to [0, 1]:

```python
        score = nonflavor + _W_FLAVOR * flavor
        if score < 0.0:
            score = 0.0
        elif score > 1.0:
            score = 1.0
```

> Note: `nonflavor` now already includes the history adjustment, so the top-N
> selection key `scored[i][6]` correctly reflects it — no other change needed.

Update the docstring `Args:` to mention `history_fn` (one line: "Optional
``title -> bounded adjustment`` added to each candidate's score; ``None`` = no
history effect.").

- [ ] **Step 4: Run to verify pass (incl. full ranking suite for regression)**

Run: `/usr/bin/python3 -m pytest tests/navigator/test_ranking.py -q`
Expected: PASS (all pre-existing tests + 3 new).

- [ ] **Step 5: Commit**

```bash
git add pantryatlas/navigator/ranking.py tests/navigator/test_ranking.py
git commit -m "feat(ranking): optional history_fn nudge folded into non-flavor pass; clamp score to [0,1]"
```

---

### Task 3: `update_cook_event` store method

**Files:**
- Modify: `pantryatlas/store/kitchen.py` (add method near `list_meals`, ~line 404)
- Test: `tests/navigator/test_kitchen_store.py` (append)

- [ ] **Step 1: Write the failing tests** (append; reuse the module's existing
  KitchenStore tmp-db fixture — match its name, e.g. `kitchen`)

```python
def test_update_cook_event_rating_and_notes(kitchen):
    ev = kitchen.add_cook_event(dish_name="Soup", consumed=[])
    out = kitchen.update_cook_event(ev["id"], rating=5, notes="great")
    assert out["rating"] == 5 and out["notes"] == "great"
    assert kitchen.list_meals()[0]["rating"] == 5


def test_update_cook_event_partial_keeps_other_field(kitchen):
    ev = kitchen.add_cook_event(dish_name="Stew", consumed=[])
    kitchen.update_cook_event(ev["id"], rating=4)
    kitchen.update_cook_event(ev["id"], notes="add salt")
    row = kitchen.list_meals()[0]
    assert row["rating"] == 4 and row["notes"] == "add salt"


def test_update_cook_event_unknown_id_returns_none(kitchen):
    assert kitchen.update_cook_event(999999, rating=3) is None


def test_update_cook_event_bad_rating_raises(kitchen):
    ev = kitchen.add_cook_event(dish_name="X", consumed=[])
    import pytest
    for bad in (0, 6, 2.5):
        with pytest.raises(ValueError):
            kitchen.update_cook_event(ev["id"], rating=bad)


def test_update_cook_event_both_none_is_noop(kitchen):
    ev = kitchen.add_cook_event(dish_name="Y", consumed=[], rating=2)
    out = kitchen.update_cook_event(ev["id"])
    assert out["rating"] == 2
```

- [ ] **Step 2: Run to verify they fail**

Run: `/usr/bin/python3 -m pytest tests/navigator/test_kitchen_store.py -q`
Expected: FAIL (`AttributeError: 'KitchenStore' object has no attribute 'update_cook_event'`).

- [ ] **Step 3: Implement** (insert after `list_meals`, before `mark_expired`)

```python
    def update_cook_event(self, event_id: int, *, rating: int | None = None,
                          notes: str | None = None) -> dict[str, Any] | None:
        """Attach a rating (1-5) and/or note to an existing cook event.

        Only provided (non-None) fields are written. Returns the updated event
        dict, or None if event_id is unknown. Raises ValueError on bad rating.
        """
        if rating is not None and (not isinstance(rating, int) or not 1 <= rating <= 5):
            raise ValueError("rating must be an int in 1..5")
        with self._lock:
            exists = self._conn.execute(
                "SELECT 1 FROM cook_events WHERE id=?", (event_id,)
            ).fetchone()
            if exists is None:
                return None
            sets, params = [], []
            if rating is not None:
                sets.append("rating=?")
                params.append(rating)
            if notes is not None:
                sets.append("notes=?")
                params.append(notes)
            if sets:
                params.append(event_id)
                self._conn.execute(
                    f"UPDATE cook_events SET {', '.join(sets)} WHERE id=?", params
                )
                self._conn.commit()
            row = self._conn.execute(
                "SELECT * FROM cook_events WHERE id=?", (event_id,)
            ).fetchone()
        return self._cook_row_to_dict(dict(row))
```

> `bool` is an `int` subclass; `isinstance(rating, int)` accepts `True`/`False`
> but the route only ever passes pydantic-validated ints, so this is acceptable.
> `2.5` (float) is rejected by `isinstance(rating, int)`. The `dict(row)` call
> assumes `self._conn.row_factory` yields mapping rows — verify the connection
> uses `sqlite3.Row` (it does for `_fetchall`); if `execute` here returns plain
> tuples, fetch via the existing `self._fetchall("SELECT * FROM cook_events WHERE id=?", (event_id,))[0]`
> helper instead and drop the `dict(row)` wrapper.

- [ ] **Step 4: Run to verify pass**

Run: `/usr/bin/python3 -m pytest tests/navigator/test_kitchen_store.py -q`
Expected: PASS.

- [ ] **Step 5: Commit**

```bash
git add pantryatlas/store/kitchen.py tests/navigator/test_kitchen_store.py
git commit -m "feat(kitchen): update_cook_event to attach rating/notes to a logged cook"
```

---

### Task 4: PATCH endpoint + history wiring in both recipe routes

**Files:**
- Modify: `pantryatlas/navigator/server.py` (import; `MealReflectIn`; `patch_meal`; wire `history_fn` in `post_recipes_from_pantry` + `post_recipes_refine`)
- Test: `tests/navigator/test_server.py` (append)

- [ ] **Step 1: Write the failing tests** (append; reuse the module's existing
  TestClient/app fixture — match its name, e.g. `client`)

```python
def test_patch_meal_updates_rating_and_notes(client):
    created = client.post("/navigator/cook", json={"dish_name": "Soup"}).json()
    r = client.patch(f"/navigator/meals/{created['id']}",
                     json={"rating": 5, "notes": "yum"})
    assert r.status_code == 200
    assert r.json()["rating"] == 5 and r.json()["notes"] == "yum"
    meals = client.get("/navigator/meals").json()
    assert meals[0]["rating"] == 5


def test_patch_meal_unknown_id_404(client):
    assert client.patch("/navigator/meals/999999", json={"rating": 3}).status_code == 404


def test_patch_meal_bad_rating_422(client):
    created = client.post("/navigator/cook", json={"dish_name": "X"}).json()
    assert client.patch(f"/navigator/meals/{created['id']}",
                        json={"rating": 9}).status_code == 422


def test_from_pantry_demotes_recently_cooked(client):
    # Seed pantry so some recipe is a candidate, capture its baseline score,
    # then cook that exact dish title and confirm its score drops.
    # (Use the test module's existing pattern for seeding pantry + a known
    # candidate title; assert the candidate's score with history < without.)
    ...
```

> For `test_from_pantry_demotes_recently_cooked`, follow the existing
> `test_server.py` conventions for seeding the kitchen pantry and the recipe
> store. If the test fixture's recipe store has no controllable candidate titles,
> assert the weaker invariant instead: cooking a candidate's title lowers that
> candidate's returned `score` relative to a baseline request made before the
> cook. Keep it deterministic; do not depend on the 50k prod DB.

- [ ] **Step 2: Run to verify they fail**

Run: `/usr/bin/python3 -m pytest tests/navigator/test_server.py -q`
Expected: FAIL (404 route missing → likely 405/404 mismatch and AttributeError).

- [ ] **Step 3: Implement**

Add import near the other stdlib imports (line ~47, replacing `from datetime import date`):

```python
from datetime import date, datetime, timezone
```

Add the body model near the other `*In` models (after `CookIn`, ~line 166):

```python
class MealReflectIn(BaseModel):
    """Body for PATCH /navigator/meals/{meal_id}."""
    rating: int | None = None
    notes: str | None = None
```

Add the route near `get_meals` (~line 476):

```python
    @app.patch("/navigator/meals/{meal_id}")
    def patch_meal(meal_id: int, body: MealReflectIn) -> dict[str, Any]:
        try:
            updated = _get_kitchen(app).update_cook_event(
                meal_id, rating=body.rating, notes=body.notes
            )
        except ValueError as e:
            raise HTTPException(status_code=422, detail=str(e)) from e
        if updated is None:
            raise HTTPException(status_code=404, detail="meal not found")
        return updated
```

In `post_recipes_from_pantry`, right before the `rank_recipes(...)` call:

```python
        now = datetime.now(timezone.utc)
        history_fn = build_history_adjuster(
            _get_kitchen(app).list_meals(limit=500), now
        )
        flavor_store = _get_flavor(app)
        ranked: list[RankedRecipe] = rank_recipes(
            pantry,
            candidates,
            compute_substitution=False,
            flavor_fn=flavor_store.flavor_score,
            history_fn=history_fn,
        )
```

In `post_recipes_refine`, similarly before its `rank_recipes(...)`:

```python
        now = datetime.now(timezone.utc)
        history_fn = build_history_adjuster(
            _get_kitchen(app).list_meals(limit=500), now
        )
        ranked = rank_recipes(
            pantry,
            candidates,
            app.state.embed_fn,
            k=len(candidates),
            compute_substitution=True,
            flavor_fn=_get_flavor(app).flavor_score,
            history_fn=history_fn,
        )
```

Add the import (with the other `pantryatlas.navigator.*` imports, ~line 61):

```python
from pantryatlas.navigator.history import build_history_adjuster
```

- [ ] **Step 4: Run to verify pass (+ full navigator suite for regression)**

Run: `/usr/bin/python3 -m pytest tests/navigator/ -q`
Expected: PASS (all suites).

- [ ] **Step 5: Commit**

```bash
git add pantryatlas/navigator/server.py tests/navigator/test_server.py
git commit -m "feat(navigator): PATCH /meals/{id} reflection + history_fn wired into both recipe routes"
```

---

### Task 5: Web — reflection panel + persistence + log display

**Files:**
- Modify: `web/src/signals.ts` (`cookRecipe` returns event; add `reflectMeal`; add `buildReflectPayload` helper)
- Modify: `web/src/components/RecipeCard.tsx` (reflection panel after log)
- Modify: `web/src/components/MealLog.tsx` (render stars + note)
- Test: `web/src/signals.test.ts` (or existing test file) — `buildReflectPayload`

- [ ] **Step 1: Write the failing vitest** for the pure payload helper

```ts
// web/src/signals.test.ts (append or create)
import { describe, it, expect } from 'vitest'
import { buildReflectPayload } from './signals'

describe('buildReflectPayload', () => {
  it('passes rating and trims notes', () => {
    expect(buildReflectPayload(5, '  yum ')).toEqual({ rating: 5, notes: 'yum' })
  })
  it('empty note becomes null', () => {
    expect(buildReflectPayload(4, '   ')).toEqual({ rating: 4, notes: null })
  })
  it('no rating becomes null', () => {
    expect(buildReflectPayload(null, 'note')).toEqual({ rating: null, notes: 'note' })
  })
})
```

- [ ] **Step 2: Run to verify it fails**

Run: `cd web && npx vitest run src/signals.test.ts`
Expected: FAIL (`buildReflectPayload` is not exported).

- [ ] **Step 3: Implement signals**

In `web/src/signals.ts`:

```ts
/** Build the PATCH body for a reflection; blank note -> null. */
export function buildReflectPayload(rating: number | null, notes: string) {
  const trimmed = notes.trim()
  return { rating, notes: trimmed.length ? trimmed : null }
}
```

Change `cookRecipe` to return the created event (and update its body parse):

```ts
export async function cookRecipe(opts: {
  recipe_id?: string
  dish_name: string
  servings?: number
  consumed?: { canonical_name: string; coarse_amount: string }[]
}): Promise<CookEvent | null> {
  try {
    const res = await fetch('/navigator/cook', {
      method: 'POST',
      headers: { 'Content-Type': 'application/json' },
      body: JSON.stringify(opts),
    })
    if (res.ok || res.status === 201) {
      const ev = (await res.json()) as CookEvent
      await fetchPantry()
      await fetchMeals()
      await refreshWasteIfOpen()
      return ev
    }
  } catch {
    // ignore
  }
  return null
}

/** Attach a rating/note to a logged cook event. */
export async function reflectMeal(
  id: number, rating: number | null, notes: string | null,
): Promise<boolean> {
  try {
    const res = await fetch(`/navigator/meals/${id}`, {
      method: 'PATCH',
      headers: { 'Content-Type': 'application/json' },
      body: JSON.stringify({ rating, notes }),
    })
    if (res.ok) {
      await fetchMeals()
      return true
    }
  } catch {
    // ignore
  }
  return false
}
```

> Note: the cook POST returns `{id, dish_name, matched, unmatched}` (not a full
> CookEvent). That is enough — only `id` is consumed by the card. Cast as
> `CookEvent` is acceptable for the `id`; do not rely on other fields from the
> POST response.

- [ ] **Step 4: Implement RecipeCard reflection panel**

In `web/src/components/RecipeCard.tsx`:
- Import: `import { ..., reflectMeal, buildReflectPayload } from '../signals'`.
- State: `const [cookedEventId, setCookedEventId] = useState<number | null>(null)`,
  `const [rating, setRating] = useState<number | null>(null)`,
  `const [note, setNote] = useState('')`,
  `const [reflectDone, setReflectDone] = useState(false)`.
- In `handleCooked`, replace the boolean handling:

```ts
    const ev = await cookRecipe({ dish_name: recipe.title, servings, consumed })
    setCooking(false)
    if (ev) { setCooked(true); setCookedEventId(ev.id) }
```

- Replace the terminal `✓ Logged` button content with: when `cooked` and not
  `reflectDone`, render a reflection panel in place of (or below) the button —
  five star buttons (`onClick={() => setRating(n)}`, `aria-label={`Rate ${n} stars`}`,
  `aria-pressed={rating === n}`, filled when `n <= (rating ?? 0)`), a note
  `<input maxLength={140} aria-label="Add a note" value={note}
  onInput={e => setNote(e.currentTarget.value)} />`, and two buttons:

```ts
    // Save
    onClick={async () => {
      if (cookedEventId != null) {
        const p = buildReflectPayload(rating, note)
        await reflectMeal(cookedEventId, p.rating, p.notes)
      }
      setReflectDone(true)
    }}
    // Skip
    onClick={() => setReflectDone(true)}
```

  When `reflectDone` (or no event id), show the quiet confirmation
  `✓ Logged{rating ? ` · ${'★'.repeat(rating)}` : ''}`. The cook button stays
  disabled once `cooked` (no double-log). Keep styles consistent with the existing
  card tokens (`--md-sys-color-*`); the panel must be keyboard-operable.

- [ ] **Step 5: Implement MealLog display**

In `web/src/components/MealLog.tsx`, where each meal row renders, add (guarded):

```tsx
{m.rating ? <span aria-label={`Rated ${m.rating} stars`}>{'★'.repeat(m.rating)}</span> : null}
{m.notes ? <div class="meal-note">{m.notes}</div> : null}
```

Match the file's existing element/style conventions (the snippet is illustrative).

- [ ] **Step 6: Run vitest + build**

Run: `cd web && npx vitest run`
Expected: PASS.
Run: `cd web && npx tsc --noEmit && npm run build`
Expected: clean (no type errors; `web/dist` produced).

- [ ] **Step 7: Commit**

```bash
git add web/src/signals.ts web/src/signals.test.ts web/src/components/RecipeCard.tsx web/src/components/MealLog.tsx
git commit -m "feat(web): post-cook star/note reflection panel + reflectMeal PATCH + MealLog ratings"
```

---

## Self-Review (author checklist — done before handoff)

- **Spec coverage:** A.1 store (Task 3) ✓; A.2 endpoint (Task 4) ✓; A.3 web (Task 5) ✓; B.1 history.py (Task 1) ✓; B.2 rank_recipes (Task 2) ✓; B.3 both-route wiring (Task 4) ✓; MealLog display (Task 5) ✓.
- **No-op invariant:** Task 2 `history_fn=None` regression test + Task 1 empty-history test both assert byte-identical / 0.0. ✓
- **Both routes:** Task 4 wires `history_fn` into from-pantry AND refine. ✓
- **Join key:** normalize_title used in both build + lookup (Task 1). ✓
- **Type consistency:** `build_history_adjuster(cook_events, now, ...)` signature identical in Task 1 def and Task 4 calls; `cookRecipe` return type `CookEvent | null` matches its single caller update in Task 5; `update_cook_event(event_id, *, rating, notes)` identical in Task 3 def and Task 4 call.
- **No new deps / data files** (slice-3 CI lesson): only stdlib `datetime` added. ✓

## Verify (after all tasks, before PR) — runtime, per `verify` skill

Boot uvicorn on the Pi over a real socket against the real `recipes.db` but a
**TEMP** kitchen db (env override / `--kitchen-db` to a `mktemp` path — never touch
`~/.pantryatlas`). Seed cooks via the API, drive from-pantry, observe re-rank;
PATCH a meal and GET it back. Capture outputs. Then deploy to pi-nas (`pantrydev`,
:8090) via `ops/dev/pa-deploy.sh` and smoke the reflection panel + a seeded re-rank
in the browser.
