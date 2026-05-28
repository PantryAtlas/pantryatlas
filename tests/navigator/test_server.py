"""Tests for pantryatlas.navigator.server (T-004).

TDD: all tests written before implementation.

Design summary
--------------
- ``create_app(store, resolver, embed_fn, pantry_path, web_dist)`` factory
  keeps the real ONNX model and real DB completely out of the test process.
- ``resolver`` is a ``Callable[[str], Optional[Ingredient]]`` — tests use a
  dict-lookup fake that resolves known ingredient names deterministically.
- ``embed_fn`` is a ``Callable[[list[str]], np.ndarray]`` — tests use the same
  sha256-seeded unit-vector fake from test_ranking.py.
- ``pantry_path`` is a ``pathlib.Path`` pointing at a ``tmp_path``-based file.
- ``store`` is a ``RecipeStore`` backed by an in-memory / tmp sqlite DB,
  seeded with ~1000 synthetic recipes for criterion 8.
"""

from __future__ import annotations

import hashlib
import importlib
import sys
from pathlib import Path

import numpy as np
import pytest
from fastapi.testclient import TestClient

from pantryatlas.pantry.models import Ingredient
from pantryatlas.store.recipes import Recipe, RecipeStore

# ---------------------------------------------------------------------------
# Helpers / fakes
# ---------------------------------------------------------------------------

_DIM = 8  # tiny dimension for fake embeddings


def _fake_embed(texts: list[str]) -> np.ndarray:
    """Sha256-seeded unit vectors — PYTHONHASHSEED-independent."""
    vecs = []
    for text in texts:
        seed = int.from_bytes(hashlib.sha256(text.encode()).digest()[:8], "big")
        rng = np.random.default_rng(seed)
        v = rng.standard_normal(_DIM).astype(np.float32)
        v = v / np.linalg.norm(v)
        vecs.append(v)
    return np.array(vecs, dtype=np.float32)


# Canonical vocabulary for the fake resolver — simple dict lookup.
_VOCAB = {
    "garlic": "garlic",
    "tomato": "tomato",
    "basil": "basil",
    "olive oil": "olive oil",
    "pasta": "pasta",
    "onion": "onion",
    "salt": "salt",
    "pepper": "pepper",
    "butter": "butter",
    "flour": "flour",
    "old garlic": "garlic",  # near-synonym resolved to canonical
}


def _fake_resolver(raw: str) -> Ingredient | None:
    """Dict-lookup resolver that doesn't touch ONNX."""
    key = raw.strip().lower()
    canonical = _VOCAB.get(key)
    if canonical is None:
        return None
    return Ingredient(canonical_name=canonical, raw_text=raw)


def _make_unit_blob(dim: int = 1024) -> bytes:
    """Return a random unit float32 blob of ``dim`` dimensions."""
    v = np.random.default_rng(42).standard_normal(dim).astype(np.float32)
    v = v / np.linalg.norm(v)
    return v.tobytes()


def _seed_store(store: RecipeStore, n: int = 1000) -> None:
    """Seed the store with ``n`` synthetic recipes.

    Half the recipes contain 'garlic' so pantry-overlap tests always get hits.
    """
    recipes = []
    for i in range(n):
        if i % 2 == 0:
            ings = ["garlic", "tomato", "basil"]
        else:
            ings = ["flour", "butter", "sugar", "egg"]
        recipes.append(
            Recipe(
                id=f"r{i}",
                title=f"Recipe {i}",
                language="en",
                embedding=np.frombuffer(_make_unit_blob(), dtype=np.float32),
                ingredients_json=ings,
                instructions=f"Cook recipe {i}.",
            )
        )
    store.upsert(recipes)


# ---------------------------------------------------------------------------
# Fixtures
# ---------------------------------------------------------------------------


@pytest.fixture()
def tmp_store(tmp_path: Path) -> RecipeStore:
    """A RecipeStore backed by a temp sqlite file, seeded with 1000 recipes."""
    db = tmp_path / "recipes.db"
    store = RecipeStore(db)
    _seed_store(store, n=1000)
    return store


@pytest.fixture()
def pantry_path(tmp_path: Path) -> Path:
    """Path to a temp pantry.json file (does not exist yet)."""
    return tmp_path / "pantry.json"


@pytest.fixture()
def client(tmp_store: RecipeStore, pantry_path: Path) -> TestClient:
    """TestClient wired with fake store, resolver, embed_fn, and tmp pantry_path."""
    from pantryatlas.navigator.server import create_app

    app = create_app(
        store=tmp_store,
        resolver=_fake_resolver,
        embed_fn=_fake_embed,
        pantry_path=pantry_path,
    )
    return TestClient(app)


# ---------------------------------------------------------------------------
# AC-1: file exists + app importable (side-effect-free)
# ---------------------------------------------------------------------------


def test_import_app(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    """AC-1: importing server must NOT create ~/.pantryatlas/recipes.db.

    We reload the module under a temp HOME so the production ``app`` is rebuilt
    with the temp home path baked in.  After the import we confirm no DB file
    was created, proving store init is truly deferred to first use.
    """
    monkeypatch.setenv("HOME", str(tmp_path))
    # Force a clean reload so _DEFAULT_DB_PATH re-evaluates under the patched HOME.
    mod_name = "pantryatlas.navigator.server"
    if mod_name in sys.modules:
        del sys.modules[mod_name]
    mod = importlib.import_module(mod_name)

    assert mod.app is not None
    # No DB must have been created by the import alone.
    db_path = tmp_path / ".pantryatlas" / "recipes.db"
    assert not db_path.exists(), f"Import opened DB at {db_path} — store init is not lazy!"


# ---------------------------------------------------------------------------
# AC-2: route count ≥ 8
# ---------------------------------------------------------------------------


def test_route_count(client: TestClient) -> None:
    """AC-2: app has at least 8 routes (7 API + ≥1 static/root)."""
    # client.app is the FastAPI instance built by create_app
    assert len(client.app.routes) >= 8


# ---------------------------------------------------------------------------
# AC-9: GET /navigator/health
# ---------------------------------------------------------------------------


def test_health_returns_ok(client: TestClient) -> None:
    """AC-9: /navigator/health → 200, status='ok', recipe_count >= 0."""
    resp = client.get("/navigator/health")
    assert resp.status_code == 200
    body = resp.json()
    assert body["status"] == "ok"
    assert isinstance(body["recipe_count"], int)
    assert body["recipe_count"] >= 0


def test_health_recipe_count_matches_store(
    tmp_store: RecipeStore, pantry_path: Path
) -> None:
    """AC-9: recipe_count in /health is read from the store, not hardcoded."""
    from pantryatlas.navigator.server import create_app

    app = create_app(
        store=tmp_store,
        resolver=_fake_resolver,
        embed_fn=_fake_embed,
        pantry_path=pantry_path,
    )
    with TestClient(app) as c:
        resp = c.get("/navigator/health")
        assert resp.json()["recipe_count"] == tmp_store.count()


# ---------------------------------------------------------------------------
# AC-4: GET /navigator/pantry round-trip
# ---------------------------------------------------------------------------


def test_pantry_get_empty(client: TestClient) -> None:
    """GET /navigator/pantry on empty pantry returns an empty list."""
    resp = client.get("/navigator/pantry")
    assert resp.status_code == 200
    body = resp.json()
    assert isinstance(body, list)
    assert body == []


def test_pantry_put_then_get_roundtrip(client: TestClient) -> None:
    """AC-4: PUT /navigator/pantry with 5 items, then GET returns same 5 items."""
    items = [
        {"canonical_name": "garlic", "raw_text": "garlic"},
        {"canonical_name": "tomato", "raw_text": "tomato"},
        {"canonical_name": "basil", "raw_text": "basil"},
        {"canonical_name": "olive oil", "raw_text": "olive oil"},
        {"canonical_name": "pasta", "raw_text": "pasta"},
    ]
    put_resp = client.put("/navigator/pantry", json=items)
    assert put_resp.status_code == 200

    get_resp = client.get("/navigator/pantry")
    assert get_resp.status_code == 200
    returned = get_resp.json()
    assert len(returned) == 5
    canonical_names = {item["canonical_name"] for item in returned}
    expected = {"garlic", "tomato", "basil", "olive oil", "pasta"}
    assert canonical_names == expected


# ---------------------------------------------------------------------------
# AC-10: malformed PUT returns 422
# ---------------------------------------------------------------------------


def test_put_pantry_malformed_returns_422(client: TestClient) -> None:
    """AC-10: PUT /navigator/pantry with wrong shape → 422 from Pydantic."""
    resp = client.put("/navigator/pantry", json={"not": "a list"})
    assert resp.status_code == 422


def test_put_pantry_missing_required_field_422(client: TestClient) -> None:
    """Pydantic validation: missing canonical_name → 422."""
    resp = client.put("/navigator/pantry", json=[{"raw_text": "garlic"}])
    assert resp.status_code == 422


# ---------------------------------------------------------------------------
# AC-5: POST /navigator/pantry/items
# ---------------------------------------------------------------------------


def test_post_pantry_items_returns_201(client: TestClient) -> None:
    """AC-5: POST /navigator/pantry/items with {raw_text:'garlic'} → 201."""
    resp = client.post("/navigator/pantry/items", json={"raw_text": "garlic"})
    assert resp.status_code == 201
    body = resp.json()
    assert body["canonical_name"] == "garlic"


def test_post_pantry_items_persists(client: TestClient) -> None:
    """POST /navigator/pantry/items actually adds to the pantry."""
    client.post("/navigator/pantry/items", json={"raw_text": "garlic"})
    get_resp = client.get("/navigator/pantry")
    names = [item["canonical_name"] for item in get_resp.json()]
    assert "garlic" in names


def test_post_pantry_items_near_synonym(client: TestClient) -> None:
    """POST /navigator/pantry/items resolves near-synonyms via resolver."""
    resp = client.post("/navigator/pantry/items", json={"raw_text": "old garlic"})
    assert resp.status_code == 201
    assert resp.json()["canonical_name"] == "garlic"


def test_post_pantry_items_unknown_returns_422(client: TestClient) -> None:
    """POST /navigator/pantry/items with unresolvable text → 422."""
    resp = client.post("/navigator/pantry/items", json={"raw_text": "xylophone"})
    assert resp.status_code == 422


# ---------------------------------------------------------------------------
# AC-6: POST /navigator/pantry/resolve (no persist)
# ---------------------------------------------------------------------------


def test_post_pantry_resolve_no_persist(client: TestClient) -> None:
    """AC-6: POST /navigator/pantry/resolve returns canonical_name without persisting."""
    # Seed a known pantry state
    client.put(
        "/navigator/pantry",
        json=[{"canonical_name": "tomato", "raw_text": "tomato"}],
    )

    resp = client.post("/navigator/pantry/resolve", json={"raw": "old garlic"})
    assert resp.status_code == 200
    assert resp.json()["canonical_name"] == "garlic"

    # Pantry must remain unchanged (only 'tomato')
    get_resp = client.get("/navigator/pantry")
    names = [item["canonical_name"] for item in get_resp.json()]
    assert "garlic" not in names
    assert "tomato" in names


def test_post_pantry_resolve_unknown_returns_404(client: TestClient) -> None:
    """POST /navigator/pantry/resolve for unresolvable text → 404."""
    resp = client.post("/navigator/pantry/resolve", json={"raw": "xylophone"})
    assert resp.status_code == 404


# ---------------------------------------------------------------------------
# AC-7: DELETE /navigator/pantry/items/{name}
# ---------------------------------------------------------------------------


def test_delete_pantry_item(client: TestClient) -> None:
    """AC-7: DELETE /navigator/pantry/items/garlic removes only garlic."""
    client.put(
        "/navigator/pantry",
        json=[
            {"canonical_name": "garlic", "raw_text": "garlic"},
            {"canonical_name": "tomato", "raw_text": "tomato"},
        ],
    )
    del_resp = client.delete("/navigator/pantry/items/garlic")
    assert del_resp.status_code == 200

    get_resp = client.get("/navigator/pantry")
    names = [item["canonical_name"] for item in get_resp.json()]
    assert "garlic" not in names
    assert "tomato" in names


def test_delete_pantry_item_nonexistent_is_ok(client: TestClient) -> None:
    """DELETE of a nonexistent item is a no-op (idempotent), returns 200."""
    resp = client.delete("/navigator/pantry/items/doesnotexist")
    assert resp.status_code == 200


# ---------------------------------------------------------------------------
# AC-8: POST /navigator/recipes/from-pantry
# ---------------------------------------------------------------------------


def test_post_recipes_from_pantry_returns_results(client: TestClient) -> None:
    """AC-8: 5-item pantry against 1000-recipe store → ≥1 result with RankedRecipe shape."""
    # Seed pantry with 5 items that overlap the seeded store
    client.put(
        "/navigator/pantry",
        json=[
            {"canonical_name": "garlic", "raw_text": "garlic"},
            {"canonical_name": "tomato", "raw_text": "tomato"},
            {"canonical_name": "basil", "raw_text": "basil"},
            {"canonical_name": "flour", "raw_text": "flour"},
            {"canonical_name": "butter", "raw_text": "butter"},
        ],
    )
    resp = client.post("/navigator/recipes/from-pantry")
    assert resp.status_code == 200
    results = resp.json()
    assert isinstance(results, list)
    assert len(results) >= 1

    # Verify RankedRecipe shape on first result
    first = results[0]
    assert "recipe" in first
    assert "score" in first
    assert "coverage" in first
    assert "missing" in first
    assert isinstance(first["score"], float)
    assert 0.0 <= first["score"] <= 1.0
    # RecipeNLG is CC-BY-NC-4.0 — every result must carry source attribution.
    assert "source" in first
    assert "RecipeNLG" in first["source"]


def test_post_recipes_from_pantry_empty_pantry(client: TestClient) -> None:
    """POST /recipes/from-pantry with empty pantry returns empty list or 200."""
    resp = client.post("/navigator/recipes/from-pantry")
    assert resp.status_code == 200
    # Could return empty list or best-effort results; must not 500
    assert isinstance(resp.json(), list)


def test_post_recipes_from_pantry_sorted_descending(client: TestClient) -> None:
    """Results from /recipes/from-pantry are sorted by score descending."""
    client.put(
        "/navigator/pantry",
        json=[
            {"canonical_name": "garlic", "raw_text": "garlic"},
            {"canonical_name": "tomato", "raw_text": "tomato"},
            {"canonical_name": "basil", "raw_text": "basil"},
        ],
    )
    resp = client.post("/navigator/recipes/from-pantry")
    assert resp.status_code == 200
    results = resp.json()
    if len(results) >= 2:
        scores = [r["score"] for r in results]
        assert scores == sorted(scores, reverse=True)


def test_from_pantry_is_fast_mode(client: TestClient) -> None:
    """Instant from-pantry runs in fast mode → substitution_penalty is 0 (optimistic)."""
    client.put(
        "/navigator/pantry",
        json=[
            {"canonical_name": "garlic", "raw_text": "garlic"},
            {"canonical_name": "tomato", "raw_text": "tomato"},
        ],
    )
    results = client.post("/navigator/recipes/from-pantry").json()
    assert len(results) >= 1
    assert all(r["substitution_penalty"] == 0.0 for r in results)


# ---------------------------------------------------------------------------
# POST /navigator/recipes/from-pantry/refine
# ---------------------------------------------------------------------------


def test_refine_recomputes_substitution(client: TestClient) -> None:
    """Refine recomputes real substitution penalties on the client-sent recipes."""
    client.put(
        "/navigator/pantry",
        json=[
            {"canonical_name": "garlic", "raw_text": "garlic"},
            {"canonical_name": "tomato", "raw_text": "tomato"},
        ],
    )
    instant = client.post("/navigator/recipes/from-pantry").json()
    assert len(instant) >= 1
    top = [r["recipe"] for r in instant[:5]]

    resp = client.post("/navigator/recipes/from-pantry/refine", json=top)
    assert resp.status_code == 200
    refined = resp.json()
    assert len(refined) == len(top)
    for r in refined:
        assert "source" in r and "RecipeNLG" in r["source"]
        assert 0.0 <= r["substitution_penalty"] <= 1.0
    # Seeded candidates are missing 'basil' (pantry has only garlic+tomato), so
    # at least one refined recipe must have a non-zero substitution penalty.
    assert any(r["substitution_penalty"] > 0.0 for r in refined)
    # Refining can only lower scores (fast mode was optimistic).
    assert all(0.0 <= r["score"] <= 1.0 for r in refined)


def test_refine_empty_body(client: TestClient) -> None:
    """Refine with an empty recipe list returns an empty list, not a 500."""
    resp = client.post("/navigator/recipes/from-pantry/refine", json=[])
    assert resp.status_code == 200
    assert resp.json() == []


# ---------------------------------------------------------------------------
# POST /navigator/recipes/swaps
# ---------------------------------------------------------------------------


def test_swaps_returns_suggestions_for_missing(client: TestClient) -> None:
    """Swaps returns one entry per MISSING ingredient with a consistent shape."""
    client.put(
        "/navigator/pantry",
        json=[
            {"canonical_name": "garlic", "raw_text": "garlic"},
            {"canonical_name": "tomato", "raw_text": "tomato"},
            {"canonical_name": "onion", "raw_text": "onion"},
        ],
    )
    resp = client.post(
        "/navigator/recipes/swaps",
        json={"ingredients": ["garlic", "tomato", "basil", "mystery_xyz"]},
    )
    assert resp.status_code == 200
    swaps = resp.json()["swaps"]
    # Only the two missing ingredients (basil, mystery_xyz) get swap entries.
    assert {s["missing"] for s in swaps} == {"basil", "mystery_xyz"}
    for s in swaps:
        assert set(s.keys()) == {"missing", "best_swap", "similarity", "reason"}
        assert 0.0 <= s["similarity"] <= 1.0
        # Invariant: a suggestion exists iff there is no failure reason.
        assert (s["best_swap"] is None) == (s["reason"] is not None)
        if s["best_swap"] is not None:
            assert s["similarity"] >= 0.5


def test_swaps_no_pantry(client: TestClient) -> None:
    """With an empty pantry, every missing ingredient reports no_pantry."""
    resp = client.post(
        "/navigator/recipes/swaps",
        json={"ingredients": ["basil", "thyme"]},
    )
    assert resp.status_code == 200
    swaps = resp.json()["swaps"]
    assert len(swaps) == 2
    assert all(s["best_swap"] is None and s["reason"] == "no_pantry" for s in swaps)


# ---------------------------------------------------------------------------
# AC-11: no wildcard CORS header (real preflight check)
# ---------------------------------------------------------------------------


def test_no_wildcard_cors(client: TestClient) -> None:
    """AC-11: preflight from an evil origin must NOT receive a permissive ACAO header.

    Sends an OPTIONS preflight with a hostile origin.  Without CORSMiddleware the
    response carries no ACAO header at all (empty string), which satisfies both
    assertions.  A future accidental ``CORSMiddleware(allow_origins=["*"])`` or an
    echo-back policy would fail one of these assertions immediately.
    """
    resp = client.options(
        "/navigator/pantry",
        headers={
            "Origin": "https://evil.example",
            "Access-Control-Request-Method": "GET",
        },
    )
    acao = resp.headers.get("access-control-allow-origin", "")
    assert acao != "*", "Wildcard CORS must not be present"
    assert acao != "https://evil.example", "Evil origin must not be echoed back in ACAO"


# ---------------------------------------------------------------------------
# Full-suite stability check: idempotent health endpoint
# ---------------------------------------------------------------------------


def test_health_idempotent(client: TestClient) -> None:
    """Calling /navigator/health twice gives same recipe_count."""
    r1 = client.get("/navigator/health").json()
    r2 = client.get("/navigator/health").json()
    assert r1["recipe_count"] == r2["recipe_count"]


# ---------------------------------------------------------------------------
# Criterion 2 sanity via module-level app (side-effect-free)
# ---------------------------------------------------------------------------


def test_module_level_app_route_count(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    """The module-level ``app`` has ≥ 8 routes AND importing it is side-effect-free.

    Reloads the module under a temp HOME to ensure the production app bakes
    in the temp path, then asserts neither the DB nor the .pantryatlas dir was
    created by the import alone.
    """
    monkeypatch.setenv("HOME", str(tmp_path))
    mod_name = "pantryatlas.navigator.server"
    if mod_name in sys.modules:
        del sys.modules[mod_name]
    mod = importlib.import_module(mod_name)

    assert len(mod.app.routes) >= 8

    # Confirm import had no FS side effects.
    pantryatlas_dir = tmp_path / ".pantryatlas"
    assert not pantryatlas_dir.exists(), (
        f"Import created {pantryatlas_dir} — store init is not lazy!"
    )
