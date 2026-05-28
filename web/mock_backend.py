"""
Minimal mock backend for T-007 screenshot testing.
Implements the pantry routes with canned responses.

Resolved vocab: garlic, onion, kale, tomato, butternut squash
Seeded pantry: garlic (no expiry) + kale (expires today = error-container chip)
"""
from __future__ import annotations
import json
from datetime import date, timedelta
from pathlib import Path
import uvicorn
from fastapi import FastAPI, HTTPException, Request
from fastapi.responses import JSONResponse
from fastapi.middleware.cors import CORSMiddleware

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

# /navigator/vision/parse-shelf → 404 (T-014 not yet built)
@app.post("/navigator/vision/parse-shelf")
async def parse_shelf():
    raise HTTPException(status_code=404, detail="Vision endpoint not yet available")

@app.get("/navigator/health")
def health():
    return {"status": "ok", "recipe_count": 0}

if __name__ == "__main__":
    uvicorn.run(app, host="127.0.0.1", port=8099, log_level="warning")
