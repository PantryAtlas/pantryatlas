import io
from pathlib import Path

import httpx
import numpy as np
from fastapi.testclient import TestClient
from PIL import Image

from pantryatlas.gemma.client import GemmaClient
from pantryatlas.inference.providers.lan_endpoint import LanEndpointProvider
from pantryatlas.inference.registry import ProviderRegistry
from pantryatlas.navigator.server import create_app
from pantryatlas.store.kitchen import KitchenStore


class _InMemoryStore:
    def count(self) -> int:
        return 0


def _chat_transport(content: str) -> httpx.MockTransport:
    def handler(request: httpx.Request) -> httpx.Response:
        return httpx.Response(200, json={"choices": [{"message": {"content": content}}]})
    return httpx.MockTransport(handler)


def _tiny_jpeg() -> bytes:
    buf = io.BytesIO()
    Image.new("RGB", (4, 4), (200, 180, 120)).save(buf, format="JPEG")
    return buf.getvalue()


def _make_app(reg: ProviderRegistry, tmp_path: Path) -> TestClient:
    app = create_app(
        store=_InMemoryStore(),
        resolver=lambda raw: None,
        embed_fn=lambda texts: np.zeros((len(texts), 8)),
        pantry_path=tmp_path / "pantry.json",
        provider_registry=reg,
        providers_config_path=tmp_path / "providers.json",
        kitchen=KitchenStore(tmp_path / "kitchen.db"),
    )
    return TestClient(app)


def _app(tmp_path: Path) -> TestClient:
    reg = ProviderRegistry([
        LanEndpointProvider(name="on-board", base_url="http://127.0.0.1:8080",
                            priority=100, capabilities=["text"],
                            client=GemmaClient(transport=_chat_transport("ok")),
                            health_check=lambda: True),
    ])
    return _make_app(reg, tmp_path)


def test_list_providers(tmp_path):
    client = _app(tmp_path)
    r = client.get("/navigator/providers")
    assert r.status_code == 200
    assert r.json()[0]["name"] == "on-board"


def test_add_lan_provider_persists(tmp_path):
    client = _app(tmp_path)
    r = client.post("/navigator/providers", json={
        "name": "desktop", "base_url": "http://192.168.1.50:8080", "multimodal": True,
    })
    assert r.status_code == 201
    names = [p["name"] for p in client.get("/navigator/providers").json()]
    assert "desktop" in names
    assert (tmp_path / "providers.json").exists()


def test_delete_provider(tmp_path):
    client = _app(tmp_path)
    client.post("/navigator/providers", json={
        "name": "desktop", "base_url": "http://192.168.1.50:8080", "multimodal": False,
    })
    assert client.delete("/navigator/providers/desktop").status_code == 200
    names = [p["name"] for p in client.get("/navigator/providers").json()]
    assert "desktop" not in names


def test_vision_endpoint_routes_through_registry(tmp_path):
    canned = '{"detected":[{"label":"flour","confidence":0.9}]}'
    reg = ProviderRegistry([
        LanEndpointProvider(
            name="desk", base_url="http://desk:8080", priority=10,
            capabilities=["text", "vision"],
            client=GemmaClient(base_url="http://desk:8080", transport=_chat_transport(canned)),
            health_check=lambda: True,
        ),
    ])
    client = _make_app(reg, tmp_path)
    r = client.post(
        "/navigator/vision/parse-shelf",
        files={"image": ("shelf.jpg", _tiny_jpeg(), "image/jpeg")},
    )
    assert r.status_code == 200
    assert "flour" in r.json()["items"]


def test_vision_endpoint_503_when_no_vision_provider(tmp_path):
    reg = ProviderRegistry([
        LanEndpointProvider(
            name="text-only", base_url="http://x:8080", priority=10,
            capabilities=["text"],
            client=GemmaClient(transport=_chat_transport("x")),
            health_check=lambda: True,
        ),
    ])
    client = _make_app(reg, tmp_path)
    r = client.post(
        "/navigator/vision/parse-shelf",
        files={"image": ("shelf.jpg", _tiny_jpeg(), "image/jpeg")},
    )
    assert r.status_code == 503
    assert r.json()["error"] == "vision_unavailable"
