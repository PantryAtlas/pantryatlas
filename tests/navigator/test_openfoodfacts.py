# tests/navigator/test_openfoodfacts.py
from __future__ import annotations

import httpx
import pytest

from pantryatlas.navigator.openfoodfacts import OpenFoodFactsClient, OffUnavailable


def _client(handler) -> OpenFoodFactsClient:
    return OpenFoodFactsClient(transport=httpx.MockTransport(handler))


def test_found_returns_product():
    def handler(req: httpx.Request) -> httpx.Response:
        assert "/api/v2/product/737628064502.json" in str(req.url)
        assert req.headers["user-agent"].startswith("PantryAtlas")
        return httpx.Response(200, json={
            "status": 1,
            "product": {"product_name": "Rice Noodles", "brands": "Thai Kitchen",
                        "categories_tags": ["en:noodles"], "ingredients_tags": ["en:rice-noodles"]},
        })
    product = _client(handler).get_product("737628064502")
    assert product is not None
    assert product["product_name"] == "Rice Noodles"
    assert product["ingredients_tags"] == ["en:rice-noodles"]


def test_status_zero_returns_none():
    def handler(req): return httpx.Response(200, json={"status": 0, "status_verbose": "not found"})
    assert _client(handler).get_product("000000000000") is None


def test_404_returns_none():
    def handler(req): return httpx.Response(404, json={"status": 0})
    assert _client(handler).get_product("000000000000") is None


def test_network_error_raises_off_unavailable():
    def handler(req): raise httpx.ConnectError("boom")
    with pytest.raises(OffUnavailable):
        _client(handler).get_product("737628064502")


def test_5xx_raises_off_unavailable():
    def handler(req): return httpx.Response(503, text="down")
    with pytest.raises(OffUnavailable):
        _client(handler).get_product("737628064502")
