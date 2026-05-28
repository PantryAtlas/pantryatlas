"""T-004: FastAPI navigator endpoint.

Exposes 7 API routes + static PWA serving for the PantryAtlas navigator
submodule (pantry-in → ranked-recipes-out).

Routes
------
GET  /navigator/health                  → {"status":"ok","recipe_count":<int>}
GET  /navigator/pantry                  → current pantry (list of items)
PUT  /navigator/pantry                  → replace whole pantry (Pydantic-validated)
POST /navigator/pantry/items            → add one item from {raw_text:...}, 201
DELETE /navigator/pantry/items/{name}   → remove one item by canonical name
POST /navigator/pantry/resolve          → resolve {raw:...} WITHOUT persisting
POST /navigator/recipes/from-pantry     → rank recipes against current pantry

Static
------
GET  /                                  → serves web/dist/index.html if present,
                                          else a JSON placeholder
/assets/*                               → static files from web/dist/assets if present

Design decisions
----------------
- ``create_app()`` factory keeps ONNX model + real DB out of the test process.
- Pantry is persisted to a flat JSON file at ``pantry_path``
  (default ~/.pantryatlas/pantry.json; overridable via app.state).
- Pre-filter for /recipes/from-pantry uses text-overlap against
  recipes_meta.ingredients_json — no embedding at pre-filter time.
  Candidates are then scored by rank_recipes() with the injected embed_fn.
- No CORSMiddleware is added: the same-origin PWA needs no permissive CORS
  and its absence guarantees no Access-Control-Allow-Origin: * header.
- Static mount is guarded: StaticFiles is only mounted when web/dist/assets
  exists so the import never fails when the frontend isn't built yet.
- The module-level ``app`` is side-effect-free at import time: no DB is opened,
  no directory is created.  The real RecipeStore is opened lazily on first use
  via ``app.state.store_factory`` (set by ``_build_production_app``).
"""

from __future__ import annotations

import json
from collections.abc import Callable
from datetime import date
from pathlib import Path
from typing import TYPE_CHECKING, Any

import numpy as np
from fastapi import FastAPI, File, HTTPException, UploadFile
from fastapi.responses import FileResponse, JSONResponse
from fastapi.staticfiles import StaticFiles
from pydantic import BaseModel

from pantryatlas.navigator.ranking import RankedRecipe, rank_recipes
from pantryatlas.pantry.models import Ingredient, Pantry, Quantity
from pantryatlas.store.recipes import RecipeStore

if TYPE_CHECKING:
    from pantryatlas.gemma.client import GemmaClient

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


class ResolveIn(BaseModel):
    """Body for POST /navigator/pantry/resolve."""

    raw: str


# ---------------------------------------------------------------------------
# Pantry JSON serialisation
# ---------------------------------------------------------------------------


def _pantry_to_list(pantry: Pantry) -> list[dict[str, Any]]:
    """Serialise ``Pantry`` to a list of dicts suitable for JSON encoding."""
    result = []
    for ing in pantry:
        item: dict[str, Any] = {
            "canonical_name": ing.canonical_name,
            "raw_text": ing.raw_text,
        }
        if ing.quantity is not None:
            item["quantity"] = {
                "amount": ing.quantity.amount,
                "unit": ing.quantity.unit,
            }
        if ing.expires_at is not None:
            item["expires_at"] = ing.expires_at.isoformat()
        result.append(item)
    return result


def _load_pantry(pantry_path: Path) -> Pantry:
    """Load Pantry from JSON file; returns empty Pantry when file absent."""
    pantry = Pantry()
    if not pantry_path.exists():
        return pantry
    raw = json.loads(pantry_path.read_text(encoding="utf-8"))
    for item in raw:
        qty = None
        if item.get("quantity"):
            qty = Quantity(
                amount=item["quantity"]["amount"],
                unit=item["quantity"].get("unit", ""),
            )
        exp = None
        if item.get("expires_at"):
            exp = date.fromisoformat(item["expires_at"])
        pantry.add(
            Ingredient(
                canonical_name=item["canonical_name"],
                raw_text=item["raw_text"],
                quantity=qty,
                expires_at=exp,
            )
        )
    return pantry


def _save_pantry(pantry: Pantry, pantry_path: Path) -> None:
    """Persist Pantry to JSON file, creating parent dirs as needed."""
    pantry_path.parent.mkdir(parents=True, exist_ok=True)
    pantry_path.write_text(
        json.dumps(_pantry_to_list(pantry), indent=2),
        encoding="utf-8",
    )


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
        pantry_path: Path to the flat JSON pantry file.
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

    app = FastAPI(
        title="PantryAtlas Navigator",
        description="Pantry-in → ranked-recipes-out API",
        version="0.2.0",
    )

    # Store dependencies on app.state so route handlers can access them.
    app.state.store = store  # None when using factory; _get_store() fills lazily
    app.state.store_factory = store_factory
    app.state.resolver = resolver
    app.state.embed_fn = embed_fn
    app.state.pantry_path = pantry_path
    # vision_client is None by default → 503 until operator loads mmproj
    app.state.vision_client = vision_client

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
        pantry = _load_pantry(app.state.pantry_path)
        return _pantry_to_list(pantry)

    # ------------------------------------------------------------------
    # Pantry — replace
    # ------------------------------------------------------------------

    @app.put("/navigator/pantry")
    def put_pantry(items: list[IngredientIn]) -> list[dict[str, Any]]:
        """Replace the whole pantry with the provided list (Pydantic-validated)."""
        pantry = Pantry()
        for item in items:
            qty = None
            if item.quantity is not None:
                qty = Quantity(amount=item.quantity.amount, unit=item.quantity.unit)
            pantry.add(
                Ingredient(
                    canonical_name=item.canonical_name,
                    raw_text=item.raw_text,
                    quantity=qty,
                    expires_at=item.expires_at,
                )
            )
        _save_pantry(pantry, app.state.pantry_path)
        return _pantry_to_list(pantry)

    # ------------------------------------------------------------------
    # Pantry — add one item
    # ------------------------------------------------------------------

    @app.post("/navigator/pantry/items", status_code=201)
    def post_pantry_item(body: AddItemIn) -> dict[str, Any]:
        """Add one ingredient from raw text.  Returns the resolved canonical_name."""
        ingredient = app.state.resolver(body.raw_text)
        if ingredient is None:
            raise HTTPException(
                status_code=422,
                detail=f"Cannot resolve '{body.raw_text}' to a canonical ingredient.",
            )
        pantry = _load_pantry(app.state.pantry_path)
        pantry.add(ingredient)
        _save_pantry(pantry, app.state.pantry_path)
        return {
            "canonical_name": ingredient.canonical_name,
            "raw_text": ingredient.raw_text,
        }

    # ------------------------------------------------------------------
    # Pantry — remove one item
    # ------------------------------------------------------------------

    @app.delete("/navigator/pantry/items/{name}")
    def delete_pantry_item(name: str) -> dict[str, str]:
        """Remove an ingredient by canonical name (no-op if not present)."""
        pantry = _load_pantry(app.state.pantry_path)
        pantry.remove(name)
        _save_pantry(pantry, app.state.pantry_path)
        return {"removed": name}

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
        """Pre-filter candidate recipes from the store and rank them.

        Pre-filter strategy: text-overlap against recipes_meta.ingredients_json.
        Any recipe whose ingredients list shares at least one canonical name with
        the current pantry is included as a candidate.  This avoids embedding at
        pre-filter time and is trivially testable.

        Candidates are then ranked via rank_recipes() using the injected embed_fn.
        """
        pantry = _load_pantry(app.state.pantry_path)
        canonical_names = [ing.canonical_name for ing in pantry]

        candidates = _get_store(app).iter_overlapping(canonical_names)

        if not candidates:
            # Fall back: return empty list rather than 500
            return []

        ranked: list[RankedRecipe] = rank_recipes(
            pantry,
            candidates,
            app.state.embed_fn,
            cuisine=cuisine,
        )

        return [
            {
                "recipe": r.recipe,
                "score": r.score,
                "coverage": r.coverage,
                "missing": r.missing,
                "expiration_urgency": r.expiration_urgency,
                "substitution_penalty": r.substitution_penalty,
                "cultural_fit": r.cultural_fit,
            }
            for r in ranked
        ]

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

        client = app.state.vision_client
        if client is None:
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
            detected = parse_shelf(raw_bytes, client)
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

    return app


# ---------------------------------------------------------------------------
# Production wiring (module-level app)
# ---------------------------------------------------------------------------
# Importing this module does NOT open the database or create any directories.
# The real RecipeStore is built lazily on first request via store_factory.
# ``python -c 'from pantryatlas.navigator.server import app'`` is fast and
# side-effect-free: no mkdir, no sqlite3.connect, no sqlite-vec load.

_DEFAULT_PANTRY_PATH = Path.home() / ".pantryatlas" / "pantry.json"
_DEFAULT_DB_PATH = Path.home() / ".pantryatlas" / "recipes.db"


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


def _build_production_app() -> FastAPI:
    """Build the production app with lazy store, resolver, and embed_fn.

    No filesystem I/O occurs here — everything is deferred to first use.
    """
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
    )


app: FastAPI = _build_production_app()
