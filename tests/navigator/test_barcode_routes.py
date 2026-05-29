# tests/navigator/test_barcode_routes.py
from __future__ import annotations

from pathlib import Path

import numpy as np
from fastapi.testclient import TestClient

from pantryatlas.pantry.models import Ingredient
from pantryatlas.store.kitchen import KitchenStore


def _fake_resolver(raw: str) -> Ingredient | None:
    key = raw.strip().lower()
    known = {"garlic", "tomato", "noodles", "pasta"}
    return Ingredient(canonical_name=key, raw_text=raw) if key in known else None


def _fake_embed(texts): return np.ones((len(texts), 8), dtype=np.float32)


class _FakeStore:
    def count(self): return 0
    def get(self, rid): return None
    def iter_overlapping(self, names): return []


def _client(tmp_path: Path) -> TestClient:
    from pantryatlas.navigator.server import create_app
    app = create_app(
        store=_FakeStore(), resolver=_fake_resolver, embed_fn=_fake_embed,
        pantry_path=tmp_path / "pantry.json", kitchen=KitchenStore(tmp_path / "kitchen.db"),
    )
    return TestClient(app)


def test_add_with_explicit_canonical_and_source(tmp_path):
    client = _client(tmp_path)
    r = client.post("/navigator/pantry/items",
                    json={"raw_text": "Thai Kitchen Rice Noodles", "canonical_name": "noodles",
                          "source": "barcode"})
    assert r.status_code == 201
    items = {i["canonical_name"]: i for i in client.get("/navigator/pantry").json()}
    assert "noodles" in items
    assert items["noodles"]["source"] == "barcode"
    assert items["noodles"]["raw_text"] == "Thai Kitchen Rice Noodles"


def test_add_without_canonical_still_resolves(tmp_path):
    client = _client(tmp_path)
    r = client.post("/navigator/pantry/items", json={"raw_text": "garlic"})
    assert r.status_code == 201
    assert client.get("/navigator/pantry").json()[0]["source"] == "manual"
