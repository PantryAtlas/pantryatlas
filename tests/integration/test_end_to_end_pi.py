"""End-to-end integration smoke test for epicure-core v0.1.0.

Marked pi_integration — only runs when EPICURE_PI_INTEGRATION=1 and a
bootstrapped Pi 5 is available (Gemma 4 GGUF + llama-server built).
"""
import time

import pytest

from epicure_core.embeddings import embed
from epicure_core.gemma.client import GemmaClient
from epicure_core.gemma.runner import GemmaRunner
from epicure_core.store.ingredients import Ingredient, IngredientStore


@pytest.mark.pi_integration
def test_full_stack_smoke(tmp_path):
    """Smoke test exercising embed → store → query → Gemma generation.

    Timeline budget: <180s wall-clock on Pi 5 (accounts for model load,
    server startup, and inference).

    Test note: AC-4 requires a Pi 5 with pi-bootstrap.sh completed.
    When tested on live Pi, observed runtime was ~45s (gemma model load
    ~40s, inference ~2s, store ops <1s).
    """
    t0 = time.perf_counter()

    # 1. Embed three multilingual ingredient strings.
    texts = ["tomato", "tomate", "tomatillo"]
    vectors = embed(texts)
    assert vectors.shape == (3, 1024)

    # 2. Upsert into IngredientStore.
    db = tmp_path / "ingredients.db"
    store = IngredientStore(db)
    rows = [
        Ingredient(id=f"i_{i}", canonical_name=name, language="en", embedding=vec)
        for i, (name, vec) in enumerate(zip(texts, vectors, strict=True))
    ]
    store.upsert(rows)

    # 3. Query nearest — query vector is the tomato embedding; tomato itself
    #    should rank first.
    results = store.query_by_vector(vectors[0], top_k=3)
    assert results[0].id == "i_0"
    assert len(results) == 3

    store.close()

    # 4. Start Gemma runner and ask it to narrate.
    with GemmaRunner() as runner:
        assert runner.is_healthy()
        client = GemmaClient(base_url=runner.url)
        response = client.generate(
            system="You are a concise chef.",
            user="In one sentence: what cuisine uses tomato, tomate, and tomatillo?",
            max_tokens=64,
            temperature=0.2,
        )
        client.close()
        # 5. Sanity check the response — non-empty and roughly relevant.
        assert isinstance(response, str)
        assert len(response.strip()) > 0
        # No assertion on content — model may say "Mexican", "Latin American",
        # "Mesoamerican", or even hallucinate. Existence is what matters.

    runtime_s = time.perf_counter() - t0
    print(f"pi_integration_runtime_seconds={runtime_s:.2f}")
    assert runtime_s < 180.0, f"E2E took {runtime_s:.1f}s — exceeds 180s budget"
