"""
Mock backend for T-007 + T-008 screenshot testing.
Implements pantry routes + POST /navigator/recipes/from-pantry.

Resolved vocab: garlic, onion, kale, tomato, butternut squash, olive oil, salt,
               black pepper, vegetable broth, onion
Seeded pantry: garlic (expires tomorrow) + kale (expires today = error-container chip)
Canned recipes: two realistic RecipeNLG-shaped ranked results for screenshot testing.
"""
from __future__ import annotations

import asyncio
import os
from datetime import date, timedelta
from pathlib import Path

import uvicorn
from fastapi import FastAPI, HTTPException, Request
from fastapi.middleware.cors import CORSMiddleware
from fastapi.staticfiles import StaticFiles

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
# In-memory pantry (seeded)
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

PANTRY: list[dict] = [
    {
        "canonical_name": "garlic",
        "raw_text": "garlic",
        "expires_at": TOMORROW,
    },
    {
        "canonical_name": "kale",
        "raw_text": "wilting kale",
        "expires_at": TODAY,
    },
]

# ---------------------------------------------------------------------------
# Routes
# ---------------------------------------------------------------------------

@app.get("/navigator/pantry")
def get_pantry():
    return PANTRY

@app.put("/navigator/pantry")
async def put_pantry(request: Request):
    body = await request.json()
    PANTRY.clear()
    PANTRY.extend(body)
    return PANTRY

@app.post("/navigator/pantry/items", status_code=201)
async def post_pantry_item(request: Request):
    body = await request.json()
    raw = body.get("raw_text", "").strip().lower()
    canonical = VOCAB.get(raw)
    if not canonical:
        raise HTTPException(status_code=422, detail=f"Cannot resolve '{raw}'")
    item = {"canonical_name": canonical, "raw_text": raw}
    # Remove if already present, then add
    PANTRY[:] = [it for it in PANTRY if it["canonical_name"] != canonical]
    PANTRY.append(item)
    return {"canonical_name": canonical, "raw_text": raw}

@app.delete("/navigator/pantry/items/{name}")
def delete_pantry_item(name: str):
    PANTRY[:] = [it for it in PANTRY if it["canonical_name"] != name]
    return {"removed": name}

@app.post("/navigator/pantry/resolve")
async def post_resolve(request: Request):
    body = await request.json()
    raw = body.get("raw", "").strip().lower()
    canonical = VOCAB.get(raw)
    if not canonical:
        raise HTTPException(status_code=404, detail=f"Cannot resolve '{raw}'")
    return {"canonical_name": canonical}

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

    pantry_names = {it["canonical_name"] for it in PANTRY}
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
        pantry_names = {it["canonical_name"] for it in PANTRY}
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
    pantry_names = {it["canonical_name"] for it in PANTRY}
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


# /navigator/vision/parse-shelf → 404 (T-014 not yet built)
@app.post("/navigator/vision/parse-shelf")
async def parse_shelf():
    raise HTTPException(status_code=404, detail="Vision endpoint not yet available")

@app.get("/navigator/health")
def health():
    return {"status": "ok", "recipe_count": 0}

# Serve the built PWA from the same origin (so no dev proxy is needed for
# screenshots). Mounted last so the explicit /navigator/* routes win.
_DIST = Path(__file__).parent / "dist"
if _DIST.exists():
    app.mount("/", StaticFiles(directory=str(_DIST), html=True), name="dist")

if __name__ == "__main__":
    uvicorn.run(app, host="127.0.0.1", port=8099, log_level="warning")
