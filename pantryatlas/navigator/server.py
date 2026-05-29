"""T-004: FastAPI navigator endpoint.

FastAPI navigator for the PantryAtlas submodule (pantry-in → ranked-recipes-out).

Route groups
------------
- Health:           GET  /navigator/health
- Pantry CRUD:      GET/PUT /navigator/pantry; POST/DELETE pantry/items;
                    POST pantry/items/{name}/consume; POST pantry/items/{name}/restore;
                    POST pantry/resolve
- Recipe ranking:   POST /navigator/recipes/from-pantry (instant, no embedding);
                    POST /navigator/recipes/from-pantry/refine (settled, with embedding);
                    POST /navigator/recipes/swaps (per-recipe swap suggestions)
- Cook loop:        POST /navigator/cook; GET /navigator/meals; GET /navigator/waste
- Vision:           POST /navigator/vision/parse-shelf (optional; 503 when unavailable)
- Inference:        GET/POST/DELETE /navigator/providers
- Static:           GET / → web/dist/index.html; /assets/* → web/dist/assets

Persistence
-----------
Mutable user state (pantry items, inventory-event ledger, cook log) is persisted
to ``~/.pantryatlas/kitchen.db`` via ``KitchenStore`` (plain SQLite, no
sqlite-vec extension required).  The static recipe corpus lives in a separate
``~/.pantryatlas/recipes.db``.

Design decisions
----------------
- ``create_app()`` factory keeps ONNX model + real DB out of the test process.
- Pre-filter for /recipes/from-pantry uses text-overlap against
  recipes_meta.ingredients_json — no embedding at pre-filter time.
  Candidates are then scored by rank_recipes() with the injected embed_fn.
- No CORSMiddleware is added: the same-origin PWA needs no permissive CORS
  and its absence guarantees no Access-Control-Allow-Origin: * header.
- Static mount is guarded: StaticFiles is only mounted when web/dist/assets
  exists so the import never fails when the frontend isn't built yet.
- The module-level ``app`` is side-effect-free at import time: no DB is opened,
  no directory is created.  The real RecipeStore and KitchenStore are opened
  lazily on first use via ``app.state.store_factory`` / ``app.state.kitchen_factory``
  (set by ``_build_production_app``).
"""

from __future__ import annotations

import logging
import os
from collections.abc import Callable
from datetime import date
from pathlib import Path
from typing import TYPE_CHECKING, Any

import numpy as np
from fastapi import FastAPI, File, Header, HTTPException, UploadFile
from fastapi.responses import FileResponse, JSONResponse
from fastapi.staticfiles import StaticFiles
from pydantic import BaseModel

from pantryatlas.flavor import FlavorStore
from pantryatlas.inference.config import save_provider_config
from pantryatlas.inference.providers.lan_endpoint import LanEndpointProvider
from pantryatlas.inference.registry import ProviderRegistry
from pantryatlas.navigator.openfoodfacts import OffUnavailable, OpenFoodFactsClient
from pantryatlas.navigator.ranking import RankedRecipe, compute_swaps, rank_recipes
from pantryatlas.pantry.models import Ingredient, Quantity
from pantryatlas.store.kitchen import KitchenStore
from pantryatlas.store.recipes import RecipeStore

_server_log = logging.getLogger(__name__)

if TYPE_CHECKING:
    from pantryatlas.gemma.client import GemmaClient

# Recipe corpus attribution. RecipeNLG is distributed CC-BY-NC-4.0, so every
# recipe surfaced by the API carries this so downstream consumers (and the
# PWA) can honour the licence without hardcoding it client-side.
RECIPE_SOURCE_ATTRIBUTION = "RecipeNLG (CC-BY-NC-4.0)"

_DEVICE_ROLES = ("compute", "sensor")

# ---------------------------------------------------------------------------
# Pydantic wire models
# ---------------------------------------------------------------------------


class QuantityIn(BaseModel):
    """Wire representation of a quantity (amount + unit)."""

    amount: float
    unit: str = ""


class IngredientIn(BaseModel):
    """Wire representation of a single pantry ingredient."""

    canonical_name: str
    raw_text: str
    quantity: QuantityIn | None = None
    expires_at: date | None = None


class AddItemIn(BaseModel):
    """Body for POST /navigator/pantry/items."""

    raw_text: str
    canonical_name: str | None = None  # when set, skip the resolver (e.g. barcode confirm)
    source: str = "manual"             # provenance: manual | barcode | vision:<id>


class ResolveIn(BaseModel):
    """Body for POST /navigator/pantry/resolve."""

    raw: str


class RecipeIn(BaseModel):
    """A recipe the client already holds (from the instant from-pantry paint).

    Sent back to /recipes/from-pantry/refine so the server can compute the real
    substitution penalty without re-querying the store.
    """

    title: str = ""
    ingredients: list[str] = []
    instructions: list[str] = []


class SwapsIn(BaseModel):
    """Body for POST /navigator/recipes/swaps — one recipe's ingredient list."""

    ingredients: list[str]


class ProviderIn(BaseModel):
    """Body for POST /navigator/providers — add a LAN provider."""

    name: str
    base_url: str
    multimodal: bool = False


class ConsumeIn(BaseModel):
    """Body for POST /navigator/pantry/items/{name}/consume."""

    coarse_amount: str = "used_up"  # half | used_up | discarded


class ExpiryIn(BaseModel):
    """Body for PUT /navigator/pantry/items/{name}/expiry."""

    expires_at: date | None = None  # null clears the date


class ConsumedItemIn(BaseModel):
    canonical_name: str
    coarse_amount: str = "cook"


class CookIn(BaseModel):
    """Body for POST /navigator/cook."""

    dish_name: str
    recipe_id: str | None = None
    servings: float | None = None
    rating: int | None = None
    notes: str | None = None
    consumed: list[ConsumedItemIn] | None = None


class DeviceEnrollIn(BaseModel):
    """Body for POST /navigator/devices/enroll."""

    name: str
    role: str  # compute | sensor
    kind: str | None = None
    caps: list[str] | None = None


# ---------------------------------------------------------------------------
# Lazy store accessor
# ---------------------------------------------------------------------------


def _get_store(app: FastAPI) -> RecipeStore:
    """Return the app's RecipeStore, initialising it lazily if needed.

    Routes should call this instead of reading ``app.state.store`` directly.
    Tests that inject an eager store via ``create_app(store=...)`` hit the fast
    path (``app.state.store`` is already set).  The production module-level app
    defers opening the real DB until the first request that needs the store.
    """
    store: RecipeStore | None = getattr(app.state, "store", None)
    if store is None:
        factory: Callable[[], RecipeStore] | None = getattr(
            app.state, "store_factory", None
        )
        if factory is None:
            raise RuntimeError("No RecipeStore and no store_factory configured on app.state")
        app.state.store = factory()
        store = app.state.store
    return store


def _get_kitchen(app: FastAPI) -> KitchenStore:
    """Return the app's KitchenStore, initialising it lazily via factory if needed."""
    kitchen: KitchenStore | None = getattr(app.state, "kitchen", None)
    if kitchen is None:
        factory: Callable[[], KitchenStore] | None = getattr(app.state, "kitchen_factory", None)
        if factory is None:
            raise RuntimeError("No KitchenStore and no kitchen_factory configured on app.state")
        app.state.kitchen = factory()
        kitchen = app.state.kitchen
    return kitchen


def _get_flavor(app: FastAPI) -> FlavorStore:
    """Return the app's FlavorStore, building it lazily via factory if needed."""
    flavor: FlavorStore | None = getattr(app.state, "flavor", None)
    if flavor is None:
        factory: Callable[[], FlavorStore] | None = getattr(app.state, "flavor_factory", None)
        if factory is None:
            raise RuntimeError("No FlavorStore and no flavor_factory configured on app.state")
        app.state.flavor = factory()
        flavor = app.state.flavor
    return flavor


# ---------------------------------------------------------------------------
# App factory
# ---------------------------------------------------------------------------


def create_app(
    *,
    store: RecipeStore | None = None,
    store_factory: Callable[[], RecipeStore] | None = None,
    resolver: Callable[[str], Ingredient | None],
    embed_fn: Callable[[list[str]], np.ndarray],
    pantry_path: Path,
    web_dist: Path | None = None,
    vision_client: GemmaClient | None = None,
    provider_registry: ProviderRegistry | None = None,
    providers_config_path: Path | None = None,
    kitchen: KitchenStore | None = None,
    kitchen_factory: Callable[[], KitchenStore] | None = None,
    off_client: OpenFoodFactsClient | None = None,
    flavor: FlavorStore | None = None,
    flavor_factory: Callable[[], FlavorStore] | None = None,
) -> FastAPI:
    """Build and return a FastAPI app wired to the given dependencies.

    Args:
        store: Eager RecipeStore instance (real or in-memory test instance).
            Mutually exclusive with ``store_factory``; tests use this path.
        store_factory: Zero-argument callable that returns a RecipeStore.
            Called lazily on first use.  Production wiring uses this so that
            importing the module does not open the real DB.
        resolver: Callable mapping raw text → Optional[Ingredient].
            Must NOT trigger ONNX model loading in tests; pass a fake.
        embed_fn: Callable mapping list[str] → np.ndarray (N, D).
            Must NOT trigger ONNX model loading in tests; pass a fake.
        pantry_path: Stored on ``app.state.pantry_path`` for calling-code API
            stability only — no route or factory reads it.  Mutable user state
            (pantry items, cook log, devices) is persisted to ``kitchen.db`` via
            ``KitchenStore``; the production kitchen factory captures the
            pantry.json migration path directly at construction time, not via
            this state value.
        web_dist: Path to the built PWA dist directory.
            When None, defaults to ``<repo>/web/dist`` if it exists; otherwise
            the static mount is skipped gracefully.
        vision_client: Optional ``GemmaClient`` with vision capability loaded
            (mmproj required).  When None (the default), POST /navigator/vision/parse-shelf
            returns HTTP 503 ``{"error":"vision_unavailable"}`` — the graceful fallback
            path the frontend already handles.

    Returns:
        Configured FastAPI application.
    """
    if store is not None and store_factory is not None:
        raise ValueError("Provide either store or store_factory, not both.")
    if store is None and store_factory is None:
        raise ValueError("One of store or store_factory is required.")

    from contextlib import asynccontextmanager

    @asynccontextmanager
    async def _lifespan(application: FastAPI):  # noqa: RUF029
        # Startup: warm the FlavorStore once (pandas + parquet ~9s) so the first
        # from-pantry request isn't stalled. Best-effort — never block boot.
        if (
            getattr(application.state, "flavor", None) is not None
            or getattr(application.state, "flavor_factory", None) is not None
        ):
            try:
                _get_flavor(application)
            except Exception:
                _server_log.warning("FlavorStore warm-up failed; will load lazily", exc_info=True)
        yield
        # Shutdown: close the OFF HTTP connection pool to avoid resource leaks.
        client = getattr(application.state, "off_client", None)
        if client is not None and hasattr(client, "close"):
            client.close()

    app = FastAPI(
        title="PantryAtlas Navigator",
        description="Pantry-in → ranked-recipes-out API",
        version="0.2.0",
        lifespan=_lifespan,
    )

    # Store dependencies on app.state so route handlers can access them.
    app.state.store = store  # None when using factory; _get_store() fills lazily
    app.state.store_factory = store_factory
    app.state.resolver = resolver
    app.state.embed_fn = embed_fn
    app.state.pantry_path = pantry_path
    # vision_client is None by default → 503 until operator loads mmproj
    app.state.vision_client = vision_client
    app.state.provider_registry = provider_registry
    app.state.providers_config_path = providers_config_path
    app.state.kitchen = kitchen
    app.state.kitchen_factory = kitchen_factory
    app.state.off_client = off_client
    app.state.flavor = flavor
    # Default factory: load the bundled parquet lazily on first use.
    if flavor is None and flavor_factory is None:
        _parquet = Path(__file__).resolve().parent.parent / "data" / "compounds.parquet"
        flavor_factory = lambda: FlavorStore(_parquet)  # noqa: E731
    app.state.flavor_factory = flavor_factory

    # ------------------------------------------------------------------
    # Static PWA serving (guarded — tolerates missing web/dist)
    # ------------------------------------------------------------------

    if web_dist is None:
        # Default: resolve relative to this file's repo root
        _here = Path(__file__).parent.parent.parent
        web_dist = _here / "web" / "dist"

    _assets_dir = web_dist / "assets"

    if _assets_dir.exists():
        app.mount("/assets", StaticFiles(directory=str(_assets_dir)), name="assets")

    @app.get("/", include_in_schema=False)
    def serve_root() -> Any:
        """Serve the PWA index.html or a JSON placeholder when not built."""
        index = web_dist / "index.html"
        if index.exists():
            return FileResponse(str(index))
        return JSONResponse({"app": "PantryAtlas Navigator", "status": "frontend not built"})

    # ------------------------------------------------------------------
    # Health
    # ------------------------------------------------------------------

    @app.get("/navigator/health")
    def health() -> dict[str, Any]:
        """Return service health and recipe count from the store."""
        return {
            "status": "ok",
            "recipe_count": _get_store(app).count(),
        }

    # ------------------------------------------------------------------
    # Pantry — read
    # ------------------------------------------------------------------

    @app.get("/navigator/pantry")
    def get_pantry() -> list[dict[str, Any]]:
        """Return the current pantry as a list of ingredient objects."""
        return _get_kitchen(app).list_items()

    # ------------------------------------------------------------------
    # Pantry — replace
    # ------------------------------------------------------------------

    @app.put("/navigator/pantry")
    def put_pantry(items: list[IngredientIn]) -> list[dict[str, Any]]:
        """Replace the whole pantry with the provided list (Pydantic-validated)."""
        ingredients = [
            Ingredient(
                canonical_name=it.canonical_name, raw_text=it.raw_text,
                quantity=Quantity(amount=it.quantity.amount, unit=it.quantity.unit)
                if it.quantity is not None else None,
                expires_at=it.expires_at,
            )
            for it in items
        ]
        return _get_kitchen(app).replace_all(ingredients)

    # ------------------------------------------------------------------
    # Pantry — add one item
    # ------------------------------------------------------------------

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

    # ------------------------------------------------------------------
    # Pantry — remove one item
    # ------------------------------------------------------------------

    @app.delete("/navigator/pantry/items/{name}")
    def delete_pantry_item(name: str) -> dict[str, str]:
        """Remove an ingredient by canonical name (no-op if not present)."""
        _get_kitchen(app).remove_item(name)
        return {"removed": name}

    # ------------------------------------------------------------------
    # Pantry — coarse consume / restore
    # ------------------------------------------------------------------

    @app.post("/navigator/pantry/items/{name}/consume")
    def consume_pantry_item(name: str, body: ConsumeIn) -> dict[str, Any]:
        item = _get_kitchen(app).consume_item(name, body.coarse_amount)
        if item is None:
            raise HTTPException(status_code=404, detail=f"No pantry item '{name}'.")
        return item

    @app.post("/navigator/pantry/items/{name}/restore")
    def restore_pantry_item(name: str) -> dict[str, Any]:
        item = _get_kitchen(app).restore_item(name)
        if item is None:
            raise HTTPException(status_code=404, detail=f"No pantry item '{name}'.")
        return item

    @app.put("/navigator/pantry/items/{name}/expiry")
    def put_pantry_item_expiry(name: str, body: ExpiryIn) -> dict[str, Any]:
        item = _get_kitchen(app).set_expiry(name, body.expires_at)
        if item is None:
            raise HTTPException(status_code=404, detail=f"No pantry item '{name}'.")
        return item

    @app.post("/navigator/pantry/items/{name}/expire")
    def post_pantry_item_expire(name: str) -> dict[str, Any]:
        item = _get_kitchen(app).mark_expired(name)
        if item is None:
            raise HTTPException(status_code=404, detail=f"No pantry item '{name}'.")
        return item

    # ------------------------------------------------------------------
    # Cook events
    # ------------------------------------------------------------------

    @app.post("/navigator/cook", status_code=201)
    def post_cook(body: CookIn) -> dict[str, Any]:
        kitchen = _get_kitchen(app)
        consumed = [{"canonical_name": c.canonical_name, "coarse_amount": c.coarse_amount}
                    for c in (body.consumed or [])]
        if not consumed and body.recipe_id is not None:
            recipe = _get_store(app).get(body.recipe_id)
            if recipe is not None and recipe.ingredients_json:
                for ing in recipe.ingredients_json:
                    resolved = app.state.resolver(ing)
                    name = resolved.canonical_name if resolved is not None else ing
                    consumed.append({"canonical_name": name, "coarse_amount": "cook"})
        return kitchen.add_cook_event(
            dish_name=body.dish_name, recipe_id=body.recipe_id, servings=body.servings,
            rating=body.rating, notes=body.notes, consumed=consumed,
        )

    @app.get("/navigator/meals")
    def get_meals(limit: int = 50) -> list[dict[str, Any]]:
        return _get_kitchen(app).list_meals(limit=limit)

    @app.get("/navigator/waste")
    def get_waste(window_days: int = 30) -> dict[str, Any]:
        return _get_kitchen(app).waste_tally(window_days=window_days)

    # ------------------------------------------------------------------
    # Pantry — resolve without persisting
    # ------------------------------------------------------------------

    @app.post("/navigator/pantry/resolve")
    def post_pantry_resolve(body: ResolveIn) -> dict[str, str]:
        """Resolve raw text to canonical_name WITHOUT modifying the pantry.

        Useful for live UI feedback (debounced resolution as the user types).
        """
        ingredient = app.state.resolver(body.raw)
        if ingredient is None:
            raise HTTPException(
                status_code=404,
                detail=f"Cannot resolve '{body.raw}' to a canonical ingredient.",
            )
        return {"canonical_name": ingredient.canonical_name}

    # ------------------------------------------------------------------
    # Recipes — rank from pantry
    # ------------------------------------------------------------------

    @app.post("/navigator/recipes/from-pantry")
    def post_recipes_from_pantry(cuisine: str | None = None) -> list[dict[str, Any]]:
        """Instant pantry → recipes: coverage-ranked, NO embedding (fast mode).

        Pre-filter strategy: text-overlap against recipes_meta.ingredients_json.
        Any recipe whose ingredients list shares at least one canonical name with
        the current pantry is a candidate.  Ranking runs in **fast mode**
        (coverage + expiration + cultural fit only, ``substitution_penalty=0``),
        so this returns well under the embedding budget even for tens of
        thousands of candidates.  The client then calls
        ``/recipes/from-pantry/refine`` to settle the ordering with real
        substitution scores.
        """
        pantry = _get_kitchen(app).on_hand()
        canonical_names = [ing.canonical_name for ing in pantry]

        candidates = _get_store(app).iter_overlapping(canonical_names)

        if not candidates:
            # Fall back: return empty list rather than 500
            return []

        flavor_store = _get_flavor(app)
        ranked: list[RankedRecipe] = rank_recipes(
            pantry,
            candidates,
            cuisine=cuisine,
            compute_substitution=False,
            flavor_fn=flavor_store.flavor_score,
        )

        return [_ranked_to_dict(r) for r in ranked]

    @app.post("/navigator/recipes/from-pantry/refine")
    def post_recipes_refine(
        recipes: list[RecipeIn], cuisine: str | None = None
    ) -> list[dict[str, Any]]:
        """Refine the instant results with real (embedding-based) substitution.

        The client sends back the top-N recipes it already painted; the server
        recomputes their substitution penalty against the *current* pantry and
        returns them re-ranked.  Because fast mode was optimistic
        (``substitution_penalty=0``), refining can only lower scores, so cards
        converge downward — a stable settle animation.

        Only the unique missing ingredients across the ≤N supplied recipes are
        embedded, in a single batch.
        """
        pantry = _get_kitchen(app).on_hand()
        candidates = [
            {"title": r.title, "ingredients": r.ingredients, "instructions": r.instructions}
            for r in recipes
        ]
        if not candidates:
            return []

        ranked = rank_recipes(
            pantry,
            candidates,
            app.state.embed_fn,
            k=len(candidates),
            cuisine=cuisine,
            compute_substitution=True,
            flavor_fn=_get_flavor(app).flavor_score,
        )
        return [_ranked_to_dict(r) for r in ranked]

    @app.post("/navigator/recipes/swaps")
    def post_recipes_swaps(body: SwapsIn) -> dict[str, Any]:
        """Suggest pantry swaps for one recipe's missing ingredients.

        Fired when the user expands a recipe card.  Embeds only that recipe's
        missing ingredients (typically 2-5) against the current pantry, so it is
        fast.  Returns ``{"swaps":[{missing,best_swap,similarity,reason}, ...]}``;
        ``best_swap`` is ``None`` when no pantry item clears the similarity floor.
        """
        pantry = _get_kitchen(app).on_hand()
        swaps = compute_swaps(body.ingredients, pantry, app.state.embed_fn)
        return {"swaps": swaps}

    # ------------------------------------------------------------------
    # Vision — shelf photo parsing
    # ------------------------------------------------------------------

    _MAX_UPLOAD_BYTES = 8 * 1024 * 1024  # 8 MiB

    @app.post("/navigator/vision/parse-shelf")
    async def post_vision_parse_shelf(
        image: UploadFile = File(..., description="Shelf photo (JPEG or PNG, ≤8 MiB)"),  # noqa: B008
    ) -> dict[str, Any]:
        """Parse a shelf photo and return detected ingredients.

        Accepts a multipart ``image`` field (JPEG or PNG, ≤8 MiB).
        Returns ``{"detected":[{"label":str,"confidence":float}],
                   "items":[str,...]}``
        on success.

        Returns HTTP 503 ``{"error":"vision_unavailable"}`` when the vision
        model/mmproj is not loaded — the frontend handles this gracefully.
        """
        from pantryatlas.navigator.vision import VisionUnavailable, parse_shelf

        registry = app.state.provider_registry
        client = app.state.vision_client  # backward-compat fallback
        backend = registry if registry is not None else client
        if backend is None:
            return JSONResponse(
                status_code=503,
                content={"error": "vision_unavailable"},
            )

        # Content-type check (permissive — allow unset/octet-stream from some clients)
        content_type = (image.content_type or "").lower()
        if content_type and content_type not in (
            "image/jpeg",
            "image/jpg",
            "image/png",
            "application/octet-stream",
        ):
            raise HTTPException(
                status_code=415,
                detail=f"Unsupported media type '{content_type}'. Use JPEG or PNG.",
            )

        raw_bytes = await image.read()
        if len(raw_bytes) > _MAX_UPLOAD_BYTES:
            raise HTTPException(
                status_code=413,
                detail=f"Image too large ({len(raw_bytes)} bytes). Maximum is 8 MiB.",
            )
        if not raw_bytes:
            raise HTTPException(status_code=400, detail="Empty image upload.")

        try:
            detected = parse_shelf(raw_bytes, backend)
        except VisionUnavailable:
            return JSONResponse(
                status_code=503,
                content={"error": "vision_unavailable"},
            )

        # Return both shapes:
        # - "detected": [{label, confidence}, ...] — canonical structured form
        # - "items": [str, ...]  — flat list for the PhotoReviewSheet.tsx client
        return {
            "detected": [{"label": d.label, "confidence": d.confidence} for d in detected],
            "items": [d.label for d in detected],
        }

    # ------------------------------------------------------------------
    # Barcode — decode + cache-first OFF lookup
    # ------------------------------------------------------------------

    @app.post("/navigator/pantry/barcode")
    async def post_pantry_barcode(
        image: UploadFile = File(..., description="Photo of a product barcode (JPEG/PNG, ≤8 MiB)"),  # noqa: B008
    ) -> dict[str, Any]:
        """Decode a barcode photo, look it up in OFF (cache-first), return a candidate.

        Read-only: does NOT add to the pantry. The client confirms, then POSTs to
        /navigator/pantry/items with {raw_text, canonical_name, source:"barcode"}.
        """
        from pantryatlas.navigator.barcode import (
            decode_barcode,
            product_to_ingredient,
            upc_ean_variants,
        )

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
        off = app.state.off_client
        product = None
        for variant in upc_ean_variants(code):
            product = kitchen.get_cached_off(variant)
            if product is not None:
                break
            if off is None:
                return {"found": False, "code": code, "error": "off_unavailable"}
            try:
                product = off.get_product(variant)
            except OffUnavailable:
                return {"found": False, "code": code, "error": "off_unavailable"}
            if product is not None:
                kitchen.cache_off(variant, product)
                break

        if product is None:
            return {"found": False, "code": code}

        ingredient, matched = product_to_ingredient(product, app.state.resolver)
        return {
            "found": True,
            "code": code,
            "product": {
                "name": product.get("product_name") or "",
                "brand": product.get("brands") or "",
            },
            "proposed": {
                "canonical_name": ingredient.canonical_name,
                "raw_text": ingredient.raw_text,
                "matched": matched,
            },
        }

    # ------------------------------------------------------------------
    # Provider registry REST API
    # ------------------------------------------------------------------

    def _persist_providers() -> None:
        reg = app.state.provider_registry
        path = app.state.providers_config_path
        if reg is not None and path is not None:
            save_provider_config([p.to_config() for p in reg.all()], path)

    @app.get("/navigator/providers")
    def list_providers() -> list[dict[str, Any]]:
        reg = app.state.provider_registry
        if reg is None:
            return []
        return [
            {
                "name": i.name, "kind": i.kind, "capabilities": i.capabilities,
                "priority": i.priority, "enabled": i.enabled, "available": i.available,
            }
            for i in reg.providers_status()
        ]

    @app.post("/navigator/providers", status_code=201)
    def add_provider(body: ProviderIn) -> dict[str, Any]:
        reg = app.state.provider_registry
        if reg is None:
            raise HTTPException(status_code=503, detail="Provider registry not configured.")
        if reg.get(body.name) is not None:
            raise HTTPException(status_code=409, detail=f"Provider '{body.name}' already exists.")
        caps = ["text", "vision"] if body.multimodal else ["text"]
        reg.add(LanEndpointProvider(
            name=body.name, base_url=body.base_url, priority=10, capabilities=caps,
        ))
        _persist_providers()
        return {"name": body.name, "capabilities": caps}

    @app.post("/navigator/providers/{name}/test")
    def test_provider(name: str) -> dict[str, Any]:
        reg = app.state.provider_registry
        p = reg.get(name) if reg is not None else None
        if p is None:
            raise HTTPException(status_code=404, detail=f"No provider '{name}'.")
        return {"name": name, "available": p.force_probe()}

    @app.delete("/navigator/providers/{name}")
    def delete_provider(name: str) -> dict[str, str]:
        reg = app.state.provider_registry
        if reg is None or not reg.remove(name):
            raise HTTPException(status_code=404, detail=f"No provider '{name}'.")
        _persist_providers()
        return {"deleted": name}

    @app.put("/navigator/providers/order")
    def reorder_providers(ordered_names: list[str]) -> list[dict[str, Any]]:
        reg = app.state.provider_registry
        if reg is None:
            raise HTTPException(status_code=503, detail="Provider registry not configured.")
        reg.reorder(ordered_names)
        _persist_providers()
        return list_providers()

    # ------------------------------------------------------------------
    # Device trust fabric
    # ------------------------------------------------------------------

    @app.post("/navigator/devices/enroll", status_code=201)
    def enroll_device(body: DeviceEnrollIn) -> dict[str, Any]:
        if body.role not in _DEVICE_ROLES:
            raise HTTPException(
                status_code=422,
                detail=f"role must be one of {list(_DEVICE_ROLES)}",
            )
        device = _get_kitchen(app).enroll_device(body.name, body.role, body.kind, body.caps)
        return {"device_id": device["device_id"], "status": device["status"]}

    @app.get("/navigator/devices")
    def list_devices() -> list[dict[str, Any]]:
        return _get_kitchen(app).list_devices()

    @app.get("/navigator/devices/me")
    def device_me(authorization: str | None = Header(default=None)) -> dict[str, Any]:
        from pantryatlas.navigator.device_auth import hash_token
        if not authorization or not authorization.lower().startswith("bearer "):
            raise HTTPException(status_code=401, detail="missing bearer token")
        token = authorization.split(" ", 1)[1].strip()
        device = _get_kitchen(app).device_by_token_hash(hash_token(token))
        if device is None:
            raise HTTPException(status_code=401, detail="invalid token")
        return device

    @app.post("/navigator/devices/{device_id}/approve")
    def approve_device(device_id: str) -> dict[str, Any]:
        from pantryatlas.navigator.device_auth import hash_token, mint_token
        # Re-approving a paired device rotates the token: a fresh token is issued
        # and the previous one stops verifying.
        token = mint_token()
        device = _get_kitchen(app).approve_device(device_id, hash_token(token))
        if device is None:
            raise HTTPException(status_code=404, detail=f"No device '{device_id}'.")
        return {"device_id": device_id, "status": "paired", "token": token}

    @app.post("/navigator/devices/{device_id}/reject")
    def reject_device(device_id: str) -> dict[str, Any]:
        device = _get_kitchen(app).reject_device(device_id)
        if device is None:
            raise HTTPException(status_code=404, detail=f"No device '{device_id}'.")
        return {"device_id": device_id, "status": "rejected"}

    @app.delete("/navigator/devices/{device_id}")
    def delete_device(device_id: str) -> dict[str, str]:
        if not _get_kitchen(app).remove_device(device_id):
            raise HTTPException(status_code=404, detail=f"No device '{device_id}'.")
        return {"deleted": device_id}

    return app


def _ranked_to_dict(r: RankedRecipe) -> dict[str, Any]:
    """Serialise a RankedRecipe to the API wire shape (with source attribution)."""
    return {
        "recipe": r.recipe,
        "score": r.score,
        "coverage": r.coverage,
        "missing": r.missing,
        "expiration_urgency": r.expiration_urgency,
        "substitution_penalty": r.substitution_penalty,
        "cultural_fit": r.cultural_fit,
        "flavor": r.flavor,
        "source": RECIPE_SOURCE_ATTRIBUTION,
    }


# ---------------------------------------------------------------------------
# Production wiring (module-level app)
# ---------------------------------------------------------------------------
# Importing this module does NOT open the database or create any directories.
# The real RecipeStore is built lazily on first request via store_factory.
# ``python -c 'from pantryatlas.navigator.server import app'`` is fast and
# side-effect-free: no mkdir, no sqlite3.connect, no sqlite-vec load.

_DEFAULT_PANTRY_PATH = Path.home() / ".pantryatlas" / "pantry.json"
_DEFAULT_DB_PATH = Path.home() / ".pantryatlas" / "recipes.db"
_DEFAULT_KITCHEN_DB_PATH = Path.home() / ".pantryatlas" / "kitchen.db"


def _make_production_store_factory() -> Callable[[], RecipeStore]:
    """Return a zero-argument factory that opens the real production RecipeStore.

    The factory is called lazily on first request, so importing the module
    does NOT touch the filesystem.
    """

    def _factory() -> RecipeStore:
        from pantryatlas.store.recipes import RecipeStore as _RS

        _DEFAULT_DB_PATH.parent.mkdir(parents=True, exist_ok=True)
        return _RS(_DEFAULT_DB_PATH)

    return _factory


def _make_production_kitchen_factory() -> Callable[[], KitchenStore]:
    """Return a factory that opens the real KitchenStore and migrates pantry.json once."""

    def _factory() -> KitchenStore:
        return KitchenStore(_DEFAULT_KITCHEN_DB_PATH, pantry_json_path=_DEFAULT_PANTRY_PATH)

    return _factory


def _build_production_app() -> FastAPI:
    """Build the production app with lazy store, resolver, and embed_fn.

    No filesystem I/O occurs here — everything is deferred to first use.
    """
    from pantryatlas.inference.config import DEFAULT_CONFIG_PATH, load_provider_config
    from pantryatlas.inference.providers.local_runner import LocalRunnerProvider

    def _build_registry() -> ProviderRegistry:
        providers = []
        for cfg in load_provider_config(DEFAULT_CONFIG_PATH):
            if cfg.kind == "local":
                providers.append(LocalRunnerProvider(
                    name=cfg.name, priority=cfg.priority, enabled=cfg.enabled,
                    capabilities=cfg.capabilities,
                ))
            elif cfg.kind == "lan" and cfg.base_url:
                providers.append(LanEndpointProvider(
                    name=cfg.name, base_url=cfg.base_url, priority=cfg.priority,
                    enabled=cfg.enabled, capabilities=cfg.capabilities,
                ))
        return ProviderRegistry(providers)

    from pantryatlas.pantry import Matcher
    from pantryatlas.pantry._default_vocab import DEFAULT_VOCAB_NAMES

    # Use module-level lazy embed so ONNX loads only once, shared across routes.
    def _prod_embed(texts: list[str]) -> np.ndarray:
        from pantryatlas.embeddings import embed

        return embed(texts)

    def _prod_resolver(raw: str) -> Ingredient | None:
        # Lazy Matcher construction: avoids ONNX load unless a route is called.
        if not hasattr(_prod_resolver, "_matcher"):
            embs = _prod_embed(DEFAULT_VOCAB_NAMES)
            _prod_resolver._matcher = Matcher(  # type: ignore[attr-defined]
                canonical_names=DEFAULT_VOCAB_NAMES,
                embeddings=embs,
                embed_fn=_prod_embed,
            )
        return _prod_resolver._matcher.resolve(raw)  # type: ignore[attr-defined]

    return create_app(
        store_factory=_make_production_store_factory(),
        resolver=_prod_resolver,
        embed_fn=_prod_embed,
        pantry_path=_DEFAULT_PANTRY_PATH,
        provider_registry=_build_registry(),
        providers_config_path=DEFAULT_CONFIG_PATH,
        kitchen_factory=_make_production_kitchen_factory(),
        off_client=OpenFoodFactsClient(),
        vision_client=_build_vision_client(),
    )


def _build_vision_client() -> GemmaClient | None:
    """Return a vision GemmaClient when vision is enabled, else None (→ 503).

    Opt-in: set ``PANTRYATLAS_VISION=1`` on deployments that have bootstrapped
    the mmproj and run llama-server with ``--mmproj`` (the gemma service started
    with vision).  ``PANTRYATLAS_VISION_URL`` overrides the llama-server base URL
    (default: the GemmaClient default, http://127.0.0.1:8080).  When the model
    isn't actually vision-capable or is unreachable, ``vision_generate`` raises
    ``VisionUnavailable`` and the route returns 503 — the graceful path.
    """
    if os.environ.get("PANTRYATLAS_VISION") != "1":
        return None
    from pantryatlas.gemma.client import GemmaClient

    url = os.environ.get("PANTRYATLAS_VISION_URL")
    return GemmaClient(base_url=url) if url else GemmaClient()


app: FastAPI = _build_production_app()
