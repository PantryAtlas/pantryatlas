"""End-to-end integration test for the navigator instant→refine→swaps flow.

Marked pi_integration — only runs when PANTRYATLAS_PI_INTEGRATION=1 against a
bootstrapped Pi 5 with the real recipe DB (~/.pantryatlas/recipes.db, built by
``python -m pantryatlas.navigator.ingest``) and the bge-m3 ONNX embedder.

Exercises the full agentic loop end-to-end via the in-process ASGI app:

  1. INSTANT  — POST /recipes/from-pantry returns coverage-ranked results with
                RecipeNLG source attribution, no embedding (fast).
  2. REFINE   — POST /recipes/from-pantry/refine recomputes real substitution
                penalties; at least one result becomes non-zero. Timed < 10s.
  3. SWAPS    — POST /recipes/swaps returns per-missing swap suggestions.

Isolation: ``app.state.kitchen`` is set to a ``KitchenStore`` backed by a
``tmp_path`` SQLite file before any route is hit.  ``_get_kitchen`` returns
``app.state.kitchen`` immediately when it is not None, so the production
factory — which would open ``~/.pantryatlas/kitchen.db`` — is never invoked.
The operator's real kitchen database is never touched.
"""

from __future__ import annotations

import asyncio
import time
from pathlib import Path

import pytest
from httpx import ASGITransport, AsyncClient

from pantryatlas.navigator.server import app
from pantryatlas.store.kitchen import KitchenStore

PANTRY_ITEMS = [
    {"canonical_name": "sugar", "raw_text": "sugar"},
    {"canonical_name": "salt", "raw_text": "salt"},
    {"canonical_name": "eggs", "raw_text": "eggs"},
    {"canonical_name": "flour", "raw_text": "flour"},
    {"canonical_name": "butter", "raw_text": "butter"},
]


@pytest.mark.pi_integration
def test_navigator_e2e(tmp_path: Path) -> None:
    """Instant → refine → swaps against the real recipe DB and embedder."""
    # Isolate from the operator's real kitchen.db.  _get_kitchen() returns
    # app.state.kitchen immediately when it is not None, so the production
    # factory (which would open ~/.pantryatlas/kitchen.db) is never invoked.
    app.state.kitchen = KitchenStore(tmp_path / "kitchen.db")
    # Keep the legacy pantry_path guard as belt-and-suspenders.
    app.state.pantry_path = tmp_path / "pantry.json"

    # Warm the ONNX embedder OUTSIDE the timed window so we measure the refine
    # work, not the one-time model cold-load.
    from pantryatlas.embeddings import embed

    embed(["warmup"])

    asyncio.run(_run_flow())


async def _run_flow() -> None:
    transport = ASGITransport(app=app)
    async with AsyncClient(transport=transport, base_url="http://e2e") as client:
        # Sanity: the real recipe store is loaded with a substantial corpus.
        health = await client.get("/navigator/health")
        assert health.status_code == 200
        recipe_count = health.json()["recipe_count"]
        assert recipe_count > 1000, f"store has only {recipe_count} recipes"

        # Seed a 5-item pantry of common staples (high real-recipe overlap).
        put = await client.put("/navigator/pantry", json=PANTRY_ITEMS)
        assert put.status_code == 200

        # --- 1. INSTANT (coverage-ranked, fast, no embedding) ---
        t0 = time.perf_counter()
        instant_resp = await client.post("/navigator/recipes/from-pantry")
        instant_seconds = time.perf_counter() - t0
        assert instant_resp.status_code == 200
        instant = instant_resp.json()
        assert len(instant) >= 1
        # License compliance: every result carries source attribution.
        assert "RecipeNLG" in instant[0]["source"]
        # Fast mode contributes a constant optimistic substitution penalty of 0.
        assert all(r["substitution_penalty"] == 0.0 for r in instant)
        # At least one result is genuinely cookable (coverage > 0.4).
        assert any(r["coverage"] > 0.4 for r in instant)
        print(f"navigator_e2e_instant_seconds={instant_seconds:.3f}")
        assert instant_seconds < 5.0

        # --- 2. REFINE (real substitution penalties; timed < 10s) ---
        top = [r["recipe"] for r in instant[:20]]
        t1 = time.perf_counter()
        refine_resp = await client.post("/navigator/recipes/from-pantry/refine", json=top)
        refine_seconds = time.perf_counter() - t1
        assert refine_resp.status_code == 200
        refined = refine_resp.json()
        assert len(refined) == len(top)
        assert all("RecipeNLG" in r["source"] for r in refined)
        # Refining must produce a real (non-zero) substitution penalty somewhere.
        assert any(r["substitution_penalty"] > 0.0 for r in refined)
        print(f"navigator_e2e_runtime_seconds={refine_seconds:.3f}")
        assert refine_seconds < 10.0

        # --- 3. SWAPS (per-missing suggestions for an expanded card) ---
        with_missing = next((r for r in refined if r["missing"]), None)
        assert with_missing is not None, "expected at least one recipe with missing items"
        swaps_resp = await client.post(
            "/navigator/recipes/swaps",
            json={"ingredients": with_missing["recipe"]["ingredients"]},
        )
        assert swaps_resp.status_code == 200
        swaps = swaps_resp.json()["swaps"]
        assert len(swaps) >= 1
        for s in swaps:
            assert set(s.keys()) == {"missing", "best_swap", "similarity", "reason"}
            assert 0.0 <= s["similarity"] <= 1.0
            assert (s["best_swap"] is None) == (s["reason"] is not None)
