# Design — SP-B (slice 1): Barcode → Open Food Facts → Pantry

- **Date:** 2026-05-29
- **Status:** Approved (brainstorming) — ready for implementation planning
- **Parent vision:** [`2026-05-28-kitchen-mesh-vision-design.md`](./2026-05-28-kitchen-mesh-vision-design.md) (SP-B = "Barcode + photo inventory")
- **Builds on:** SP-A (`KitchenStore`, `add_item`, the lazy `_get_kitchen` wiring) — merged to `main` (`b6efcb0`).
- **Scope:** The barcode half of SP-B only. The shelf-photo → host-Gemma-vision half is **deferred** (it inherits the unrun host-vision bootstrap, PR #3) and is a separate slice.

## Goal

Let a user scan a packaged product's barcode (by photographing it on any phone, iOS included) and get the **exact** product + ingredient list from Open Food Facts, mapped to a canonical pantry ingredient — the highest-accuracy, lowest-friction inventory-IN path, and the one no vision model can match for packaged goods.

## Why this is buildable + verifiable on the Pi today

- **Decode runs on the host** from an uploaded image (`zxing-cpp`, a pure pip wheel — verified installable; `libzbar.so.0` is also present as a fallback). This reuses SP-A's `<input type="file" capture="environment">` path, so it **works on the operator's iPhone** (no `BarcodeDetector` API, which Safari lacks).
- **Open Food Facts** is a free, keyless public API, verified reachable from this Pi; it's the **only** network call and is fully mockable in tests via `httpx.MockTransport` (the existing `GemmaClient` test pattern). Responses are cached locally so repeat scans + offline work.
- No Gemma / mmproj dependency. Tests run under `PYTHONPATH=. /usr/bin/python3` (3.13).

## Decisions locked (brainstorming)

| Decision | Choice |
|---|---|
| Decode location | **Host-side**, from an uploaded photo (iOS-friendly; reuses file-capture) |
| Decoder | **`zxing-cpp`** (pure wheel, no system dep) |
| Product → pantry mapping | OFF `categories_tags`/`ingredients_tags` (`en:rice-noodles`→"rice noodles") → **existing resolver** → canonical; fall back to `product_name`; final fallback = store product name verbatim |
| Scan UX | **Confirm sheet, then add** (user can correct the canonical mapping before it lands) |
| Provenance | `source="barcode"` on the pantry item |
| Caching | OFF responses cached in `kitchen.db` (`off_cache` table) → repeat + offline |
| Out of scope | shelf-photo vision (deferred), live OFF write-back, nutrition, multi-scan batch |

## Data flow

```
phone photographs barcode (existing file-capture)
  → POST /navigator/pantry/barcode  (multipart image)
      → decode_barcode(image)            [zxing-cpp + PIL]   ── None → 422 "no barcode detected"
      → OpenFoodFactsClient.get_product(code)  (cache-first) ── not found → return {code, found:false} (offer manual add)
      → product_to_ingredient(product, resolver) → candidate
      ← 200 {code, found:true, product:{name,brand}, proposed:{canonical_name, raw_text, matched:bool}}
  → confirm sheet (editable canonical) → user taps Add
  → POST /navigator/pantry/items {raw_text, canonical_name, source:"barcode"}  → KitchenStore.add_item
```

The barcode route is **read-only** (no pantry write); the write happens on confirm through the existing add path.

## Components (small, focused units)

- **`pantryatlas/navigator/openfoodfacts.py`** — `OpenFoodFactsClient(base_url="https://world.openfoodfacts.org", timeout_s=..., transport=None)`. `get_product(code) -> dict | None`: GET `/api/v2/product/{code}.json?fields=product_name,brands,categories_tags,ingredients_tags`; a descriptive non-bot User-Agent (OFF asks for one; and per project memory a generic `Python-urllib` UA gets bot-blocked by some CDNs); returns the `product` dict on `status==1`, `None` on `status==0`/404; raises a typed `OffUnavailable` on network/timeout/5xx. `transport` injectable for `httpx.MockTransport` tests.
- **`pantryatlas/navigator/barcode.py`**
  - `decode_barcode(image_bytes: bytes) -> str | None` — PIL open + EXIF-orient + downscale (reuse `vision._preprocess`-style), `zxing_cpp.read_barcodes`; return the first decoded value's text, or `None`.
  - `product_to_ingredient(product: dict, resolver) -> tuple[Ingredient, bool]` — build candidate canonical-source strings from `ingredients_tags` + `categories_tags` (strip `en:` / lang prefix, `-`→space), try `resolver` on each most-specific-first; else `resolver(product_name)`; else `Ingredient(canonical_name=slug(product_name), raw_text=product_name)`. Returns `(ingredient, matched)` where `matched` = resolver succeeded. `raw_text` = product name (+ brand).
- **`KitchenStore`** — add an `off_cache` table (`code TEXT PRIMARY KEY, product_json TEXT, fetched_at TEXT`) + `cache_off(code, product)` / `get_cached_off(code)`. The client checks the cache first and writes through on a successful fetch.
- **`pantryatlas/navigator/server.py`**
  - New `POST /navigator/pantry/barcode` (`UploadFile`, ≤8 MiB, JPEG/PNG — mirror the vision route's validation) → decode → OFF (cache-first) → map → return the candidate. 422 no-barcode; 200 `{found:false, code}` when OFF has no product; `OffUnavailable` → 200 `{found:false, code, error:"off_unavailable"}` so the UI can offer manual add.
  - Extend `AddItemIn` → `{raw_text, canonical_name: str | None = None, source: str = "manual"}`. In `post_pantry_item`: if `canonical_name` is provided, build the `Ingredient` directly (skip the resolver) and pass `source` to `add_item`; else current behavior. Wire `OpenFoodFactsClient` onto `app.state` (lazy, like the others) + a default in `_build_production_app`.
- **Frontend (`web/`)** — a "Scan barcode" affordance (second file-capture input, `capture="environment"`) → `postBarcode(file)` in `signals.ts` → a `BarcodeReviewSheet.tsx` (mirrors `PhotoReviewSheet`): shows product name/brand + an editable canonical field + matched/unmatched hint → "Add to pantry" calls the extended add path with `source:"barcode"`; handles `found:false` (offer manual add) and `off_unavailable`.

## Error handling

- No barcode in image → **422** `{detail:"no barcode detected"}`; sheet says "couldn't read a barcode — try again or add manually."
- OFF product-not-found (`status==0`/404) → **200** `{found:false, code}`; sheet offers manual add (prefilled with nothing — user types the item).
- OFF network/timeout/5xx → cache-first means a previously-scanned code still resolves offline; otherwise **200** `{found:false, code, error:"off_unavailable"}` → graceful manual-add path. Never a 500.
- Upload validation mirrors the vision route (content-type, ≤8 MiB, non-empty).

## Testing strategy

- **Unit (system py3.13):** `decode_barcode` on a **committed fixture barcode image** (a generated PNG of a known EAN/UPC; assert the decoded digits) + a no-barcode image → `None`; `product_to_ingredient` mapping cases (tag→canonical via a fake resolver; product-name fallback; verbatim fallback; `matched` flag); `OpenFoodFactsClient.get_product` via `httpx.MockTransport` (found / status-0 / 404 / timeout→`OffUnavailable`); `off_cache` round-trip + cache-first behavior in `KitchenStore`.
- **Route tests:** `POST /navigator/pantry/barcode` with a fixture image + mocked OFF (found → candidate; not-found → `found:false`; no-barcode → 422; OFF-down → graceful); extended `POST /navigator/pantry/items` with explicit `canonical_name`+`source` → item stored with `source="barcode"`. Use the duck-typed fake store from `test_loop_routes.py`.
- **Frontend:** `npm run build` clean; extend `web/verify_loop.mjs` or a sibling headless check to confirm the barcode sheet renders the candidate and "Add" lands an item with the barcode source (mock_backend serves the new route against its `KitchenStore`).
- Gates: full `tests/navigator/` green, `ruff check .` clean, `npm run build` clean. Verify a fresh dependency resolve (zxing-cpp added to `pyproject`).

## Open questions (resolve in planning)

- **Fixture barcode image:** generate at test-time (a tiny EAN-13 renderer) vs. commit a small PNG. Lean: commit a small PNG fixture (deterministic, no extra dep) of a known code, plus a real `zxing-cpp` round-trip test that also *encodes* if `zxing-cpp` supports write (it does) — encode→decode is the most robust, fixture-free option. Prefer encode→decode if the installed wheel exposes `write_barcode`.
- **Resolver reach:** the default vocab may not contain "rice noodles"; confirm the fallback chain (ingredients_tags → categories_tags → product_name → verbatim) degrades sensibly and the confirm sheet always lets the user fix it.
- **OFF UA / rate:** set a descriptive UA (`PantryAtlas/0.x (+pantryatlas.org)`); single per-scan request, cached — well within OFF's norms.
