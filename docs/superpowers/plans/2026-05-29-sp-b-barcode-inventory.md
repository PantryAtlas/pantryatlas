# SP-B (slice 1) Barcode → Open Food Facts → Pantry — Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Scan a packaged product's barcode (photographed on any phone, iOS included), look it up in Open Food Facts, and add it to the pantry as a canonical ingredient — all decoded host-side, cached, and verifiable on the Pi today.

**Architecture:** A pure-HTTP `OpenFoodFactsClient` (httpx, MockTransport-testable) + a host-side `decode_barcode` (`zxing-cpp` + PIL) + a `product_to_ingredient` mapper (OFF tags → existing resolver). A read-only `POST /navigator/pantry/barcode` route decodes the uploaded image, looks up OFF (cache-first via a new `off_cache` table in `KitchenStore`), maps to a canonical candidate, and returns it; the confirm sheet then adds via the existing add path (extended to carry an explicit `canonical_name` + `source="barcode"`).

**Tech Stack:** Python 3.11+ · FastAPI · `zxing-cpp` (pure wheel) · Pillow · httpx · stdlib `sqlite3` · pytest + `httpx.MockTransport` · Preact + `@preact/signals`.

**Spec:** [`../specs/2026-05-29-sp-b-barcode-inventory-design.md`](../specs/2026-05-29-sp-b-barcode-inventory-design.md) · **Vision:** [`../specs/2026-05-28-kitchen-mesh-vision-design.md`](../specs/2026-05-28-kitchen-mesh-vision-design.md)

---

## Prerequisite (before Task 1)

- [ ] **Add `zxing-cpp` and install it into the test interpreter (system py 3.13).** The repo `.venv` is a uv-venv with no pytest — tests run under `/usr/bin/python3`. Add the dep to `pyproject.toml` `dependencies` (it'll reach the runtime `.venv` via `uv`), and install into system py3.13 for the test runner:

Run: `cd ~/pantryatlas && /usr/bin/python3 -m pip install --user 'zxing-cpp>=2.2'`
Then confirm import + inspect the installed API (the `write_barcode`/`read_barcodes` surface varies by version — Task 3 depends on what you see):
Run: `/usr/bin/python3 -c "import zxingcpp; print(zxingcpp.__version__); print([n for n in dir(zxingcpp) if not n.startswith('_')])"`
Expected: a version string + names including `read_barcodes` (and ideally `write_barcode`, `BarcodeFormat`).

> Canonical commands throughout: tests `PYTHONPATH=. /usr/bin/python3 -m pytest <target> -q`; lint `ruff check .`; build `cd web && npm run build`. Filter Pi gcov noise with `2>&1 | grep -v -E "profiling:|\.gcda:|Cannot open"` when running the `.venv` python (not needed for `/usr/bin/python3`).

## File structure

| File | Responsibility | Action |
|---|---|---|
| `pantryatlas/navigator/openfoodfacts.py` | `OpenFoodFactsClient` — OFF HTTP lookup (pure, no cache) | **Create** |
| `pantryatlas/navigator/barcode.py` | `decode_barcode` + `product_to_ingredient` | **Create** |
| `pantryatlas/store/kitchen.py` | add `off_cache` table + `cache_off`/`get_cached_off` | **Modify** |
| `pantryatlas/navigator/server.py` | extend `AddItemIn`+`post_pantry_item`; add `/pantry/barcode` route; wire OFF client on `app.state` | **Modify** |
| `pyproject.toml` | add `zxing-cpp` dependency | **Modify** |
| `tests/navigator/test_openfoodfacts.py` | OFF client tests (MockTransport) | **Create** |
| `tests/navigator/test_barcode.py` | decode + mapping tests | **Create** |
| `tests/navigator/test_barcode_routes.py` | route + extended-add tests | **Create** |
| `tests/navigator/test_kitchen_store.py` | off_cache round-trip test | **Modify** |
| `web/src/signals.ts` | `postBarcode(file)` + barcode candidate state | **Modify** |
| `web/src/components/BarcodeReviewSheet.tsx` | confirm sheet | **Create** |
| `web/src/pages/Navigator.tsx` | "Scan barcode" affordance + sheet wiring | **Modify** |
| `web/mock_backend.py` | serve `/pantry/barcode` (canned) for headless verify | **Modify** |
| `docs/navigator.md` | document the route + OFF + cache | **Modify** |

---

## Task 1: OpenFoodFactsClient

**Files:**
- Create: `pantryatlas/navigator/openfoodfacts.py`
- Test: `tests/navigator/test_openfoodfacts.py`

- [ ] **Step 1: Write the failing test**

```python
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
```

- [ ] **Step 2: Run it to verify it fails**

Run: `PYTHONPATH=. /usr/bin/python3 -m pytest tests/navigator/test_openfoodfacts.py -q`
Expected: FAIL — `ModuleNotFoundError: No module named 'pantryatlas.navigator.openfoodfacts'`

- [ ] **Step 3: Write the minimal implementation**

```python
# pantryatlas/navigator/openfoodfacts.py
"""Open Food Facts lookup client (pure HTTP, no caching).

OFF is a free, keyless public product database. This client does ONE thing:
GET a product by barcode. Caching lives in KitchenStore; routing decides
cache-first. ``transport`` is injectable for httpx.MockTransport tests.
"""

from __future__ import annotations

import httpx

_DEFAULT_BASE_URL = "https://world.openfoodfacts.org"
# OFF asks API users to send a descriptive UA; a generic Python UA is also
# bot-blocked by some CDNs (see project memory). Identify ourselves.
_USER_AGENT = "PantryAtlas/0.2 (+https://pantryatlas.org)"
_FIELDS = "product_name,brands,categories_tags,ingredients_tags"


class OffUnavailable(Exception):
    """Raised when OFF cannot be reached / returns a server error."""


class OpenFoodFactsClient:
    def __init__(self, base_url: str = _DEFAULT_BASE_URL, timeout_s: float = 6.0,
                 transport: httpx.BaseTransport | None = None) -> None:
        self._base_url = base_url.rstrip("/")
        self._client = httpx.Client(
            timeout=timeout_s,
            headers={"User-Agent": _USER_AGENT},
            transport=transport,
        )

    def get_product(self, code: str) -> dict | None:
        """Return the OFF product dict for a barcode, or None if not found.

        Raises OffUnavailable on network error / timeout / 5xx.
        """
        url = f"{self._base_url}/api/v2/product/{code}.json?fields={_FIELDS}"
        try:
            r = self._client.get(url)
        except httpx.HTTPError as exc:
            raise OffUnavailable(str(exc)) from exc
        if r.status_code == 404:
            return None
        if r.status_code >= 500:
            raise OffUnavailable(f"OFF returned {r.status_code}")
        if r.status_code != 200:
            raise OffUnavailable(f"OFF returned {r.status_code}")
        body = r.json()
        if body.get("status") != 1:
            return None
        return body.get("product")
```

- [ ] **Step 4: Run it to verify it passes**

Run: `PYTHONPATH=. /usr/bin/python3 -m pytest tests/navigator/test_openfoodfacts.py -q`
Expected: PASS (5 passed)

- [ ] **Step 5: Commit**

```bash
git add pantryatlas/navigator/openfoodfacts.py tests/navigator/test_openfoodfacts.py
git commit -m "feat(navigator): Open Food Facts lookup client"
```

---

## Task 2: KitchenStore off_cache

**Files:**
- Modify: `pantryatlas/store/kitchen.py`
- Test: `tests/navigator/test_kitchen_store.py`

- [ ] **Step 1: Write the failing test**

```python
# append to tests/navigator/test_kitchen_store.py
def test_off_cache_round_trip(tmp_path):
    store = KitchenStore(tmp_path / "kitchen.db")
    assert store.get_cached_off("123") is None
    store.cache_off("123", {"product_name": "Rice Noodles", "ingredients_tags": ["en:rice-noodles"]})
    cached = store.get_cached_off("123")
    assert cached["product_name"] == "Rice Noodles"
    # overwrite is idempotent (cache-through on re-fetch)
    store.cache_off("123", {"product_name": "Rice Noodles v2"})
    assert store.get_cached_off("123")["product_name"] == "Rice Noodles v2"
```

- [ ] **Step 2: Run it to verify it fails**

Run: `PYTHONPATH=. /usr/bin/python3 -m pytest tests/navigator/test_kitchen_store.py -k off_cache -q`
Expected: FAIL — `AttributeError: ... 'get_cached_off'`

- [ ] **Step 3: Write the minimal implementation**

In `pantryatlas/store/kitchen.py`, add a third table to the `_DDL` string (after `cook_events`):

```sql
CREATE TABLE IF NOT EXISTS off_cache (
    code         TEXT PRIMARY KEY,
    product_json TEXT NOT NULL,
    fetched_at   TEXT NOT NULL
);
```

Add two methods to `class KitchenStore` (cache write takes the lock; read is lock-free, mirroring the existing read/write split):

```python
    def cache_off(self, code: str, product: dict[str, Any]) -> None:
        with self._lock:
            self._conn.execute(
                "INSERT INTO off_cache (code, product_json, fetched_at) VALUES (?,?,?) "
                "ON CONFLICT(code) DO UPDATE SET product_json=excluded.product_json, "
                "fetched_at=excluded.fetched_at",
                (code, json.dumps(product), _now_iso()),
            )
            self._conn.commit()

    def get_cached_off(self, code: str) -> dict[str, Any] | None:
        row = self._conn.execute(
            "SELECT product_json FROM off_cache WHERE code=?", (code,)
        ).fetchone()
        return json.loads(row[0]) if row is not None else None
```

- [ ] **Step 4: Run it to verify it passes**

Run: `PYTHONPATH=. /usr/bin/python3 -m pytest tests/navigator/test_kitchen_store.py -q`
Expected: PASS (all, incl. the new off_cache test)

- [ ] **Step 5: Commit**

```bash
git add pantryatlas/store/kitchen.py tests/navigator/test_kitchen_store.py
git commit -m "feat(store): off_cache table for Open Food Facts responses"
```

---

## Task 3: barcode decode + product→ingredient mapping

**Files:**
- Create: `pantryatlas/navigator/barcode.py`
- Test: `tests/navigator/test_barcode.py`

> **First, confirm the zxing-cpp API** you saw in the Prerequisite. The test below uses `zxingcpp.write_barcode(...)` to ENCODE a barcode image and `zxingcpp.read_barcodes(...)` to decode it (fixture-free, robust). If the installed wheel does not expose `write_barcode`, instead commit a small PNG of a known barcode at `tests/fixtures/barcode-737628064502.png` and load it; keep the no-barcode-image case either way. Read `pantryatlas/navigator/vision.py:72` (`_preprocess`) for the PIL EXIF/convert idiom — but **do NOT downscale for barcodes** (resolution matters); only EXIF-orient + convert mode.

- [ ] **Step 1: Write the failing test**

```python
# tests/navigator/test_barcode.py
from __future__ import annotations

import io

import zxingcpp
from PIL import Image

from pantryatlas.navigator.barcode import decode_barcode, product_to_ingredient
from pantryatlas.pantry.models import Ingredient


def _barcode_png(value: str = "737628064502") -> bytes:
    # Encode an EAN/UPC barcode to a PNG (fixture-free round-trip).
    img = zxingcpp.write_barcode(zxingcpp.BarcodeFormat.EAN13, value)  # PIL Image or ndarray
    pil = img if isinstance(img, Image.Image) else Image.fromarray(img)
    buf = io.BytesIO()
    pil.convert("RGB").resize((pil.width * 4, pil.height * 4)).save(buf, format="PNG")
    return buf.getvalue()


def test_decode_reads_barcode():
    code = decode_barcode(_barcode_png("737628064502"))
    assert code is not None
    assert "737628064502" in code  # EAN-13 may add/strip a check digit prefix


def test_decode_returns_none_when_no_barcode():
    buf = io.BytesIO()
    Image.new("RGB", (200, 200), "white").save(buf, format="PNG")
    assert decode_barcode(buf.getvalue()) is None


# --- mapping ---
_KNOWN = {"noodles": "noodles", "rice noodles": "noodles", "pasta": "pasta"}


def _fake_resolver(raw: str) -> Ingredient | None:
    canonical = _KNOWN.get(raw.strip().lower())
    return Ingredient(canonical_name=canonical, raw_text=raw) if canonical else None


def test_mapping_uses_ingredient_tag_first():
    product = {"product_name": "Thai Kitchen Rice Noodles", "brands": "Thai Kitchen",
               "ingredients_tags": ["en:rice-noodles"], "categories_tags": ["en:pastas", "en:noodles"]}
    ing, matched = product_to_ingredient(product, _fake_resolver)
    assert matched is True
    assert ing.canonical_name == "noodles"   # "rice noodles" → resolver → "noodles"
    assert "Rice Noodles" in ing.raw_text


def test_mapping_falls_back_to_product_name_verbatim_when_unresolvable():
    product = {"product_name": "Exotic Snack 9000", "brands": "BrandX",
               "ingredients_tags": ["en:mystery"], "categories_tags": ["en:snacks"]}
    ing, matched = product_to_ingredient(product, _fake_resolver)
    assert matched is False
    assert ing.raw_text.startswith("Exotic Snack 9000")
    assert ing.canonical_name  # non-empty slug, never blank
```

- [ ] **Step 2: Run it to verify it fails**

Run: `PYTHONPATH=. /usr/bin/python3 -m pytest tests/navigator/test_barcode.py -q`
Expected: FAIL — `ModuleNotFoundError: No module named 'pantryatlas.navigator.barcode'`

- [ ] **Step 3: Write the minimal implementation**

```python
# pantryatlas/navigator/barcode.py
"""Host-side barcode decode + OFF-product → canonical-ingredient mapping."""

from __future__ import annotations

import io
import re
from collections.abc import Callable

from pantryatlas.pantry.models import Ingredient


def decode_barcode(image_bytes: bytes) -> str | None:
    """Decode the first barcode in an image, or None. Host-side (zxing-cpp)."""
    import zxingcpp
    from PIL import Image, ImageOps

    try:
        with Image.open(io.BytesIO(image_bytes)) as img:
            img = ImageOps.exif_transpose(img)
            if img.mode not in ("RGB", "L"):
                img = img.convert("RGB")
            results = zxingcpp.read_barcodes(img)
    except Exception:
        return None
    for r in results:
        text = getattr(r, "text", None)
        if text:
            return text
    return None


def _tag_to_text(tag: str) -> str:
    # "en:rice-noodles" -> "rice noodles"; "en:Rice Noodles" -> "rice noodles"
    body = tag.split(":", 1)[-1]
    return body.replace("-", " ").strip().lower()


def _slug(name: str) -> str:
    s = re.sub(r"[^a-z0-9]+", "-", name.strip().lower()).strip("-")
    return s or "unknown-product"


def product_to_ingredient(
    product: dict, resolver: Callable[[str], Ingredient | None]
) -> tuple[Ingredient, bool]:
    """Map an OFF product to a canonical pantry Ingredient.

    Tries ingredients_tags (most specific) then categories_tags then the product
    name through the resolver; falls back to a verbatim product-name Ingredient.
    Returns (ingredient, matched) where matched = the resolver succeeded.
    """
    name = (product.get("product_name") or "").strip()
    brand = (product.get("brands") or "").strip()
    raw_text = f"{name} ({brand})" if name and brand else (name or brand or "scanned item")

    # ingredients_tags first (most specific), then categories (most-specific last → reversed)
    candidates: list[str] = []
    candidates += [_tag_to_text(t) for t in (product.get("ingredients_tags") or [])]
    candidates += [_tag_to_text(t) for t in reversed(product.get("categories_tags") or [])]
    if name:
        candidates.append(name.lower())

    for cand in candidates:
        if not cand:
            continue
        resolved = resolver(cand)
        if resolved is not None:
            return (
                Ingredient(canonical_name=resolved.canonical_name, raw_text=raw_text),
                True,
            )

    # Final fallback: store verbatim (user can fix on the confirm sheet)
    return (Ingredient(canonical_name=_slug(name or raw_text), raw_text=raw_text), False)
```

- [ ] **Step 4: Run it to verify it passes**

Run: `PYTHONPATH=. /usr/bin/python3 -m pytest tests/navigator/test_barcode.py -q`
Expected: PASS (4 passed). If `write_barcode` is unavailable, switch the fixture per the note above and re-run.

- [ ] **Step 5: Commit**

```bash
git add pantryatlas/navigator/barcode.py tests/navigator/test_barcode.py
git commit -m "feat(navigator): host-side barcode decode + OFF→canonical mapping"
```

---

## Task 4: extend the add path (explicit canonical_name + source)

**Files:**
- Modify: `pantryatlas/navigator/server.py:93` (`AddItemIn`), `:382-392` (`post_pantry_item`)
- Test: `tests/navigator/test_barcode_routes.py`

- [ ] **Step 1: Write the failing test**

```python
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
```

- [ ] **Step 2: Run it to verify it fails**

Run: `PYTHONPATH=. /usr/bin/python3 -m pytest tests/navigator/test_barcode_routes.py -q`
Expected: FAIL — the explicit-canonical item is rejected (422) or stored with `source="manual"`.

- [ ] **Step 3: Write the minimal implementation**

Replace `AddItemIn` (server.py:93):

```python
class AddItemIn(BaseModel):
    """Body for POST /navigator/pantry/items."""

    raw_text: str
    canonical_name: str | None = None  # when set, skip the resolver (e.g. barcode confirm)
    source: str = "manual"             # provenance: manual | barcode | vision:<id>
```

Replace `post_pantry_item` (server.py:382-392):

```python
    @app.post("/navigator/pantry/items", status_code=201)
    def post_pantry_item(body: AddItemIn) -> dict[str, Any]:
        """Add one ingredient. With canonical_name set, store it directly (skip resolver)."""
        if body.canonical_name:
            ingredient = Ingredient(canonical_name=body.canonical_name, raw_text=body.raw_text)
        else:
            ingredient = app.state.resolver(body.raw_text)
            if ingredient is None:
                raise HTTPException(
                    status_code=422,
                    detail=f"Cannot resolve '{body.raw_text}' to a canonical ingredient.",
                )
        item = _get_kitchen(app).add_item(ingredient, source=body.source)
        return {"canonical_name": item["canonical_name"], "raw_text": item["raw_text"],
                "source": item["source"]}
```

- [ ] **Step 4: Run it to verify it passes**

Run: `PYTHONPATH=. /usr/bin/python3 -m pytest tests/navigator/test_barcode_routes.py -q`
Expected: PASS (2 passed)

- [ ] **Step 5: Commit**

```bash
git add pantryatlas/navigator/server.py tests/navigator/test_barcode_routes.py
git commit -m "feat(navigator): add path accepts explicit canonical_name + source"
```

---

## Task 5: POST /navigator/pantry/barcode route + OFF wiring

**Files:**
- Modify: `pantryatlas/navigator/server.py` (Pydantic-free route; wire `app.state.off_client`; production default in `_build_production_app`)
- Test: `tests/navigator/test_barcode_routes.py`

- [ ] **Step 1: Write the failing test**

```python
# append to tests/navigator/test_barcode_routes.py
import io as _io

import httpx
import zxingcpp
from PIL import Image

from pantryatlas.navigator.openfoodfacts import OpenFoodFactsClient


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
    buf = _io.BytesIO(); Image.new("RGB", (200, 200), "white").save(buf, format="PNG")
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
```

- [ ] **Step 2: Run it to verify it fails**

Run: `PYTHONPATH=. /usr/bin/python3 -m pytest tests/navigator/test_barcode_routes.py -k barcode_route -q`
Expected: FAIL — 404/405 (route not defined)

- [ ] **Step 3: Write the minimal implementation**

Add `app.state.off_client = None` in the `app.state` block (after `app.state.kitchen_factory = kitchen_factory`, ~server.py:315), and add an `off_client` param to `create_app`'s signature (`off_client: "OpenFoodFactsClient | None" = None`) plus the import at top: `from pantryatlas.navigator.openfoodfacts import OffUnavailable, OpenFoodFactsClient`.

Add the route after the vision route (it reuses the same `_MAX_UPLOAD_BYTES` + validation idiom):

```python
    @app.post("/navigator/pantry/barcode")
    async def post_pantry_barcode(
        image: UploadFile = File(..., description="Photo of a product barcode (JPEG/PNG, ≤8 MiB)"),  # noqa: B008
    ) -> dict[str, Any]:
        """Decode a barcode photo, look it up in OFF (cache-first), return a candidate.

        Read-only: does NOT add to the pantry. The client confirms, then POSTs to
        /navigator/pantry/items with {raw_text, canonical_name, source:"barcode"}.
        """
        from pantryatlas.navigator.barcode import decode_barcode, product_to_ingredient

        content_type = (image.content_type or "").lower()
        if content_type and content_type not in (
            "image/jpeg", "image/jpg", "image/png", "application/octet-stream",
        ):
            raise HTTPException(status_code=415, detail=f"Unsupported media type '{content_type}'.")
        raw_bytes = await image.read()
        if len(raw_bytes) > _MAX_UPLOAD_BYTES:
            raise HTTPException(status_code=413, detail="Image too large. Maximum is 8 MiB.")
        if not raw_bytes:
            raise HTTPException(status_code=400, detail="Empty image upload.")

        code = decode_barcode(raw_bytes)
        if code is None:
            raise HTTPException(status_code=422, detail="no barcode detected")

        kitchen = _get_kitchen(app)
        product = kitchen.get_cached_off(code)
        if product is None:
            off = app.state.off_client
            if off is None:
                return {"found": False, "code": code, "error": "off_unavailable"}
            try:
                product = off.get_product(code)
            except OffUnavailable:
                return {"found": False, "code": code, "error": "off_unavailable"}
            if product is not None:
                kitchen.cache_off(code, product)

        if product is None:
            return {"found": False, "code": code}

        ingredient, matched = product_to_ingredient(product, app.state.resolver)
        return {
            "found": True,
            "code": code,
            "product": {"name": product.get("product_name") or "", "brand": product.get("brands") or ""},
            "proposed": {"canonical_name": ingredient.canonical_name,
                         "raw_text": ingredient.raw_text, "matched": matched},
        }
```

In `_build_production_app` (server.py:736+), add a default client to the `create_app(...)` call:

```python
        off_client=OpenFoodFactsClient(),
```

- [ ] **Step 4: Run it to verify it passes**

Run: `PYTHONPATH=. /usr/bin/python3 -m pytest tests/navigator/ -q`
Expected: PASS — the whole navigator suite (the new barcode-route tests + everything pre-existing).

- [ ] **Step 5: Commit**

```bash
git add pantryatlas/navigator/server.py tests/navigator/test_barcode_routes.py
git commit -m "feat(navigator): POST /pantry/barcode — decode + cache-first OFF + candidate"
```

---

## Task 6: declare the dependency

**Files:**
- Modify: `pyproject.toml`

- [ ] **Step 1: Add the dependency**

Add `"zxing-cpp>=2.2"` to the `dependencies` array in `pyproject.toml` (alongside the existing runtime deps like `Pillow`/`python-multipart`). Keep array sorted/styled as the file already is.

- [ ] **Step 2: Verify a clean resolve + import**

Run: `cd ~/pantryatlas && /usr/bin/python3 -c "import zxingcpp, pantryatlas.navigator.barcode; print('ok')"`
Expected: `ok`
Run: `ruff check .`
Expected: clean (CI runs `ruff check .`).

- [ ] **Step 3: Commit**

```bash
git add pyproject.toml
git commit -m "build: declare zxing-cpp runtime dependency"
```

---

## Task 7: frontend data layer — postBarcode

**Files:**
- Modify: `web/src/signals.ts`

- [ ] **Step 1: Add the barcode candidate types + action** (after the cook/consume helpers added in SP-A):

```typescript
export interface BarcodeCandidate {
  found: boolean
  code: string
  product?: { name: string; brand: string }
  proposed?: { canonical_name: string; raw_text: string; matched: boolean }
  error?: string
}

export const barcodeSheetOpen = signal<boolean>(false)
export const barcodeCandidate = signal<BarcodeCandidate | null>(null)
export const barcodeState = signal<'idle' | 'scanning' | 'ready' | 'error'>('idle')

/** Upload a barcode photo; populate the candidate for the confirm sheet. */
export async function postBarcode(file: File) {
  barcodeState.value = 'scanning'
  barcodeCandidate.value = null
  barcodeSheetOpen.value = true
  try {
    const form = new FormData()
    form.append('image', file)
    const res = await fetch('/navigator/pantry/barcode', { method: 'POST', body: form })
    if (res.status === 422) { barcodeState.value = 'error'; return }
    if (!res.ok) { barcodeState.value = 'error'; return }
    barcodeCandidate.value = await res.json()
    barcodeState.value = 'ready'
  } catch {
    barcodeState.value = 'error'
  }
}

/** Confirm the (possibly user-edited) canonical and add with barcode provenance. */
export async function confirmBarcodeAdd(rawText: string, canonicalName: string) {
  try {
    const res = await fetch('/navigator/pantry/items', {
      method: 'POST', headers: { 'Content-Type': 'application/json' },
      body: JSON.stringify({ raw_text: rawText, canonical_name: canonicalName, source: 'barcode' }),
    })
    if (res.ok || res.status === 201) {
      barcodeSheetOpen.value = false
      barcodeCandidate.value = null
      barcodeState.value = 'idle'
      await fetchPantry()
    }
  } catch { /* keep sheet open on failure */ }
}
```

- [ ] **Step 2: Build**

Run: `cd ~/pantryatlas/web && npm run build`
Expected: clean (no TS errors).

- [ ] **Step 3: Commit**

```bash
cd ~/pantryatlas && git add web/src/signals.ts
git commit -m "feat(web): barcode scan data layer (postBarcode + confirm)"
```

---

## Task 8: BarcodeReviewSheet + scan affordance

**Files:**
- Create: `web/src/components/BarcodeReviewSheet.tsx`
- Modify: `web/src/pages/Navigator.tsx`

- [ ] **Step 1: Create the sheet** (mirrors PhotoReviewSheet's structure + token styling — read `web/src/components/PhotoReviewSheet.tsx` first for the modal/overlay idiom and match it):

```tsx
// web/src/components/BarcodeReviewSheet.tsx
import { h } from 'preact'
import { useState, useEffect } from 'preact/hooks'
import { barcodeSheetOpen, barcodeCandidate, barcodeState, confirmBarcodeAdd } from '../signals'

export function BarcodeReviewSheet() {
  if (!barcodeSheetOpen.value) return null
  const state = barcodeState.value
  const cand = barcodeCandidate.value
  const [canonical, setCanonical] = useState('')
  useEffect(() => {
    if (cand?.proposed) setCanonical(cand.proposed.canonical_name)
  }, [cand?.proposed?.canonical_name])

  const close = () => { barcodeSheetOpen.value = false }

  return (
    <div
      data-barcode-sheet="true"
      onClick={close}
      style={{
        position: 'fixed', inset: '0', background: 'rgba(0,0,0,0.4)',
        display: 'flex', alignItems: 'flex-end', justifyContent: 'center', zIndex: 50,
      }}
    >
      <div
        onClick={(e) => e.stopPropagation()}
        style={{
          background: 'var(--md-sys-color-surface)', width: '100%', maxWidth: '520px',
          borderTopLeftRadius: 'var(--md-sys-shape-corner-extra-large)',
          borderTopRightRadius: 'var(--md-sys-shape-corner-extra-large)',
          padding: '24px', fontFamily: 'var(--font)',
        }}
      >
        {state === 'scanning' && <p data-barcode-status="scanning">Reading barcode…</p>}
        {state === 'error' && (
          <p data-barcode-status="error">Couldn’t read a barcode. Try again, or add the item by typing it.</p>
        )}
        {state === 'ready' && cand && !cand.found && (
          <p data-barcode-status="notfound">
            Barcode {cand.code} isn’t in Open Food Facts{cand.error === 'off_unavailable' ? ' (offline)' : ''}.
            Add it by typing the item instead.
          </p>
        )}
        {state === 'ready' && cand && cand.found && cand.proposed && (
          <div data-barcode-status="found" style={{ display: 'flex', flexDirection: 'column', gap: '12px' }}>
            <p style={{ fontSize: 'var(--md-sys-typescale-title-medium-size)',
                        color: 'var(--md-sys-color-on-surface)' }}>
              {cand.product?.name}{cand.product?.brand ? ` · ${cand.product.brand}` : ''}
            </p>
            <label style={{ fontSize: 'var(--md-sys-typescale-label-medium-size)',
                            color: 'var(--md-sys-color-on-surface-variant)' }}>
              Store as (pantry ingredient):
              <input
                data-barcode-canonical
                value={canonical}
                onInput={(e) => setCanonical((e.target as HTMLInputElement).value)}
                style={{ display: 'block', width: '100%', marginTop: '6px', padding: '10px',
                         borderRadius: 'var(--md-sys-shape-corner-medium)',
                         border: '1px solid var(--md-sys-color-outline)',
                         fontFamily: 'var(--font)', fontSize: 'var(--md-sys-typescale-body-large-size)' }}
              />
            </label>
            {!cand.proposed.matched && (
              <span style={{ fontSize: 'var(--md-sys-typescale-label-small-size)',
                             color: 'var(--md-sys-color-on-surface-variant)' }}>
                We couldn’t auto-match this to a known ingredient — edit if needed.
              </span>
            )}
            <button
              data-barcode-add
              onClick={() => confirmBarcodeAdd(cand.product?.name || canonical, canonical)}
              disabled={!canonical.trim()}
              style={{ minHeight: '44px', borderRadius: 'var(--md-sys-shape-corner-full)',
                       background: 'var(--md-sys-color-primary)', color: 'var(--md-sys-color-on-primary)',
                       border: 'none', fontFamily: 'var(--font)',
                       fontSize: 'var(--md-sys-typescale-label-large-size)', cursor: 'pointer' }}
            >
              Add to pantry
            </button>
          </div>
        )}
      </div>
    </div>
  )
}
```

- [ ] **Step 2: Wire the scan affordance + sheet into `Navigator.tsx`** — add a hidden file input with `capture="environment"` whose `onChange` calls `postBarcode(file)`, a "Scan barcode" button that triggers it (next to the existing add-ingredient / photo controls), import and render `<BarcodeReviewSheet />` near the existing `<PhotoReviewSheet />`. Read the current add/photo control block first and match its markup + token styling. Import:

```typescript
import { postBarcode } from '../signals'
import { BarcodeReviewSheet } from '../components/BarcodeReviewSheet'
```

- [ ] **Step 3: Build**

Run: `cd ~/pantryatlas/web && npm run build`
Expected: clean.

- [ ] **Step 4: Commit**

```bash
cd ~/pantryatlas && git add web/src/components/BarcodeReviewSheet.tsx web/src/pages/Navigator.tsx
git commit -m "feat(web): barcode scan affordance + confirm sheet"
```

---

## Task 9: headless verify + docs + final gates

**Files:**
- Modify: `web/mock_backend.py`, `docs/navigator.md`, `web/verify_loop.mjs` (or a sibling `web/verify_barcode.mjs`)

- [ ] **Step 1: Extend `web/mock_backend.py`** to serve `POST /navigator/pantry/barcode` returning a canned candidate (no real decode/OFF — the mock just returns a fixed `{found:true, code, product, proposed}`), so the headless check can drive the sheet. Read the current `mock_backend.py` (KitchenStore-backed since SP-A) and add the route consistently.

- [ ] **Step 2: Add a headless check** (`web/verify_barcode.mjs`, modeled on `web/verify_loop.mjs`): build, serve via mock_backend, open in chromium, trigger `postBarcode` (call it via `page.evaluate` with a synthetic File, or click the scan input), confirm the `[data-barcode-sheet]` renders the candidate, edit `[data-barcode-canonical]`, click `[data-barcode-add]`, and assert via `GET /navigator/pantry` that an item with `source:"barcode"` landed. Print `BARCODE OK` / non-zero on failure. (If driving a real File through the input is too fiddly headlessly, call `window`-exposed `postBarcode` with a fetched fixture blob, or assert the sheet+add path against a candidate injected via `barcodeCandidate.value` — document what was exercised.)

- [ ] **Step 3: Document** in `docs/navigator.md`: the `POST /navigator/pantry/barcode` route (multipart image → `{found, code, product?, proposed?}`, read-only), the OFF dependency + `off_cache` table + cache-first/offline behavior, and the extended `POST /navigator/pantry/items` (`canonical_name?`, `source`). Note barcode is the highest-accuracy IN path (exact product + ingredient list) and the iOS-friendly host-decode design.

- [ ] **Step 4: Final gates**

Run: `cd ~/pantryatlas && PYTHONPATH=. /usr/bin/python3 -m pytest tests/navigator/ -q`
Expected: all pass.
Run: `ruff check .`
Expected: clean.
Run: `cd web && npm run build`
Expected: clean.
Run: `node web/verify_barcode.mjs`
Expected: `BARCODE OK`.

- [ ] **Step 5: Commit**

```bash
cd ~/pantryatlas && git add web/mock_backend.py web/verify_barcode.mjs docs/navigator.md
git commit -m "test(web): headless barcode verification + docs for SP-B route"
```

---

## Self-review (completed during planning)

- **Spec coverage:** OFF client (T1) · cache table (T2) · host decode + mapping (T3) · extended add path / confirm-then-add (T4) · read-only barcode route w/ cache-first + graceful OFF errors + 422 no-barcode (T5) · dep (T6) · scan UX confirm-sheet (T7, T8) · headless verify + docs (T9). Every spec section maps to a task. ✓
- **iOS path:** host-side decode from a file-capture upload — no `BarcodeDetector`; covered by T3/T5/T8. ✓
- **No placeholders:** complete code in every backend step; T8 sheet is complete, T9 + the two `Navigator.tsx` wiring steps point to exact insertion sites in existing markup the implementer reads. ✓
- **Type consistency:** `OpenFoodFactsClient.get_product` / `OffUnavailable`, `decode_barcode`, `product_to_ingredient(product, resolver)->(Ingredient,bool)`, `cache_off`/`get_cached_off`, `AddItemIn{raw_text,canonical_name?,source}`, the route's `{found,code,product,proposed{canonical_name,raw_text,matched}}` shape, and the frontend `BarcodeCandidate`/`postBarcode`/`confirmBarcodeAdd` all match across tasks. ✓
- **Env reality:** every test runs under `/usr/bin/python3` (3.13, has the deps); the Prerequisite installs `zxing-cpp` there and inspects its API so T3 picks the right encode/decode form; gates run the whole `tests/navigator/` suite + `ruff check .` (CI parity). ✓
- **zxing-cpp API risk:** flagged in the Prerequisite + T3 (verify `write_barcode`; committed-PNG fixture fallback). ✓
