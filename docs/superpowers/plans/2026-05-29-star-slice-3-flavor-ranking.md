# Star Slice 3 — FlavorDB Compound-Overlap Ranking Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Add a hybrid flavor sub-score (recipe cohesion + non-pantry affinity over FlavorDB molecule sets) at weight 0.10, surface a "great pairing" badge, without slowing the instant paint.

**Architecture:** New lazy `pantryatlas/flavor/` module (loads `compounds.parquet`, maps noisy ingredient phrases → FlavorDB entities, computes Jaccard-based cohesion/affinity). `ranking.py` stays pure — flavor enters via an injected `flavor_fn`, takes over the dormant 0.10 `cultural_fit` weight, and is computed only for the top-N candidates by non-flavor score (perf cap). Server wires a lazy `FlavorStore`. Web shows a subtle badge.

**Tech Stack:** Python 3 + pandas (already a dep) + FastAPI; Preact + @preact/signals + Vite; pytest via `/usr/bin/python3 -m pytest`; vitest (node).

**Critical conventions:**
- Run Python tests with `/usr/bin/python3 -m pytest …` (the `.venv` has no pytest). `ruff` is on PATH.
- Subagents use **specific `git add <paths>`**, never `git add -A`.
- Keep `ranking.py` **pure** (no parquet/DB load); flavor only via `flavor_fn`.
- Do NOT consume `slerp.py`/`modes.py`; do NOT touch the cuisine/filter path; do NOT re-ingest `recipes.db`.

---

### Task 1: `pantryatlas/flavor/` — FlavorStore (loader + matcher + jaccard)

**Files:**
- Create: `pantryatlas/flavor/__init__.py`
- Create: `pantryatlas/flavor/store.py`
- Create: `tests/flavor/__init__.py`
- Test: `tests/flavor/test_store.py`

- [ ] **Step 1: Write the failing tests** (`tests/flavor/test_store.py`)

```python
from __future__ import annotations

from pathlib import Path

import pytest

from pantryatlas.flavor.store import FlavorStore

PARQUET = Path(__file__).resolve().parents[2] / "pantryatlas" / "data" / "compounds.parquet"


@pytest.fixture(scope="module")
def fs() -> FlavorStore:
    return FlavorStore(PARQUET)


def _name(fs: FlavorStore, phrase: str) -> str | None:
    eid = fs.entity_for(phrase)
    return fs.entity_name(eid) if eid is not None else None


def test_matcher_precision(fs: FlavorStore):
    # exact + multiword (longest wins)
    assert _name(fs, "garlic") == "Garlic"
    assert _name(fs, "cream cheese") == "Cream Cheese"
    assert _name(fs, "sweet potato") == "Sweet Potato"
    assert _name(fs, "peanut butter") == "Peanut Butter"
    # generic head-noun → modifier wins
    assert _name(fs, "coconut milk") == "Coconut"
    assert _name(fs, "almond milk") == "Almond"
    assert _name(fs, "almond butter") == "Almond"
    # head-noun for noisy phrases
    assert _name(fs, "ribs celery") == "Celery"
    assert _name(fs, "red onion") == "Onion"
    assert _name(fs, "ground beef") == "Beef"
    # blocklist / non-foods → None
    assert fs.entity_for("baking soda") is None
    assert fs.entity_for("cream of tartar") is None
    # unmappable → None
    assert fs.entity_for("xyzzy widget") is None


def test_jaccard(fs: FlavorStore):
    g = fs.entity_for("garlic")
    o = fs.entity_for("onion")
    assert fs.jaccard(g, g) == 1.0
    j = fs.jaccard(g, o)
    assert 0.0 <= j <= 1.0
    assert fs.jaccard(g, o) == fs.jaccard(o, g)  # symmetric + cached
```

- [ ] **Step 2: Run tests to verify they fail**

Run: `cd /home/craigm26/pantryatlas && /usr/bin/python3 -m pytest tests/flavor/test_store.py -v`
Expected: FAIL — `ModuleNotFoundError: pantryatlas.flavor`.

- [ ] **Step 3: Implement the module**

`pantryatlas/flavor/__init__.py`:

```python
"""FlavorDB-backed flavor scoring (compound-overlap)."""
from pantryatlas.flavor.store import FlavorStore

__all__ = ["FlavorStore"]
```

`pantryatlas/flavor/store.py`:

```python
"""FlavorStore — map noisy ingredient phrases to FlavorDB entities and score
flavor cohesion / pantry affinity from shared flavor molecules.

Loads ``pantryatlas/data/compounds.parquet`` (935 FlavorDB food entities, each
with a ``molecules_json`` list of flavor molecules).  Pure + deterministic;
all caches are per-instance so test instances stay isolated.
"""
from __future__ import annotations

import json
import re
from pathlib import Path
from typing import Any

import pandas as pd

_TOKEN_RE = re.compile(r"[a-z']+")

# Generic head-nouns whose preceding modifier usually carries the real food
# identity (e.g. "coconut milk" is coconut-flavored, not dairy).
_GENERIC_HEADS = {"milk", "sauce", "cream", "oil", "juice", "syrup", "powder", "butter"}

# Phrases that must map to NO entity (non-foods or misleading head nouns).
_BLOCKLIST = {"baking soda", "baking powder", "cream of tartar", "corn starch", "cornstarch"}

# Curated phrase (normalized) -> FlavorDB entity name (normalized) fixes.
_ALIASES: dict[str, str] = {}


class FlavorStore:
    def __init__(self, parquet_path: str | Path) -> None:
        df = pd.read_parquet(parquet_path)
        self._ent_mol: dict[int, frozenset[int]] = {}
        self._id2name: dict[int, str] = {}
        self._name2id: dict[str, int] = {}
        rows: list[tuple[str, int]] = []
        for _, r in df.iterrows():
            eid = int(r["compound_id"])
            mols = r["molecules_json"]
            mols = json.loads(mols) if isinstance(mols, str) else mols
            self._ent_mol[eid] = frozenset(
                m["pubchem_id"]
                for m in mols
                if isinstance(m, dict) and m.get("pubchem_id") is not None
            )
            self._id2name[eid] = str(r["compound_name"])
            rows.append((str(r["compound_name"]).strip().lower(), eid))
        # Register longest names first so multiword/specific entities win.
        for name, eid in sorted(rows, key=lambda t: -len(t[0])):
            self._register(name, eid)
            if name.endswith("s"):
                self._register(name[:-1], eid)
        self._jac_cache: dict[tuple[int, int], float] = {}
        self._entity_cache: dict[str, int | None] = {}

    def _register(self, name: str, eid: int) -> None:
        if name and name not in self._name2id:
            self._name2id[name] = eid

    def entity_name(self, eid: int) -> str | None:
        return self._id2name.get(eid)

    # -- matcher ---------------------------------------------------------------
    def entity_for(self, phrase: str) -> int | None:
        key = phrase.strip().lower()
        if key in self._entity_cache:
            return self._entity_cache[key]
        result = self._match(key)
        self._entity_cache[key] = result
        return result

    def _match(self, pl: str) -> int | None:
        if pl in self._name2id:
            return self._name2id[pl]
        if pl in _ALIASES:
            return self._name2id.get(_ALIASES[pl])
        if pl in _BLOCKLIST:
            return None
        words = _TOKEN_RE.findall(pl)
        if not words:
            return None
        n = len(words)
        # longest consecutive token-subsequence (multiword entities first)
        for length in range(min(n, 4), 1, -1):
            for i in range(0, n - length + 1):
                cand = " ".join(words[i : i + length])
                if cand in self._name2id:
                    return self._name2id[cand]
        # head noun, with generic-modifier handling
        head = words[-1]
        if head in _GENERIC_HEADS and n >= 2:
            for w in words[:-1]:
                if w in self._name2id:
                    return self._name2id[w]
        if head in self._name2id:
            return self._name2id[head]
        for w in words:
            if w in self._name2id:
                return self._name2id[w]
        return None

    # -- metrics ---------------------------------------------------------------
    def jaccard(self, e1: int, e2: int) -> float:
        if e1 == e2:
            return 1.0
        key = (e1, e2) if e1 < e2 else (e2, e1)
        cached = self._jac_cache.get(key)
        if cached is not None:
            return cached
        a = self._ent_mol.get(e1, frozenset())
        b = self._ent_mol.get(e2, frozenset())
        union = len(a | b)
        val = (len(a & b) / union) if union else 0.0
        self._jac_cache[key] = val
        return val

    def _entities(self, phrases: list[str]) -> list[int]:
        out: list[int] = []
        for p in phrases:
            e = self.entity_for(p)
            if e is not None and e not in out:
                out.append(e)
        return out

    def cohesion(self, phrases: list[str]) -> float | None:
        ids = self._entities(phrases)
        if len(ids) < 2:
            return None
        total = 0.0
        count = 0
        for i in range(len(ids)):
            for j in range(i + 1, len(ids)):
                total += self.jaccard(ids[i], ids[j])
                count += 1
        return total / count

    def affinity(self, recipe_phrases: list[str], pantry_names: list[str]) -> float | None:
        pantry_entities = {e for e in (self.entity_for(p) for p in pantry_names) if e is not None}
        if not pantry_entities:
            return None
        recipe_entities = self._entities(recipe_phrases)
        non_pantry = [e for e in recipe_entities if e not in pantry_entities]
        if not non_pantry:
            return None
        total = 0.0
        for e in non_pantry:
            total += max(self.jaccard(e, pe) for pe in pantry_entities)
        return total / len(non_pantry)

    def flavor_score(self, recipe_phrases: list[str], pantry_names: list[str]) -> float:
        coh = self.cohesion(recipe_phrases)
        aff = self.affinity(recipe_phrases, pantry_names)
        if coh is None and aff is None:
            return 0.0
        if aff is None:
            return coh  # type: ignore[return-value]
        if coh is None:
            return aff
        return 0.5 * coh + 0.5 * aff
```

- [ ] **Step 4: Run tests to verify they pass**

Run: `cd /home/craigm26/pantryatlas && /usr/bin/python3 -m pytest tests/flavor/test_store.py -v`
Expected: PASS. If a `test_matcher_precision` assertion fails on a specific phrase, tune `_GENERIC_HEADS` / `_BLOCKLIST` / `_ALIASES` (or the subsequence length) until the fixture passes — this is the precision-tuning step. Do NOT weaken the assertions; fix the matcher.

- [ ] **Step 5: ruff + commit**

```bash
ruff check pantryatlas/flavor/ tests/flavor/
git add pantryatlas/flavor/__init__.py pantryatlas/flavor/store.py tests/flavor/__init__.py tests/flavor/test_store.py
git commit -m "feat(flavor): FlavorStore — ingredient→FlavorDB matcher + jaccard"
```

---

### Task 2: FlavorStore cohesion / affinity / flavor_score tests

**Files:**
- Test: `tests/flavor/test_store.py` (append)

(The implementation already exists from Task 1; this task locks the metric semantics — especially the affinity self-match exclusion, which is the whole point of "hybrid not double-counted coverage".)

- [ ] **Step 1: Append the failing-then-passing tests**

```python
def test_cohesion(fs: FlavorStore):
    assert fs.cohesion(["garlic"]) is None  # <2 mapped → None
    assert fs.cohesion(["xyzzy", "qwerty"]) is None  # 0 mapped → None
    c = fs.cohesion(["garlic", "onion", "tomato"])
    assert c is not None and 0.0 <= c <= 1.0


def test_affinity_excludes_pantry_and_equal(fs: FlavorStore):
    # A recipe whose only mapped entities are already in the pantry → None
    assert fs.affinity(["garlic", "onion"], ["garlic", "onion"]) is None
    # Empty pantry → None
    assert fs.affinity(["garlic", "onion"], []) is None
    # Non-pantry recipe entities vs pantry → defined, in [0,1]
    a = fs.affinity(["basil", "tomato"], ["garlic", "onion"])
    assert a is not None and 0.0 <= a <= 1.0


def test_flavor_score_blend(fs: FlavorStore):
    # both None → 0.0
    assert fs.flavor_score(["xyzzy"], []) == 0.0
    # cohesion present, affinity None (empty pantry) → equals cohesion
    coh = fs.cohesion(["garlic", "onion", "tomato"])
    assert fs.flavor_score(["garlic", "onion", "tomato"], []) == pytest.approx(coh)
    # both present → 0.5/0.5 blend
    phrases = ["basil", "tomato", "oregano"]
    pantry = ["garlic", "onion"]
    coh2 = fs.cohesion(phrases)
    aff2 = fs.affinity(phrases, pantry)
    assert coh2 is not None and aff2 is not None
    assert fs.flavor_score(phrases, pantry) == pytest.approx(0.5 * coh2 + 0.5 * aff2)
```

- [ ] **Step 2: Run**

Run: `cd /home/craigm26/pantryatlas && /usr/bin/python3 -m pytest tests/flavor/test_store.py -v`
Expected: PASS (these exercise existing methods). If `test_affinity_excludes_pantry_and_equal` fails, the affinity method is wrong (must exclude pantry entities) — fix the method, not the test.

- [ ] **Step 3: ruff + commit**

```bash
ruff check tests/flavor/test_store.py
git add tests/flavor/test_store.py
git commit -m "test(flavor): lock cohesion/affinity/flavor_score semantics"
```

---

### Task 3: `ranking.py` integration (flavor_fn, weight, top-N cap)

**Files:**
- Modify: `pantryatlas/navigator/ranking.py`
- Modify: `tests/navigator/test_ranking.py`

- [ ] **Step 1: Write the failing tests** (append to `tests/navigator/test_ranking.py`)

```python
def test_flavor_reorders_ties():
    """Two recipes tie on coverage; the higher flavor_fn score ranks first.

    rank_recipes passes ``recipe["ingredients"]`` (the same list object) to
    flavor_fn, so we key flavor off object identity for a deterministic test.
    """
    pantry = _make_pantry("garlic", "onion")
    r_hi = _recipe("HiFlavor", "garlic", "onion")
    r_lo = _recipe("LoFlavor", "garlic", "onion")

    def flavor_fn(ings, pantry_names):
        return 0.8 if ings is r_hi["ingredients"] else 0.0

    results = rank_recipes(
        pantry, [r_lo, r_hi], embed_fn=_identity_embed, flavor_fn=flavor_fn
    )
    assert results[0].recipe["title"] == "HiFlavor"
    assert results[0].flavor == 0.8
    assert results[1].flavor == 0.0


def test_flavor_fn_none_is_backcompat():
    """flavor_fn=None → flavor 0.0, scores unchanged from coverage/expiry/sub only."""
    pantry = _make_pantry("garlic", "onion")
    r = _recipe("X", "garlic", "onion")
    [res] = rank_recipes(pantry, [r], embed_fn=_identity_embed)
    assert res.flavor == 0.0
    # full coverage, no missing → 0.50 + 0.20*0 + 0.20*1 + 0.10*0 = 0.70
    assert abs(res.score - 0.70) < 1e-6


def test_flavor_top_n_cap():
    """With flavor_top_n=1, only the top candidate by non-flavor score gets flavor>0."""
    pantry = _make_pantry("garlic", "onion")
    full = _recipe("Full", "garlic", "onion")            # coverage 1.0
    partial = _recipe("Partial", "garlic", "zucchini")   # coverage 0.5
    calls = []

    def flavor_fn(ings, pantry_names):
        calls.append(ings)
        return 0.5

    results = rank_recipes(
        pantry, [full, partial], embed_fn=_identity_embed,
        flavor_fn=flavor_fn, flavor_top_n=1,
    )
    # Only the higher non-flavor-score recipe (Full) had flavor computed.
    assert len(calls) == 1
    full_res = next(r for r in results if r.recipe["title"] == "Full")
    partial_res = next(r for r in results if r.recipe["title"] == "Partial")
    assert full_res.flavor == 0.5
    assert partial_res.flavor == 0.0
```

- [ ] **Step 2: Run to verify they fail**

Run: `cd /home/craigm26/pantryatlas && /usr/bin/python3 -m pytest tests/navigator/test_ranking.py -k "flavor" -v`
Expected: FAIL — `rank_recipes() got an unexpected keyword argument 'flavor_fn'` / no `flavor` attribute.

- [ ] **Step 3: Implement**

In `pantryatlas/navigator/ranking.py`:

(a) Add `import logging` at the top (after the existing imports) and a module logger:
```python
import logging

_log = logging.getLogger(__name__)
```

(b) Add `flavor` to `RankedRecipe`:
```python
    cultural_fit: float = 0.0
    flavor: float = 0.0
```

(c) Change the weights block:
```python
_W_COVERAGE: float = 0.50
_W_EXPIRY: float = 0.20
_W_SUBSTITUTION: float = 0.20
_W_CULTURAL: float = 0.0   # superseded by flavor (slice 3); cuisine ranking → slice 2
_W_FLAVOR: float = 0.10
```

(d) Update the docstring formula comment near the top of the file to:
```
    score = 0.50 * coverage
          + 0.20 * expiration_urgency
          + 0.20 * (1 - substitution_penalty)
          + 0.10 * flavor
```

(e) Change the `rank_recipes` signature to add the two params (keep existing ones):
```python
def rank_recipes(
    pantry: Pantry,
    candidate_recipes: list[dict[str, Any]],
    embed_fn: Callable[[list[str]], np.ndarray] | None = None,
    k: int = 20,
    *,
    cuisine: str | None = None,
    expiry_window_days: int = _EXPIRY_WINDOW_DAYS,
    compute_substitution: bool = True,
    flavor_fn: Callable[[list[str], list[str]], float] | None = None,
    flavor_top_n: int = 250,
) -> list[RankedRecipe]:
```

(f) Replace the final scoring loop (the `ranked: list[RankedRecipe] = []` block through `return ranked[:k]`) with the two-phase flavor-aware version:

```python
    # Phase A: non-flavor score for every candidate.
    scored: list[tuple[dict[str, Any], float, list[str], float, float, float, float]] = []
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
        scored.append(
            (recipe, coverage, missing, expiration_urgency, cultural_fit,
             substitution_penalty, nonflavor)
        )

    # Phase B: compute flavor only for the top-N by non-flavor score (perf cap).
    flavor_indices = set(range(len(scored)))
    if flavor_fn is not None and len(scored) > flavor_top_n:
        ordered = sorted(range(len(scored)), key=lambda i: scored[i][6], reverse=True)
        flavor_indices = set(ordered[:flavor_top_n])
        _log.info(
            "flavor capped to top %d of %d candidates", flavor_top_n, len(scored)
        )

    ranked: list[RankedRecipe] = []
    for i, (recipe, coverage, missing, expiration_urgency, cultural_fit,
            substitution_penalty, nonflavor) in enumerate(scored):
        flavor = 0.0
        if flavor_fn is not None and i in flavor_indices:
            flavor = flavor_fn(recipe.get("ingredients", []), pantry_names)
        score = nonflavor + _W_FLAVOR * flavor
        ranked.append(
            RankedRecipe(
                recipe=recipe,
                score=score,
                coverage=coverage,
                missing=missing,
                expiration_urgency=expiration_urgency,
                substitution_penalty=substitution_penalty,
                cultural_fit=cultural_fit,
                flavor=flavor,
            )
        )

    ranked.sort(key=lambda r: r.score, reverse=True)
    return ranked[:k]
```

- [ ] **Step 4: Update the one broken existing test**

In `tests/navigator/test_ranking.py`, `test_cultural_fit_cuisine_boost` (line ~296): the cuisine no longer boosts score (weight moved to flavor; cuisine ranking is slice 2). Change:
```python
    assert italian_result.score > generic_result.score
```
to:
```python
    # cultural_fit weight moved to flavor (slice 3); cuisine ranking → slice 2.
    # cultural_fit is still computed/reported, but no longer affects score.
    assert italian_result.score == generic_result.score
```
(Keep the `cultural_fit == 1.0` / `== 0.0` field assertions — those still hold.)

- [ ] **Step 5: Run the whole ranking suite**

Run: `cd /home/craigm26/pantryatlas && /usr/bin/python3 -m pytest tests/navigator/test_ranking.py -v`
Expected: PASS (new flavor tests + all existing, with the one updated assertion). Then `ruff check pantryatlas/navigator/ranking.py tests/navigator/test_ranking.py`.

- [ ] **Step 6: Commit**

```bash
git add pantryatlas/navigator/ranking.py tests/navigator/test_ranking.py
git commit -m "feat(ranking): flavor sub-score via injected flavor_fn (0.10 weight, top-N cap)"
```

---

### Task 4: `server.py` wiring

**Files:**
- Modify: `pantryatlas/navigator/server.py`
- Modify: `tests/navigator/test_server.py`

- [ ] **Step 1: Write the failing test** (append to `tests/navigator/test_server.py`)

```python
def test_from_pantry_includes_flavor_field(client):
    client.post("/navigator/pantry/items", json={"raw_text": "garlic", "canonical_name": "garlic"})
    client.post("/navigator/pantry/items", json={"raw_text": "onion", "canonical_name": "onion"})
    res = client.post("/navigator/recipes/from-pantry")
    assert res.status_code == 200
    data = res.json()
    if data:  # fake store may return few; assert the field shape when present
        assert "flavor" in data[0]
        assert isinstance(data[0]["flavor"], (int, float))
```

(Note: the `client` fixture uses a fake RecipeStore; flavor_fn must be wired but tolerate a fake store. The wiring below uses a lazy FlavorStore that loads the real parquet — the parquet is bundled, so it loads fine even in tests.)

- [ ] **Step 2: Run to verify it fails**

Run: `cd /home/craigm26/pantryatlas && /usr/bin/python3 -m pytest tests/navigator/test_server.py -k flavor -v`
Expected: FAIL — `"flavor"` not in the response dict.

- [ ] **Step 3: Implement the wiring**

In `pantryatlas/navigator/server.py`:

(a) Add the import near the other store imports:
```python
from pantryatlas.flavor import FlavorStore
```

(b) Add a lazy accessor next to `_get_kitchen` (mirror its pattern):
```python
def _get_flavor(app: FastAPI) -> FlavorStore:
    """Return the app's FlavorStore, building it lazily via factory if needed."""
    flavor: FlavorStore | None = getattr(app.state, "flavor", None)
    if flavor is None:
        factory: Callable[[], FlavorStore] | None = getattr(app.state, "flavor_factory", None)
        if factory is None:
            raise RuntimeError("No FlavorStore and no flavor_factory configured on app.state")
        app.state.flavor = factory()
        flavor = app.state.flavor
    return flavor
```

(c) In `create_app`, accept and store an optional flavor store/factory. Add params to the signature:
```python
    flavor: FlavorStore | None = None,
    flavor_factory: Callable[[], FlavorStore] | None = None,
```
and after the kitchen wiring lines (`app.state.kitchen = kitchen` / `app.state.kitchen_factory = kitchen_factory`), add:
```python
    app.state.flavor = flavor
    # Default factory: load the bundled parquet lazily on first use.
    if flavor is None and flavor_factory is None:
        _parquet = Path(__file__).resolve().parent.parent / "data" / "compounds.parquet"
        flavor_factory = lambda: FlavorStore(_parquet)  # noqa: E731
    app.state.flavor_factory = flavor_factory
```
(`Path` is already imported in server.py.)

(d) In `post_recipes_from_pantry`, build a `flavor_fn` and pass it:
```python
        flavor_store = _get_flavor(app)
        ranked: list[RankedRecipe] = rank_recipes(
            pantry,
            candidates,
            cuisine=cuisine,
            compute_substitution=False,
            flavor_fn=flavor_store.flavor_score,
        )
```

(e) In `post_recipes_refine`, likewise add `flavor_fn=_get_flavor(app).flavor_score` to the `rank_recipes(...)` call.

(f) In `_ranked_to_dict`, add the flavor field:
```python
        "cultural_fit": r.cultural_fit,
        "flavor": r.flavor,
```

(g) **Warm the FlavorStore at startup** so the first request isn't stalled by the
~9s pandas+parquet load (it's lazy otherwise). In `create_app`'s `_lifespan`, add a
best-effort warm-up BEFORE `yield`. First ensure a module logger exists near the top
of `server.py` (add if missing):
```python
import logging

_server_log = logging.getLogger(__name__)
```
Then update `_lifespan` (it currently only does shutdown):
```python
    @asynccontextmanager
    async def _lifespan(application: FastAPI):  # noqa: RUF029
        # Startup: warm the FlavorStore once (pandas + parquet ~9s) so the first
        # from-pantry request isn't stalled. Best-effort — never block boot.
        if (
            getattr(application.state, "flavor", None) is not None
            or getattr(application.state, "flavor_factory", None) is not None
        ):
            try:
                _get_flavor(application)
            except Exception:
                _server_log.warning("FlavorStore warm-up failed; will load lazily", exc_info=True)
        yield
        # Shutdown: close the OFF HTTP connection pool to avoid resource leaks.
        client = getattr(application.state, "off_client", None)
        if client is not None and hasattr(client, "close"):
            client.close()
```
(The non-context-manager `client` fixture does not trigger lifespan, so most
server tests are unaffected; the context-managed lifespan test will warm and stay
green, just ~9s slower.)

- [ ] **Step 4: Run to verify it passes**

Run: `cd /home/craigm26/pantryatlas && /usr/bin/python3 -m pytest tests/navigator/test_server.py -k "flavor or from_pantry" -v`
Expected: PASS. Then `ruff check pantryatlas/navigator/server.py tests/navigator/test_server.py`.

- [ ] **Step 5: Commit**

```bash
git add pantryatlas/navigator/server.py tests/navigator/test_server.py
git commit -m "feat(api): wire lazy FlavorStore into from-pantry + refine; expose flavor"
```

---

### Task 5: Web — wire type, badge helper, card badge

**Files:**
- Create: `web/src/lib/flavor.ts`
- Create: `web/src/lib/flavor.test.ts`
- Modify: `web/src/components/RecipeCard.tsx`

- [ ] **Step 1: Write the failing test** (`web/src/lib/flavor.test.ts`)

```ts
import { describe, it, expect } from 'vitest'
import { shouldShowPairingBadge, FLAVOR_BADGE_THRESHOLD } from './flavor'

describe('shouldShowPairingBadge', () => {
  it('true at/above threshold', () => {
    expect(shouldShowPairingBadge(FLAVOR_BADGE_THRESHOLD)).toBe(true)
    expect(shouldShowPairingBadge(0.9)).toBe(true)
  })
  it('false below threshold or missing', () => {
    expect(shouldShowPairingBadge(FLAVOR_BADGE_THRESHOLD - 0.01)).toBe(false)
    expect(shouldShowPairingBadge(0)).toBe(false)
    expect(shouldShowPairingBadge(undefined)).toBe(false)
  })
})
```

- [ ] **Step 2: Run to verify it fails**

Run: `cd /home/craigm26/pantryatlas/web && npx vitest run src/lib/flavor.test.ts`
Expected: FAIL — module not found.

- [ ] **Step 3: Implement helper** (`web/src/lib/flavor.ts`)

```ts
/** Threshold above which a recipe earns the "great pairing" badge.
 *  ~top quartile of the blended cohesion+affinity distribution; tunable. */
export const FLAVOR_BADGE_THRESHOLD = 0.3

export function shouldShowPairingBadge(flavor: number | undefined): boolean {
  return typeof flavor === 'number' && flavor >= FLAVOR_BADGE_THRESHOLD
}
```

- [ ] **Step 4: Add `flavor` to the wire type + render the badge** (`web/src/components/RecipeCard.tsx`)

(a) Add to the `RankedRecipe` interface (after `cultural_fit: number`):
```ts
  cultural_fit: number
  flavor?: number
```

(b) Add the import at the top:
```ts
import { shouldShowPairingBadge } from '../lib/flavor'
```

(c) In the chip-line `<div style={{ marginTop: '8px' }}>` (right after the existing `{chipLabel}` span closes, still inside that div), add the badge:
```tsx
              {shouldShowPairingBadge(ranked.flavor) && (
                <span
                  data-pairing-badge="true"
                  style={{
                    display: 'inline-flex',
                    alignItems: 'center',
                    marginLeft: '6px',
                    padding: '3px 12px',
                    borderRadius: 'var(--md-sys-shape-corner-full)',
                    background: 'var(--md-sys-color-tertiary-container)',
                    color: 'var(--md-sys-color-on-tertiary-container)',
                    fontFamily: 'var(--font)',
                    fontSize: 'var(--md-sys-typescale-label-medium-size)',
                    fontWeight: 'var(--md-sys-typescale-label-medium-weight)',
                    whiteSpace: 'nowrap',
                  }}
                >
                  great pairing
                </span>
              )}
```

- [ ] **Step 5: Verify**

Run: `cd /home/craigm26/pantryatlas/web && npx vitest run && npx tsc --noEmit && npm run build`
Expected: all vitest green, tsc clean, build succeeds.

- [ ] **Step 6: Commit**

```bash
git add web/src/lib/flavor.ts web/src/lib/flavor.test.ts web/src/components/RecipeCard.tsx
git commit -m "feat(web): great-pairing badge driven by flavor score"
```

---

### Final verification (after all tasks)

- [ ] **Full Python suite + lint:**
  `cd /home/craigm26/pantryatlas && /usr/bin/python3 -m pytest tests/ -q && ruff check pantryatlas/ tests/`
  Expected: all green; ruff clean.

- [ ] **Full web suite + build:**
  `cd /home/craigm26/pantryatlas/web && npx vitest run && npx tsc --noEmit && npm run build`
  Expected: green/clean.

- [ ] **Runtime verification (Pi, real socket, real recipes.db, TEMP kitchen — never touch `~/.pantryatlas`):**
  1. Boot the app with the real RecipeStore + real FlavorStore (bundled parquet) + temp kitchen.
  2. **Perf:** add a ~10-item pantry, time `POST /navigator/recipes/from-pantry` → confirm the instant paint stays within budget (target < ~1.2s) WITH flavor + the top-N cap. Capture the timing.
  3. **Signal:** confirm responses carry a numeric `flavor`; capture an ordering where a higher-flavor recipe out-ranks a coverage-tie.
  4. **Badge:** confirm `flavor >= 0.30` recipes exist (would render the badge).
  5. Confirm real `~/.pantryatlas` untouched.

- [ ] **Finish:** superpowers:finishing-a-development-branch → Option 2 (push + PR). Stop at PR + CI green; do NOT merge (operator merges).
