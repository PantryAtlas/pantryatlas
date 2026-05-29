"""
Mock backend for T-007 + T-008 screenshot testing and the SP-A loop verify.
Implements pantry routes + POST /navigator/recipes/from-pantry, now backed by a
real ``KitchenStore`` so the full cook -> decrement -> timeline loop is exercised
against the same persistence the production app uses (no sqlite-vec dependency).

Resolved vocab: garlic, onion, kale, tomato, butternut squash, olive oil, salt,
               black pepper, vegetable broth, onion
Seeded pantry: garlic (expires tomorrow) + kale (expires today = error-container chip)
Canned recipes: realistic RecipeNLG-shaped ranked results for screenshot testing.

SP-A routes added (all backed by KitchenStore):
  POST   /navigator/cook                            log a cook event + soft-decrement
  GET    /navigator/meals                           cook-event timeline (newest first)
  GET    /navigator/waste                           discard/expire tally
  POST   /navigator/pantry/items/{name}/consume     coarse consume transition
  POST   /navigator/pantry/items/{name}/restore     restore a consumed item

SP-C routes added (all backed by KitchenStore + real device_auth):
  POST   /navigator/devices/enroll                  enroll a device (pending)
  GET    /navigator/devices                         list all devices (never leaks token)
  POST   /navigator/devices/{id}/approve            approve → mint + return raw token once
  POST   /navigator/devices/{id}/reject             reject a device
  DELETE /navigator/devices/{id}                    remove a device

Env:
  MOCK_KITCHEN_DB     path to the kitchen.db SQLite file. If unset, an isolated
                      per-process temp file is used and the default two items are
                      seeded (keeps the sibling screenshot scripts working). When
                      set (e.g. by verify_loop.mjs), the store starts EMPTY so the
                      verify run is fully deterministic.
  MOCK_REFINE_DELAY_S artificial /refine delay for the "refining…" screenshot.
"""
from __future__ import annotations

import asyncio
import os
import tempfile
from datetime import date, timedelta
from pathlib import Path

import uvicorn
from fastapi import FastAPI, HTTPException, Request
from fastapi.middleware.cors import CORSMiddleware
from fastapi.staticfiles import StaticFiles
from pydantic import BaseModel

from pantryatlas.navigator.device_auth import hash_token, mint_token
from pantryatlas.pantry.models import Ingredient
from pantryatlas.store.kitchen import KitchenStore

# Artificial delay (seconds) on /refine so the "refining…" chip is visible long
# enough to screenshot. Only affects this mock — the real backend has no delay.
REFINE_DELAY_S = float(os.environ.get("MOCK_REFINE_DELAY_S", "1.2"))

app = FastAPI()

# Minimal CORS for dev proxy
app.add_middleware(
    CORSMiddleware,
    allow_origins=["*"],
    allow_methods=["*"],
    allow_headers=["*"],
)

# ---------------------------------------------------------------------------
# Vocab + KitchenStore-backed pantry
# ---------------------------------------------------------------------------
VOCAB = {
    "garlic": "garlic",
    "onion": "onion",
    "kale": "kale",
    "tomato": "tomato",
    "butternut squash": "butternut squash",
    "olive oil": "olive oil",
    "salt": "salt",
    "black pepper": "black pepper",
    "vegetable broth": "vegetable broth",
}

TODAY = date.today().isoformat()
TOMORROW = (date.today() + timedelta(days=1)).isoformat()

# Default seed used only when MOCK_KITCHEN_DB is unset (screenshot scripts).
_DEFAULT_SEED = [
    Ingredient(canonical_name="garlic", raw_text="garlic",
               expires_at=date.today() + timedelta(days=1)),
    Ingredient(canonical_name="kale", raw_text="wilting kale",
               expires_at=date.today()),
]


def _make_kitchen() -> KitchenStore:
    """Open the KitchenStore. A persistent path (MOCK_KITCHEN_DB) starts empty;
    otherwise use a fresh temp db seeded with the default two items."""
    db_env = os.environ.get("MOCK_KITCHEN_DB")
    if db_env:
        return KitchenStore(db_env)
    tmp = Path(tempfile.mkdtemp(prefix="pa-mock-")) / "kitchen.db"
    store = KitchenStore(tmp)
    for ing in _DEFAULT_SEED:
        store.add_item(ing)
    return store


KITCHEN = _make_kitchen()


def _on_hand_names() -> set[str]:
    """Canonical names of items that count as on-hand (present | low)."""
    return {ing.canonical_name for ing in KITCHEN.on_hand()}


# ---------------------------------------------------------------------------
# Pantry routes (KitchenStore-backed)
# ---------------------------------------------------------------------------

@app.get("/navigator/pantry")
def get_pantry():
    return KITCHEN.list_items()

@app.put("/navigator/pantry")
async def put_pantry(request: Request):
    body = await request.json()
    ingredients = [
        Ingredient(canonical_name=it["canonical_name"],
                   raw_text=it.get("raw_text", it["canonical_name"]))
        for it in body
    ]
    return KITCHEN.replace_all(ingredients)

@app.post("/navigator/pantry/items", status_code=201)
async def post_pantry_item(request: Request):
    body = await request.json()
    raw = body.get("raw_text", "")
    source = body.get("source", "manual")
    canonical_name = body.get("canonical_name")

    if canonical_name:
        # Barcode (or any explicit-canonical) confirm path — bypass VOCAB.
        ingredient = Ingredient(canonical_name=canonical_name, raw_text=raw)
    else:
        resolved = VOCAB.get(raw.strip().lower())
        if not resolved:
            raise HTTPException(status_code=422, detail=f"Cannot resolve '{raw}'")
        ingredient = Ingredient(canonical_name=resolved, raw_text=raw.strip().lower())

    item = KITCHEN.add_item(ingredient, source=source)
    return {
        "canonical_name": item["canonical_name"],
        "raw_text": item["raw_text"],
        "source": item.get("source", source),
    }

@app.delete("/navigator/pantry/items/{name}")
def delete_pantry_item(name: str):
    KITCHEN.remove_item(name)
    return {"removed": name}

@app.post("/navigator/pantry/items/{name}/consume")
async def consume_pantry_item(name: str, request: Request):
    body = await request.json()
    item = KITCHEN.consume_item(name, body.get("coarse_amount", "used_up"))
    if item is None:
        raise HTTPException(status_code=404, detail=f"No pantry item '{name}'.")
    return item

@app.post("/navigator/pantry/items/{name}/restore")
def restore_pantry_item(name: str):
    item = KITCHEN.restore_item(name)
    if item is None:
        raise HTTPException(status_code=404, detail=f"No pantry item '{name}'.")
    return item

@app.post("/navigator/pantry/resolve")
async def post_resolve(request: Request):
    body = await request.json()
    raw = body.get("raw", "").strip().lower()
    canonical = VOCAB.get(raw)
    if not canonical:
        raise HTTPException(status_code=404, detail=f"Cannot resolve '{raw}'")
    return {"canonical_name": canonical}

# ---------------------------------------------------------------------------
# Cook / meals / waste routes (KitchenStore-backed)
# ---------------------------------------------------------------------------

@app.post("/navigator/cook", status_code=201)
async def post_cook(request: Request):
    body = await request.json()
    # The real "I cooked this" button always sends an explicit, non-empty
    # `consumed` array (covered ingredients with coarse_amount='cook'); the
    # KitchenStore drops any name that is not on-hand. That is the load-bearing
    # path this mock guards for verify_loop.mjs.
    consumed = [
        {"canonical_name": c["canonical_name"],
         "coarse_amount": c.get("coarse_amount", "cook")}
        for c in (body.get("consumed") or [])
    ]
    return KITCHEN.add_cook_event(
        dish_name=body["dish_name"],
        recipe_id=body.get("recipe_id"),
        servings=body.get("servings"),
        rating=body.get("rating"),
        notes=body.get("notes"),
        consumed=consumed,
    )

@app.get("/navigator/meals")
def get_meals(limit: int = 50):
    return KITCHEN.list_meals(limit=limit)

@app.get("/navigator/waste")
def get_waste(window_days: int = 30):
    return KITCHEN.waste_tally(window_days=window_days)

# ---------------------------------------------------------------------------
# Canned recipe data (RecipeNLG shape)
# ---------------------------------------------------------------------------

CANNED_RECIPES = [
    {
        "recipe": {
            "title": "Butternut & Kale Stew",
            "ingredients": [
                "butternut squash",
                "kale",
                "garlic",
                "onion",
                "vegetable broth",
                "olive oil",
                "black pepper",
                "nutmeg",
                "chili flakes",
                "lemon juice",
            ],
            "instructions": [
                "Heat olive oil in a large pot over medium heat. Add diced onion and cook until translucent, about 5 minutes.",
                "Add minced garlic and cook for another minute until fragrant.",
                "Add the peeled and cubed butternut squash, stir to coat with the oil.",
                "Pour in the vegetable broth and bring to a boil. Reduce heat and simmer for 15 minutes until squash is tender.",
                "Stir in the chopped kale and cook for 3–4 minutes until wilted.",
                "Season with black pepper, nutmeg, and a squeeze of lemon juice. Serve hot.",
            ],
            "cook_time_min": 30,
            "source": "RecipeNLG",
        },
        "score": 0.82,
        "coverage": 0.8,
        "missing": ["nutmeg", "chili flakes"],
        "expiration_urgency": 0.75,
        "substitution_penalty": 0.18,
        "cultural_fit": 0.0,
    },
    {
        "recipe": {
            "title": "Roasted Squash & Onion",
            "ingredients": [
                "butternut squash",
                "onion",
                "olive oil",
                "salt",
                "black pepper",
                "thyme",
                "rosemary",
                "maple syrup",
                "apple cider vinegar",
                "walnuts",
            ],
            "instructions": [
                "Preheat oven to 400°F (200°C). Line a baking sheet with parchment paper.",
                "Peel and cube the butternut squash into 1-inch pieces. Slice the onion into wedges.",
                "Toss squash and onion with olive oil, salt, and black pepper.",
                "Spread in a single layer on the baking sheet. Roast for 25 minutes.",
                "Drizzle with maple syrup and apple cider vinegar. Scatter thyme and rosemary over top.",
                "Return to oven for 10 more minutes until caramelized. Top with chopped walnuts to serve.",
            ],
            "cook_time_min": 40,
            "source": "RecipeNLG",
        },
        "score": 0.61,
        "coverage": 0.6,
        "missing": ["thyme", "rosemary", "maple syrup", "apple cider vinegar"],
        "expiration_urgency": 0.1,
        "substitution_penalty": 0.3,
        "cultural_fit": 0.0,
    },
    {
        "recipe": {
            "title": "Garlic Kale Stir-Fry",
            "ingredients": [
                "kale",
                "garlic",
                "olive oil",
                "salt",
                "black pepper",
                "soy sauce",
                "sesame oil",
            ],
            "instructions": [
                "Wash and roughly chop the kale, removing tough stems.",
                "Heat olive oil in a large skillet or wok over high heat.",
                "Add minced garlic and stir-fry for 30 seconds until golden.",
                "Add kale in batches, tossing with tongs until wilted, about 3–4 minutes.",
                "Season with soy sauce, sesame oil, salt, and black pepper. Serve immediately.",
            ],
            "cook_time_min": 12,
            "source": "RecipeNLG",
        },
        "score": 0.55,
        "coverage": 0.71,
        "missing": ["soy sauce", "sesame oil"],
        "expiration_urgency": 0.5,
        "substitution_penalty": 0.22,
        "cultural_fit": 0.0,
    },
]


def _overlap_results(pantry_names: set[str]) -> list[dict]:
    """Canned recipes overlapping the pantry, with missing/coverage recomputed."""
    results = []
    for r in CANNED_RECIPES:
        recipe_ings = set(r["recipe"]["ingredients"])
        if recipe_ings & pantry_names:
            missing = [ing for ing in r["recipe"]["ingredients"] if ing not in pantry_names]
            total = len(r["recipe"]["ingredients"])
            present = total - len(missing)
            coverage = present / total if total > 0 else 0.0
            results.append({**r, "missing": missing, "coverage": coverage})
    return results


def _score(cov: float, exp: float, penalty: float, cult: float) -> float:
    return 0.50 * cov + 0.20 * exp + 0.20 * (1.0 - penalty) + 0.10 * cult


@app.post("/navigator/recipes/from-pantry")
async def post_recipes_from_pantry(request: Request):
    """INSTANT fast mode: coverage-ranked, substitution_penalty=0 (optimistic)."""
    try:
        await request.json()
    except Exception:
        pass

    pantry_names = _on_hand_names()
    if not pantry_names:
        return []

    results = []
    for r in _overlap_results(pantry_names):
        cov = r["coverage"]
        results.append({
            **r,
            "substitution_penalty": 0.0,
            "score": _score(cov, r.get("expiration_urgency", 0.0), 0.0, 0.0),
            "source": "RecipeNLG (CC-BY-NC-4.0)",
        })
    # Coverage order (fast mode): highest coverage first.
    results.sort(key=lambda x: x["score"], reverse=True)
    return results


# Canned "real" substitution penalties used by /refine to settle the order.
# Butternut's missing (nutmeg/chili) have no close pantry swap → high penalty →
# it drops below Garlic Kale Stir-Fry, demonstrating the live re-order.
_REFINE_PENALTY = {
    "Butternut & Kale Stew": 0.55,
    "Garlic Kale Stir-Fry": 0.12,
    "Roasted Squash & Onion": 0.40,
}


@app.post("/navigator/recipes/from-pantry/refine")
async def post_recipes_refine(request: Request):
    """Re-rank the client-sent recipes with 'real' substitution penalties."""
    if REFINE_DELAY_S > 0:
        await asyncio.sleep(REFINE_DELAY_S)
    try:
        recipes = await request.json()
    except Exception:
        recipes = []
    if not recipes:
        return []

    out = []
    for rec in recipes:
        title = rec.get("title", "")
        ings = rec.get("ingredients", [])
        pantry_names = _on_hand_names()
        missing = [ing for ing in ings if ing not in pantry_names]
        total = len(ings)
        cov = (total - len(missing)) / total if total else 0.0
        penalty = _REFINE_PENALTY.get(title, 0.25)
        exp = 0.5 if "kale" in pantry_names and "kale" in ings else 0.0
        out.append({
            "recipe": rec,
            "score": _score(cov, exp, penalty, 0.0),
            "coverage": cov,
            "missing": missing,
            "expiration_urgency": exp,
            "substitution_penalty": penalty,
            "cultural_fit": 0.0,
            "source": "RecipeNLG (CC-BY-NC-4.0)",
        })
    out.sort(key=lambda x: x["score"], reverse=True)
    return out


# Canned swap suggestions for the expanded-card demo (best_swap + no-match states).
_SWAP_MAP = {
    "soy sauce": {"best_swap": "salt", "similarity": 0.58, "reason": None},
    "sesame oil": {"best_swap": "olive oil", "similarity": 0.81, "reason": None},
    "vegetable broth": {"best_swap": "water", "similarity": 0.66, "reason": None},
    "onion": {"best_swap": "garlic", "similarity": 0.74, "reason": None},
}


@app.post("/navigator/recipes/swaps")
async def post_recipes_swaps(request: Request):
    """Per-missing swap suggestions; unknown items report no close match."""
    try:
        body = await request.json()
    except Exception:
        body = {}
    ings = body.get("ingredients", [])
    pantry_names = _on_hand_names()
    swaps = []
    seen = set()
    for ing in ings:
        if ing in pantry_names or ing in seen:
            continue
        seen.add(ing)
        hit = _SWAP_MAP.get(ing)
        if hit:
            swaps.append({"missing": ing, **hit})
        else:
            swaps.append(
                {"missing": ing, "best_swap": None, "similarity": 0.31, "reason": "no_close_match"}
            )
    return {"swaps": swaps}


# ---------------------------------------------------------------------------
# Barcode route — canned candidate (no real decode / OFF lookup in the mock)
# ---------------------------------------------------------------------------

@app.post("/navigator/pantry/barcode")
async def post_pantry_barcode(request: Request):
    """Canned barcode response for headless verify.

    The real route decodes the uploaded image and looks it up in Open Food
    Facts; the mock skips both and returns a fixed known-product candidate so
    verify_barcode.mjs can drive the confirm sheet without needing a real
    barcode image or internet access.
    """
    return {
        "found": True,
        "code": "737628064502",
        "product": {"name": "Rice Noodles", "brand": "Thai Kitchen"},
        "proposed": {
            "canonical_name": "noodles",
            "raw_text": "Rice Noodles (Thai Kitchen)",
            "matched": True,
        },
    }


# ---------------------------------------------------------------------------
# SP-C Device-trust fabric routes (KitchenStore-backed, real device_auth)
# ---------------------------------------------------------------------------

_DEVICE_ROLES = ("compute", "sensor")


class _DeviceEnrollIn(BaseModel):
    name: str
    role: str
    kind: str | None = None
    caps: list[str] | None = None


@app.post("/navigator/devices/enroll", status_code=201)
def enroll_device(body: _DeviceEnrollIn):
    if body.role not in _DEVICE_ROLES:
        raise HTTPException(status_code=422, detail=f"role must be one of {list(_DEVICE_ROLES)}")
    device = KITCHEN.enroll_device(body.name, body.role, body.kind, body.caps)
    return {"device_id": device["device_id"], "status": device["status"]}


@app.get("/navigator/devices")
def list_devices():
    return KITCHEN.list_devices()


@app.post("/navigator/devices/{device_id}/approve")
def approve_device(device_id: str):
    token = mint_token()
    device = KITCHEN.approve_device(device_id, hash_token(token))
    if device is None:
        raise HTTPException(status_code=404, detail=f"No device '{device_id}'.")
    return {"device_id": device_id, "status": "paired", "token": token}


@app.post("/navigator/devices/{device_id}/reject")
def reject_device(device_id: str):
    device = KITCHEN.reject_device(device_id)
    if device is None:
        raise HTTPException(status_code=404, detail=f"No device '{device_id}'.")
    return {"device_id": device_id, "status": "rejected"}


@app.delete("/navigator/devices/{device_id}")
def delete_device(device_id: str):
    if not KITCHEN.remove_device(device_id):
        raise HTTPException(status_code=404, detail=f"No device '{device_id}'.")
    return {"deleted": device_id}


# /navigator/vision/parse-shelf → 404 (T-014 not yet built)
@app.post("/navigator/vision/parse-shelf")
async def parse_shelf():
    raise HTTPException(status_code=404, detail="Vision endpoint not yet available")

@app.get("/navigator/health")
def health():
    return {"status": "ok", "recipe_count": len(CANNED_RECIPES)}

# Serve the built PWA from the same origin (so no dev proxy is needed for
# screenshots). Mounted last so the explicit /navigator/* routes win.
_DIST = Path(__file__).parent / "dist"
if _DIST.exists():
    app.mount("/", StaticFiles(directory=str(_DIST), html=True), name="dist")

if __name__ == "__main__":
    port = int(os.environ.get("MOCK_PORT", "8099"))
    uvicorn.run(app, host="127.0.0.1", port=port, log_level="warning")
