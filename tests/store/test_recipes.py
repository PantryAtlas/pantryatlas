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


def _near_vec(base: np.ndarray, seed: int, eps: float = 0.01) -> np.ndarray:
    """A unit vector very close to ``base`` (small distance)."""
    rng = np.random.default_rng(seed)
    v = base + eps * rng.standard_normal(1024).astype(np.float32)
    return (v / np.linalg.norm(v)).astype(np.float32)


class TestRecipeStoreFilters:
    def test_filter_by_language(self, tmp_path: pytest.TempdirFactory) -> None:
        db = tmp_path / "recipes.db"
        rows = [
            Recipe(id="en0", title="A", language="en", embedding=_unit_vec(0)),
            Recipe(id="es0", title="B", language="es", embedding=_unit_vec(1)),
            Recipe(id="es1", title="C", language="es", embedding=_unit_vec(2)),
        ]
        with RecipeStore(db) as store:
            store.upsert(rows)
            results = store.query_by_vector(
                _unit_vec(0), top_k=5, filters={"language": "es"}
            )
        assert {r.language for r in results} == {"es"}
        assert "en0" not in {r.id for r in results}

    def test_filter_excludes_nearest_row(self, tmp_path: pytest.TempdirFactory) -> None:
        # The query vector IS en0's embedding, so en0 is the nearest by distance.
        # Filtering to 'es' must exclude it and still return the es rows — the
        # case a naive `LIMIT top_k` (no over-fetch) would silently under-return.
        db = tmp_path / "recipes.db"
        rows = [
            Recipe(id="en0", title="A", language="en", embedding=_unit_vec(0)),
            Recipe(id="es0", title="B", language="es", embedding=_unit_vec(1)),
            Recipe(id="es1", title="C", language="es", embedding=_unit_vec(2)),
        ]
        with RecipeStore(db) as store:
            store.upsert(rows)
            results = store.query_by_vector(
                rows[0].embedding, top_k=2, filters={"language": "es"}
            )
        ids = {r.id for r in results}
        assert "en0" not in ids
        assert ids == {"es0", "es1"}

    def test_filter_widens_pool_past_initial_limit(
        self, tmp_path: pytest.TempdirFactory
    ) -> None:
        # 70 'en' rows clustered tight around the query (nearest), plus 3 far 'es'
        # rows. The initial KNN pool (64) is all 'en' → 0 'es' matches → the
        # widening loop must grow the pool until the 'es' rows are found.
        db = tmp_path / "recipes.db"
        base = _unit_vec(999)
        rows = [
            Recipe(id=f"en{i}", title="x", language="en", embedding=_near_vec(base, i))
            for i in range(70)
        ]
        rows += [
            Recipe(id=f"es{j}", title="y", language="es", embedding=_unit_vec(1000 + j))
            for j in range(3)
        ]
        with RecipeStore(db) as store:
            store.upsert(rows)
            results = store.query_by_vector(base, top_k=3, filters={"language": "es"})
        assert len(results) == 3
        assert {r.language for r in results} == {"es"}

    def test_empty_filter_is_unfiltered(self, tmp_path: pytest.TempdirFactory) -> None:
        db = tmp_path / "recipes.db"
        rows = _make_recipes(5)
        with RecipeStore(db) as store:
            store.upsert(rows)
            r_none = store.query_by_vector(rows[2].embedding, top_k=5, filters=None)
            r_empty = store.query_by_vector(rows[2].embedding, top_k=5, filters={})
        assert r_none[0].id == rows[2].id
        assert r_empty[0].id == rows[2].id

    def test_unknown_filter_key_raises(self, tmp_path: pytest.TempdirFactory) -> None:
        db = tmp_path / "recipes.db"
        with RecipeStore(db) as store:
            store.upsert(_make_recipes(2))
            with pytest.raises(ValueError, match="unsupported filter keys"):
                store.query_by_vector(_unit_vec(0), filters={"cuisine": "italian"})

    def test_non_string_filter_value_raises(
        self, tmp_path: pytest.TempdirFactory
    ) -> None:
        db = tmp_path / "recipes.db"
        with RecipeStore(db) as store:
            store.upsert(_make_recipes(2))
            with pytest.raises(ValueError, match="must be a string scalar"):
                store.query_by_vector(_unit_vec(0), filters={"language": ["en", "es"]})
