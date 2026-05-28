"""Tests for RecipeStore — basic upsert/get/query/delete round-trip."""

from __future__ import annotations

import numpy as np
import pytest

from pantryatlas.store.recipes import Recipe, RecipeStore


def _unit_vec(seed: int = 0) -> np.ndarray:
    rng = np.random.default_rng(seed)
    v = rng.standard_normal(1024).astype(np.float32)
    v /= np.linalg.norm(v)
    return v


def _make_recipes(n: int) -> list[Recipe]:
    return [
        Recipe(
            id=f"recipe_{i}",
            title=f"Recipe {i}",
            language="en",
            embedding=_unit_vec(i),
        )
        for i in range(n)
    ]


class TestRecipeStoreRoundTrip:
    def test_upsert_and_get(self, tmp_path: pytest.TempdirFactory) -> None:
        db = tmp_path / "recipes.db"
        recipe = Recipe(
            id="pasta_carbonara",
            title="Pasta Carbonara",
            language="it",
            embedding=_unit_vec(1),
            ingredients_json=["pasta", "eggs", "guanciale"],
            instructions="Boil pasta. Make sauce. Combine.",
        )
        with RecipeStore(db) as store:
            store.upsert([recipe])
            result = store.get("pasta_carbonara")

        assert result is not None
        assert result.title == "Pasta Carbonara"
        assert result.language == "it"
        assert result.ingredients_json == ["pasta", "eggs", "guanciale"]
        assert result.instructions == "Boil pasta. Make sauce. Combine."
        np.testing.assert_array_almost_equal(result.embedding, recipe.embedding)

    def test_get_missing_returns_none(self, tmp_path: pytest.TempdirFactory) -> None:
        db = tmp_path / "recipes.db"
        with RecipeStore(db) as store:
            assert store.get("does_not_exist") is None

    def test_query_by_vector_top_hit(self, tmp_path: pytest.TempdirFactory) -> None:
        db = tmp_path / "recipes.db"
        rows = _make_recipes(5)
        with RecipeStore(db) as store:
            store.upsert(rows)
            results = store.query_by_vector(rows[2].embedding, top_k=5)
        assert len(results) >= 1
        assert results[0].id == rows[2].id

    def test_delete(self, tmp_path: pytest.TempdirFactory) -> None:
        db = tmp_path / "recipes.db"
        rows = _make_recipes(3)
        with RecipeStore(db) as store:
            store.upsert(rows)
            store.delete(rows[1].id)
            assert store.get(rows[1].id) is None
            assert store.get(rows[0].id) is not None

    def test_upsert_overwrite(self, tmp_path: pytest.TempdirFactory) -> None:
        db = tmp_path / "recipes.db"
        r = Recipe(id="r1", title="old", language="en", embedding=_unit_vec(0))
        r2 = Recipe(id="r1", title="new", language="fr", embedding=_unit_vec(1))
        with RecipeStore(db) as store:
            store.upsert([r])
            store.upsert([r2])
            result = store.get("r1")
        assert result is not None
        assert result.title == "new"
        assert result.language == "fr"

    def test_persist_across_reopen(self, tmp_path: pytest.TempdirFactory) -> None:
        db = tmp_path / "recipes.db"
        rows = _make_recipes(5)

        store = RecipeStore(db)
        store.upsert(rows)
        store.close()

        store2 = RecipeStore(db)
        results = store2.query_by_vector(rows[0].embedding, top_k=5)
        store2.close()

        assert len(results) >= 1
        assert results[0].id == rows[0].id
