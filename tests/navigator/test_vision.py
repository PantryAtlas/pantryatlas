"""T-014: Tests for shelf-photo ingredient detection.

Test plan
---------
Unit (mock-gemma, default pytest run):
  - parse_shelf returns DetectedIngredient list from canned JSON client
  - parse_shelf repair fallback handles slightly-malformed JSON (prose wrapper)
  - parse_shelf regex rescue handles very broken JSON (only label keys present)
  - parse_shelf returns empty list when client returns empty detected array
  - VisionUnavailable from client propagates out of parse_shelf
  - POST /navigator/vision/parse-shelf → 200 + {detected, items} with mock client
  - POST /navigator/vision/parse-shelf → 503 {"error":"vision_unavailable"} with
    None vision_client (production default)
  - POST /navigator/vision/parse-shelf → 503 when client raises VisionUnavailable

Pi integration (opt-in, deselected by default):
  - Live Gemma 4 multimodal with real fixture → ≥1 detection
"""

from __future__ import annotations

import io
import json
from pathlib import Path
from unittest.mock import MagicMock

import numpy as np
import pytest
from fastapi.testclient import TestClient

from pantryatlas.navigator.vision import (
    DetectedIngredient,
    VisionUnavailable,
    _parse_detected,  # noqa: PLC2701  (internal but tested directly)
    parse_shelf,
)

# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------

FIXTURES_DIR = Path(__file__).parent.parent / "fixtures"
SHELF_FIXTURE = FIXTURES_DIR / "test-shelf.jpg"

_CANNED_JSON = json.dumps(
    {
        "detected": [
            {"label": "tomato", "confidence": 0.92},
            {"label": "carrot", "confidence": 0.87},
            {"label": "broccoli", "confidence": 0.75},
        ]
    }
)

_EMPTY_JSON = json.dumps({"detected": []})

_PROSE_WRAPPED = (
    "Here are the ingredients I detected:\n"
    + json.dumps(
        {
            "detected": [
                {"label": "onion", "confidence": 0.80},
                {"label": "garlic", "confidence": 0.70},
            ]
        }
    )
    + "\nLet me know if you need more details."
)

_LABEL_ONLY_RESPONSE = (
    '{"detected": [{"label": "pepper", "confide...'  # truncated/broken JSON
)


def _fake_client(response_text: str) -> MagicMock:
    """Return a mock GemmaClient whose vision_generate() returns response_text."""
    client = MagicMock()
    client.vision_generate.return_value = response_text
    return client


def _unavailable_client() -> MagicMock:
    """Return a mock GemmaClient whose vision_generate() raises VisionUnavailable."""
    client = MagicMock()
    client.vision_generate.side_effect = VisionUnavailable("mmproj not loaded")
    return client


def _shelf_image_bytes() -> bytes:
    """Return bytes of the synthetic test-shelf.jpg fixture."""
    return SHELF_FIXTURE.read_bytes()


# ---------------------------------------------------------------------------
# Unit tests — parse_shelf
# ---------------------------------------------------------------------------


def test_parse_shelf_returns_detected_ingredients() -> None:
    """Canned JSON response yields correctly typed DetectedIngredient list."""
    client = _fake_client(_CANNED_JSON)
    result = parse_shelf(_shelf_image_bytes(), client)

    assert isinstance(result, list)
    assert len(result) == 3

    labels = [d.label for d in result]
    assert "tomato" in labels
    assert "carrot" in labels
    assert "broccoli" in labels

    for d in result:
        assert isinstance(d, DetectedIngredient)
        assert isinstance(d.label, str)
        assert 0.0 <= d.confidence <= 1.0


def test_parse_shelf_correct_values() -> None:
    """Confidence values are preserved from the canned JSON."""
    client = _fake_client(_CANNED_JSON)
    result = parse_shelf(_shelf_image_bytes(), client)

    by_label = {d.label: d for d in result}
    assert abs(by_label["tomato"].confidence - 0.92) < 1e-6
    assert abs(by_label["carrot"].confidence - 0.87) < 1e-6


def test_parse_shelf_repair_prose_wrapper() -> None:
    """Repair fallback: JSON embedded in prose is extracted correctly."""
    client = _fake_client(_PROSE_WRAPPED)
    result = parse_shelf(_shelf_image_bytes(), client)

    assert len(result) == 2
    labels = {d.label for d in result}
    assert "onion" in labels
    assert "garlic" in labels


def test_parse_shelf_regex_rescue_partial_json() -> None:
    """Regex rescue: label keys extracted even from truncated/broken JSON."""
    client = _fake_client(_LABEL_ONLY_RESPONSE)
    result = parse_shelf(_shelf_image_bytes(), client)
    # Regex should rescue "pepper" from the partial JSON
    assert len(result) >= 1
    assert result[0].label == "pepper"
    # Confidence falls back to 0.5 in regex rescue
    assert result[0].confidence == pytest.approx(0.5)


def test_parse_shelf_empty_detected() -> None:
    """Empty detected array returns empty list without error."""
    client = _fake_client(_EMPTY_JSON)
    result = parse_shelf(_shelf_image_bytes(), client)
    assert result == []


def test_parse_shelf_propagates_vision_unavailable() -> None:
    """VisionUnavailable from the client propagates out of parse_shelf."""
    client = _unavailable_client()
    with pytest.raises(VisionUnavailable):
        parse_shelf(_shelf_image_bytes(), client)


# ---------------------------------------------------------------------------
# Unit tests — _parse_detected (internal, tested directly)
# ---------------------------------------------------------------------------


def test_parse_detected_direct_json() -> None:
    """_parse_detected handles direct JSON strings."""
    result = _parse_detected(_CANNED_JSON)
    assert result is not None
    assert len(result) == 3


def test_parse_detected_none_on_garbage() -> None:
    """_parse_detected returns None for completely unparseable text."""
    result = _parse_detected("This is not JSON at all, not even close.")
    # Either None or empty list (regex rescue finds no labels)
    assert result is None or result == []


def test_parse_detected_confidence_clamped() -> None:
    """Confidence values outside [0, 1] are clamped."""
    raw = json.dumps({"detected": [{"label": "egg", "confidence": 2.5}]})
    result = _parse_detected(raw)
    assert result is not None
    assert result[0].confidence == pytest.approx(1.0)

    raw2 = json.dumps({"detected": [{"label": "milk", "confidence": -0.5}]})
    result2 = _parse_detected(raw2)
    assert result2 is not None
    assert result2[0].confidence == pytest.approx(0.0)


# ---------------------------------------------------------------------------
# Helpers for route tests
# ---------------------------------------------------------------------------


def _make_vision_client(
    tmp_path: Path,
    vision_client,
) -> TestClient:
    """Build a minimal test app with the given vision_client injected."""
    from pantryatlas.navigator.server import create_app
    from pantryatlas.pantry.models import Ingredient
    from pantryatlas.store.recipes import RecipeStore

    db = tmp_path / "v.db"
    store = RecipeStore(db)

    def _resolver(raw: str) -> Ingredient | None:
        return Ingredient(canonical_name=raw, raw_text=raw)

    def _embed(texts: list[str]) -> np.ndarray:
        return np.zeros((len(texts), 8), dtype=np.float32)

    app = create_app(
        store=store,
        resolver=_resolver,
        embed_fn=_embed,
        pantry_path=tmp_path / "pantry.json",
        vision_client=vision_client,
    )
    return TestClient(app)


# ---------------------------------------------------------------------------
# Unit tests — HTTP route
# ---------------------------------------------------------------------------


def test_route_registered() -> None:
    """AC-3: /navigator/vision/parse-shelf appears in the module-level app routes."""
    import importlib
    import sys
    from pathlib import Path as _P

    tmp = _P("/tmp/pantry_route_test")
    tmp.mkdir(exist_ok=True)
    mod_name = "pantryatlas.navigator.server"
    import os

    old_home = os.environ.get("HOME")
    os.environ["HOME"] = str(tmp)
    if mod_name in sys.modules:
        del sys.modules[mod_name]
    try:
        mod = importlib.import_module(mod_name)
        paths = [r.path for r in mod.app.routes]
        assert "/navigator/vision/parse-shelf" in paths, (
            f"Route not found. Available: {paths}"
        )
    finally:
        if old_home is not None:
            os.environ["HOME"] = old_home
        else:
            del os.environ["HOME"]
        if mod_name in sys.modules:
            del sys.modules[mod_name]


def test_vision_route_success(tmp_path: Path) -> None:
    """Route returns 200 + {detected, items} when mock client returns canned JSON."""
    client = _fake_client(_CANNED_JSON)
    tc = _make_vision_client(tmp_path, client)

    image_bytes = _shelf_image_bytes()
    resp = tc.post(
        "/navigator/vision/parse-shelf",
        files={"image": ("test-shelf.jpg", io.BytesIO(image_bytes), "image/jpeg")},
    )
    assert resp.status_code == 200
    body = resp.json()
    assert "detected" in body
    assert "items" in body
    assert isinstance(body["detected"], list)
    assert isinstance(body["items"], list)
    assert len(body["detected"]) == 3
    assert len(body["items"]) == 3
    assert "tomato" in body["items"]
    assert "carrot" in body["items"]
    assert "broccoli" in body["items"]

    # Verify detected shape
    first = body["detected"][0]
    assert "label" in first
    assert "confidence" in first


def test_vision_route_503_when_no_vision_client(tmp_path: Path) -> None:
    """AC-8: vision_client=None → 503 {"error":"vision_unavailable"}."""
    tc = _make_vision_client(tmp_path, None)

    image_bytes = _shelf_image_bytes()
    resp = tc.post(
        "/navigator/vision/parse-shelf",
        files={"image": ("test-shelf.jpg", io.BytesIO(image_bytes), "image/jpeg")},
    )
    assert resp.status_code == 503
    assert resp.json() == {"error": "vision_unavailable"}


def test_vision_route_503_when_client_raises(tmp_path: Path) -> None:
    """AC-8 variant: VisionUnavailable from client → 503."""
    client = _unavailable_client()
    tc = _make_vision_client(tmp_path, client)

    image_bytes = _shelf_image_bytes()
    resp = tc.post(
        "/navigator/vision/parse-shelf",
        files={"image": ("test-shelf.jpg", io.BytesIO(image_bytes), "image/jpeg")},
    )
    assert resp.status_code == 503
    assert resp.json() == {"error": "vision_unavailable"}


def test_vision_route_empty_upload(tmp_path: Path) -> None:
    """Empty image upload returns 400."""
    client = _fake_client(_CANNED_JSON)
    tc = _make_vision_client(tmp_path, client)

    resp = tc.post(
        "/navigator/vision/parse-shelf",
        files={"image": ("empty.jpg", io.BytesIO(b""), "image/jpeg")},
    )
    assert resp.status_code == 400


def test_vision_route_empty_detection(tmp_path: Path) -> None:
    """When Gemma returns empty detected list, items is [] and status is 200."""
    client = _fake_client(_EMPTY_JSON)
    tc = _make_vision_client(tmp_path, client)

    image_bytes = _shelf_image_bytes()
    resp = tc.post(
        "/navigator/vision/parse-shelf",
        files={"image": ("test-shelf.jpg", io.BytesIO(image_bytes), "image/jpeg")},
    )
    assert resp.status_code == 200
    body = resp.json()
    assert body["items"] == []
    assert body["detected"] == []


# ---------------------------------------------------------------------------
# Pi integration test (deselected by default — requires real Gemma multimodal)
# ---------------------------------------------------------------------------


@pytest.mark.pi_integration
def test_vision_route_live_detection(tmp_path: Path) -> None:
    """Live integration: real Gemma 4 E4B multimodal → ≥1 detection from fixture.

    PRECONDITIONS (must be met before this test can pass):
    1. llama-server running at http://127.0.0.1:8080 WITH --mmproj pointing to
       the Gemma 4 E4B vision projector GGUF.
    2. The mmproj file must be downloaded (see docs/gemma4-verified-specs.md
       for the expected URL and SHA256 placeholder).

    Run with: pytest tests/navigator/test_vision.py -m pi_integration -v
    """
    from pantryatlas.gemma.client import GemmaClient

    real_client = GemmaClient(base_url="http://127.0.0.1:8080", timeout_s=120.0)
    image_bytes = _shelf_image_bytes()
    result = parse_shelf(image_bytes, real_client)
    assert isinstance(result, list)
    assert len(result) >= 1, (
        "Expected ≥1 detection from fixture, got 0. "
        "Check that --mmproj is passed to llama-server."
    )
    for d in result:
        assert isinstance(d.label, str) and d.label
        assert 0.0 <= d.confidence <= 1.0
