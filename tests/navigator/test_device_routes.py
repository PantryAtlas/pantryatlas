from __future__ import annotations

from pathlib import Path

import numpy as np
from fastapi.testclient import TestClient

from pantryatlas.pantry.models import Ingredient
from pantryatlas.store.kitchen import KitchenStore


def _resolver(raw): return Ingredient(canonical_name=raw.lower(), raw_text=raw)
def _embed(texts): return np.ones((len(texts), 8), dtype=np.float32)


class _FakeStore:
    def count(self): return 0
    def get(self, rid): return None
    def iter_overlapping(self, names): return []


def _client(tmp_path: Path) -> TestClient:
    from pantryatlas.navigator.server import create_app
    app = create_app(store=_FakeStore(), resolver=_resolver, embed_fn=_embed,
                     pantry_path=tmp_path / "pantry.json",
                     kitchen=KitchenStore(tmp_path / "kitchen.db"))
    return TestClient(app)


def test_enroll_list_approve_me_flow(tmp_path):
    client = _client(tmp_path)
    # enroll
    r = client.post("/navigator/devices/enroll",
                    json={"name": "Counter Pi", "role": "sensor", "kind": "pi-cam", "caps": ["camera"]})
    assert r.status_code == 201
    did = r.json()["device_id"]
    assert r.json()["status"] == "pending"
    # bad role rejected
    assert client.post("/navigator/devices/enroll", json={"name": "X", "role": "bogus"}).status_code == 422
    # list shows it, never leaks token_hash
    listing = client.get("/navigator/devices").json()
    assert any(d["device_id"] == did for d in listing)
    assert all("token_hash" not in d for d in listing)
    # approve → raw token once
    appr = client.post(f"/navigator/devices/{did}/approve")
    assert appr.status_code == 200
    token = appr.json()["token"]
    assert token and appr.json()["status"] == "paired"
    # the token authenticates /devices/me
    me = client.get("/navigator/devices/me", headers={"Authorization": f"Bearer {token}"})
    assert me.status_code == 200 and me.json()["device_id"] == did
    assert "token" not in me.json() and "token_hash" not in me.json()
    # subsequent list still never carries the raw token
    assert all("token" not in d for d in client.get("/navigator/devices").json())


def test_me_rejects_bad_or_missing_token(tmp_path):
    client = _client(tmp_path)
    assert client.get("/navigator/devices/me").status_code == 401
    assert client.get("/navigator/devices/me",
                      headers={"Authorization": "Bearer nope"}).status_code == 401
    assert client.get("/navigator/devices/me",
                      headers={"Authorization": "notbearer x"}).status_code == 401


def test_reject_and_delete(tmp_path):
    client = _client(tmp_path)
    did = client.post("/navigator/devices/enroll", json={"name": "X", "role": "compute"}).json()["device_id"]
    token = client.post(f"/navigator/devices/{did}/approve").json()["token"]
    assert client.post(f"/navigator/devices/{did}/reject").json()["status"] == "rejected"
    # rejected token no longer verifies
    assert client.get("/navigator/devices/me",
                      headers={"Authorization": f"Bearer {token}"}).status_code == 401
    assert client.delete(f"/navigator/devices/{did}").json()["deleted"] == did
    assert client.post(f"/navigator/devices/ghost/approve").status_code == 404
    assert client.delete("/navigator/devices/ghost").status_code == 404
