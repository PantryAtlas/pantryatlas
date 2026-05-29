# tests/navigator/test_loop_routes.py
from __future__ import annotations

from pathlib import Path

import numpy as np
from fastapi.testclient import TestClient

from pantryatlas.pantry.models import Ingredient
from pantryatlas.store.kitchen import KitchenStore


def _fake_resolver(raw: str) -> Ingredient | None:
    key = raw.strip().lower()
    known = {"garlic", "tomato", "basil", "onion", "salt", "pasta"}
    return Ingredient(canonical_name=key, raw_text=raw) if key in known else None


def _fake_embed(texts: list[str]) -> np.ndarray:
    return np.ones((len(texts), 8), dtype=np.float32)


class _FakeRecipe:
    def __init__(self, ingredients): self.ingredients_json = ingredients


class _FakeStore:
    """Duck-typed RecipeStore — no sqlite-vec, runs on Pi 3.11."""
    def __init__(self): self._recipes = {"r1": _FakeRecipe(["garlic", "tomato", "basil"])}
    def count(self): return len(self._recipes)
    def get(self, rid): return self._recipes.get(rid)
    def iter_overlapping(self, names): return []


def _client(tmp_path: Path) -> TestClient:
    from pantryatlas.navigator.server import create_app
    kitchen = KitchenStore(tmp_path / "kitchen.db")
    app = create_app(
        store=_FakeStore(), resolver=_fake_resolver, embed_fn=_fake_embed,
        pantry_path=tmp_path / "pantry.json", kitchen=kitchen,
    )
    return TestClient(app)


def test_pantry_roundtrips_through_kitchen_store(tmp_path):
    client = _client(tmp_path)
    assert client.get("/navigator/pantry").json() == []
    r = client.post("/navigator/pantry/items", json={"raw_text": "garlic"})
    assert r.status_code == 201
    items = client.get("/navigator/pantry").json()
    assert len(items) == 1
    assert items[0]["canonical_name"] == "garlic"
    assert items[0]["state"] == "present"          # new field surfaced
    client.delete("/navigator/pantry/items/garlic")
    assert client.get("/navigator/pantry").json() == []


def test_put_replaces_pantry(tmp_path):
    client = _client(tmp_path)
    client.put("/navigator/pantry", json=[
        {"canonical_name": "tomato", "raw_text": "tomato"},
        {"canonical_name": "basil", "raw_text": "basil"},
    ])
    names = {i["canonical_name"] for i in client.get("/navigator/pantry").json()}
    assert names == {"tomato", "basil"}


def test_consume_route(tmp_path):
    client = _client(tmp_path)
    client.post("/navigator/pantry/items", json={"raw_text": "garlic"})
    r = client.post("/navigator/pantry/items/garlic/consume", json={"coarse_amount": "half"})
    assert r.status_code == 200
    assert r.json()["state"] == "low"
    assert client.post("/navigator/pantry/items/ghost/consume",
                       json={"coarse_amount": "used_up"}).status_code == 404


def test_cook_route_logs_and_decrements(tmp_path):
    client = _client(tmp_path)
    for n in ("garlic", "tomato", "basil"):
        client.post("/navigator/pantry/items", json={"raw_text": n})
    r = client.post(
        "/navigator/cook",
        json={"recipe_id": "r1", "dish_name": "Pomodoro", "servings": 2},
    )
    assert r.status_code == 201
    body = r.json()
    assert set(body["matched"]) == {"garlic", "tomato", "basil"}   # derived from recipe r1
    states = {i["canonical_name"]: i["state"] for i in client.get("/navigator/pantry").json()}
    assert states == {"garlic": "low", "tomato": "low", "basil": "low"}
    meals = client.get("/navigator/meals").json()
    assert meals[0]["dish_name"] == "Pomodoro"


def test_cook_route_explicit_consumed(tmp_path):
    client = _client(tmp_path)
    client.post("/navigator/pantry/items", json={"raw_text": "onion"})
    r = client.post("/navigator/cook", json={
        "dish_name": "Soup",
        "consumed": [{"canonical_name": "onion", "coarse_amount": "used_up"}],
    })
    assert r.status_code == 201
    states = {i["canonical_name"]: i["state"] for i in client.get("/navigator/pantry").json()}
    assert states["onion"] == "used_up"


def test_waste_route(tmp_path):
    client = _client(tmp_path)
    client.post("/navigator/pantry/items", json={"raw_text": "tomato"})
    client.post("/navigator/pantry/items/tomato/consume", json={"coarse_amount": "discarded"})
    tally = client.get("/navigator/waste").json()
    assert tally["discarded"] == 1 and tally["total"] == 1


def test_cook_unknown_recipe_id_still_logs(tmp_path):
    """POST /cook with an unknown recipe_id → 201, matched=[], event created."""
    client = _client(tmp_path)
    r = client.post(
        "/navigator/cook",
        json={"dish_name": "Mystery", "recipe_id": "no-such-id"},
    )
    assert r.status_code == 201
    body = r.json()
    assert body["matched"] == []
    meals = client.get("/navigator/meals").json()
    assert meals[0]["dish_name"] == "Mystery"


def _client_with_r2(tmp_path: Path) -> TestClient:
    """A client whose _FakeStore also contains recipe r2 with saffron (unknown)."""
    from pantryatlas.navigator.server import create_app

    class _FakeStoreExtended:
        def __init__(self):
            self._recipes = {
                "r1": _FakeRecipe(["garlic", "tomato", "basil"]),
                "r2": _FakeRecipe(["garlic", "saffron"]),  # saffron unknown to _fake_resolver
            }

        def count(self): return len(self._recipes)
        def get(self, rid): return self._recipes.get(rid)
        def iter_overlapping(self, names): return []

    kitchen = KitchenStore(tmp_path / "kitchen.db")
    app = create_app(
        store=_FakeStoreExtended(), resolver=_fake_resolver, embed_fn=_fake_embed,
        pantry_path=tmp_path / "pantry.json", kitchen=kitchen,
    )
    return TestClient(app)


def test_cook_unresolvable_ingredient_falls_back_to_raw_token(tmp_path):
    """Resolver returns None for 'saffron' → raw token used as canonical_name, no crash."""
    client = _client_with_r2(tmp_path)
    # Add garlic so it can be matched; saffron is not on hand → unmatched raw token
    client.post("/navigator/pantry/items", json={"raw_text": "garlic"})

    r = client.post("/navigator/cook", json={"dish_name": "Saffron Rice", "recipe_id": "r2"})
    assert r.status_code == 201
    body = r.json()
    # garlic is on hand → matched; saffron resolved to None → raw token "saffron" used
    assert "garlic" in body["matched"]
    assert "saffron" in body["unmatched"]
