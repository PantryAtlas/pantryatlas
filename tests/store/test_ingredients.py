"""Tests for IngredientStore (AC-4, AC-5, AC-6)."""

from __future__ import annotations

import numpy as np
import pytest

from pantryatlas.store.ingredients import Ingredient, IngredientStore


def _make_unit_vec(seed: int | None = None) -> np.ndarray:
    rng = np.random.default_rng(seed)
    vec = rng.standard_normal(1024).astype(np.float32)
    vec /= np.linalg.norm(vec)
    return vec


def _make_ingredients(n: int) -> list[Ingredient]:
    return [
        Ingredient(
            id=f"ing_{i}",
            canonical_name=f"ingredient_{i}",
            language="en",
            embedding=_make_unit_vec(i),
        )
        for i in range(n)
    ]


class TestIngredientStoreBasic:
    """AC-4: upsert 5 rows, query, assert top hit matches first row."""

    def test_upsert_and_query_top_hit(self, tmp_path: pytest.TempdirFactory) -> None:
        db = tmp_path / "ingredients.db"
        rows = _make_ingredients(5)

        with IngredientStore(db) as store:
            store.upsert(rows)
            results = store.query_by_vector(rows[0].embedding, top_k=5)

        assert len(results) >= 1
        assert results[0].id == rows[0].id

    def test_upsert_metadata_roundtrip(self, tmp_path: pytest.TempdirFactory) -> None:
        db = tmp_path / "ingredients.db"
        ing = Ingredient(
            id="garlic_en",
            canonical_name="garlic",
            language="en",
            embedding=_make_unit_vec(42),
            aliases=["ajo", "Knoblauch"],
            source="manual",
        )
        with IngredientStore(db) as store:
            store.upsert([ing])
            result = store.get("garlic_en")

        assert result is not None
        assert result.canonical_name == "garlic"
        assert result.language == "en"
        assert result.aliases == ["ajo", "Knoblauch"]
        assert result.source == "manual"
        np.testing.assert_array_almost_equal(result.embedding, ing.embedding)

    def test_get_missing_returns_none(self, tmp_path: pytest.TempdirFactory) -> None:
        db = tmp_path / "ingredients.db"
        with IngredientStore(db) as store:
            assert store.get("nonexistent") is None

    def test_delete(self, tmp_path: pytest.TempdirFactory) -> None:
        db = tmp_path / "ingredients.db"
        rows = _make_ingredients(3)
        with IngredientStore(db) as store:
            store.upsert(rows)
            store.delete(rows[0].id)
            assert store.get(rows[0].id) is None
            assert store.get(rows[1].id) is not None

    def test_upsert_is_idempotent(self, tmp_path: pytest.TempdirFactory) -> None:
        db = tmp_path / "ingredients.db"
        ing = Ingredient(
            id="tomato",
            canonical_name="tomato",
            language="en",
            embedding=_make_unit_vec(7),
        )
        updated = Ingredient(
            id="tomato",
            canonical_name="tomato (updated)",
            language="fr",
            embedding=_make_unit_vec(8),
        )
        with IngredientStore(db) as store:
            store.upsert([ing])
            store.upsert([updated])
            result = store.get("tomato")

        assert result is not None
        assert result.canonical_name == "tomato (updated)"
        assert result.language == "fr"

    def test_query_returns_sorted_by_distance(self, tmp_path: pytest.TempdirFactory) -> None:
        db = tmp_path / "ingredients.db"
        rows = _make_ingredients(5)
        with IngredientStore(db) as store:
            store.upsert(rows)
            results = store.query_by_vector(rows[2].embedding, top_k=5)
        assert results[0].id == rows[2].id


class TestIngredientStorePersistence:
    """AC-5: close + reopen, data must persist."""

    def test_close_reopen_persists_data(self, tmp_path: pytest.TempdirFactory) -> None:
        db = tmp_path / "ingredients.db"
        rows = _make_ingredients(5)

        store = IngredientStore(db)
        store.upsert(rows)
        store.close()

        store2 = IngredientStore(db)
        results = store2.query_by_vector(rows[0].embedding, top_k=5)
        store2.close()

        assert len(results) >= 1
        assert results[0].id == rows[0].id

    def test_context_manager_persistence(self, tmp_path: pytest.TempdirFactory) -> None:
        db = tmp_path / "ingredients.db"
        rows = _make_ingredients(5)

        with IngredientStore(db) as store:
            store.upsert(rows)

        with IngredientStore(db) as store2:
            fetched = store2.get(rows[3].id)

        assert fetched is not None
        assert fetched.id == rows[3].id


class TestIngredientStoreFilters:
    """query_by_vector metadata filtering (language, source)."""

    def test_filter_by_language(self, tmp_path: pytest.TempdirFactory) -> None:
        db = tmp_path / "ingredients.db"
        rows = [
            Ingredient(id="en", canonical_name="garlic", language="en",
                       embedding=_make_unit_vec(0)),
            Ingredient(id="es", canonical_name="ajo", language="es",
                       embedding=_make_unit_vec(1)),
        ]
        with IngredientStore(db) as store:
            store.upsert(rows)
            results = store.query_by_vector(
                rows[0].embedding, top_k=5, filters={"language": "es"}
            )
        assert {r.id for r in results} == {"es"}

    def test_filter_by_source(self, tmp_path: pytest.TempdirFactory) -> None:
        db = tmp_path / "ingredients.db"
        rows = [
            Ingredient(id="a", canonical_name="x", language="en",
                       embedding=_make_unit_vec(0), source="manual"),
            Ingredient(id="b", canonical_name="y", language="en",
                       embedding=_make_unit_vec(1), source="recipenlg"),
        ]
        with IngredientStore(db) as store:
            store.upsert(rows)
            results = store.query_by_vector(
                _make_unit_vec(0), top_k=5, filters={"source": "recipenlg"}
            )
        assert {r.id for r in results} == {"b"}

    def test_unknown_filter_key_raises(self, tmp_path: pytest.TempdirFactory) -> None:
        db = tmp_path / "ingredients.db"
        with IngredientStore(db) as store:
            store.upsert(_make_ingredients(2))
            with pytest.raises(ValueError, match="unsupported filter keys"):
                store.query_by_vector(_make_unit_vec(0), filters={"title": "x"})

    def test_non_string_filter_value_raises(
        self, tmp_path: pytest.TempdirFactory
    ) -> None:
        db = tmp_path / "ingredients.db"
        with IngredientStore(db) as store:
            store.upsert(_make_ingredients(2))
            with pytest.raises(ValueError, match="must be a string scalar"):
                store.query_by_vector(_make_unit_vec(0), filters={"language": 3})


class TestIngredientStoreSize:
    """AC-6: 1500 rows must stay under 500 MB."""

    def test_size_under_500mb(self, tmp_path: pytest.TempdirFactory) -> None:
        db = tmp_path / "ingredients.db"
        store = IngredientStore(db)
        rows = []
        rng = np.random.default_rng(0)
        for i in range(1500):
            vec = rng.standard_normal(1024).astype(np.float32)
            vec /= np.linalg.norm(vec)
            rows.append(
                Ingredient(
                    id=f"i_{i}",
                    canonical_name=f"ing_{i}",
                    language="en",
                    embedding=vec,
                )
            )
        store.upsert(rows)
        store.close()

        size = db.stat().st_size
        assert size < 500 * 1024 * 1024, (
            f"DB file too large: {size / (1024 * 1024):.1f} MB >= 500 MB"
        )
