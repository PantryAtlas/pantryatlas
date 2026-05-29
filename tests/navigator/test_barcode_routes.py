# tests/navigator/test_barcode_routes.py
from __future__ import annotations

import io as _io
from pathlib import Path

import httpx
import numpy as np
import zxingcpp
from fastapi.testclient import TestClient
from PIL import Image

from pantryatlas.navigator.openfoodfacts import OpenFoodFactsClient
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


# ---------------------------------------------------------------------------
# Task 5: POST /navigator/pantry/barcode route
# ---------------------------------------------------------------------------


def _barcode_png(value="737628064502") -> bytes:
    img = zxingcpp.write_barcode(zxingcpp.BarcodeFormat.EAN13, value)
    pil = img if isinstance(img, Image.Image) else Image.fromarray(img)
    buf = _io.BytesIO()
    pil.convert("RGB").resize((pil.width * 4, pil.height * 4)).save(buf, format="PNG")
    return buf.getvalue()


def _client_with_off(tmp_path, handler) -> TestClient:
    from pantryatlas.navigator.server import create_app
    app = create_app(
        store=_FakeStore(), resolver=_fake_resolver, embed_fn=_fake_embed,
        pantry_path=tmp_path / "pantry.json", kitchen=KitchenStore(tmp_path / "kitchen.db"),
    )
    app.state.off_client = OpenFoodFactsClient(transport=httpx.MockTransport(handler))
    return TestClient(app)


def _off_found(req):
    return httpx.Response(200, json={"status": 1, "product": {
        "product_name": "Rice Noodles", "brands": "Thai Kitchen",
        "ingredients_tags": ["en:rice-noodles"], "categories_tags": ["en:pastas", "en:noodles"]}})


def test_barcode_route_returns_candidate(tmp_path):
    client = _client_with_off(tmp_path, _off_found)
    r = client.post("/navigator/pantry/barcode",
                    files={"image": ("b.png", _barcode_png(), "image/png")})
    assert r.status_code == 200
    body = r.json()
    assert body["found"] is True
    assert body["product"]["name"] == "Rice Noodles"
    assert body["proposed"]["canonical_name"] == "noodles"
    # route is read-only: nothing added yet
    assert client.get("/navigator/pantry").json() == []


def test_barcode_route_no_barcode_returns_422(tmp_path):
    client = _client_with_off(tmp_path, _off_found)
    buf = _io.BytesIO()
    Image.new("RGB", (200, 200), "white").save(buf, format="PNG")
    r = client.post("/navigator/pantry/barcode",
                    files={"image": ("blank.png", buf.getvalue(), "image/png")})
    assert r.status_code == 422


def test_barcode_route_off_not_found(tmp_path):
    def off_missing(req): return httpx.Response(200, json={"status": 0})
    client = _client_with_off(tmp_path, off_missing)
    r = client.post("/navigator/pantry/barcode",
                    files={"image": ("b.png", _barcode_png(), "image/png")})
    assert r.status_code == 200
    assert r.json()["found"] is False
    assert r.json()["code"]


def test_barcode_route_off_down_is_graceful(tmp_path):
    def off_down(req): raise httpx.ConnectError("boom")
    client = _client_with_off(tmp_path, off_down)
    r = client.post("/navigator/pantry/barcode",
                    files={"image": ("b.png", _barcode_png(), "image/png")})
    assert r.status_code == 200
    assert r.json()["found"] is False
    assert r.json().get("error") == "off_unavailable"
