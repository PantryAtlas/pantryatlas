"""Tests for ModeStore — verifies class exists with the magic docstring (AC-7)."""

from __future__ import annotations

import numpy as np
import pytest

from pantryatlas.store.modes import Mode, ModeStore


def _unit_vec(seed: int = 0) -> np.ndarray:
    rng = np.random.default_rng(seed)
    v = rng.standard_normal(1024).astype(np.float32)
    v /= np.linalg.norm(v)
    return v


class TestModeStoreDocstring:
    """AC-7: ModeStore docstring must contain 'schema reserved for v0.2'."""

    def test_docstring_contains_magic_phrase(self) -> None:
        assert ModeStore.__doc__ is not None
        assert "schema reserved for v0.2" in ModeStore.__doc__


class TestModeStoreApi:
    """ModeStore exposes the full CRUD API even though v0.1 does not insert."""

    def test_has_required_methods(self) -> None:
        for method in ("upsert", "get", "query_by_vector", "delete", "close"):
            assert hasattr(ModeStore, method), f"ModeStore missing method: {method}"

    def test_creates_tables_idempotent(self, tmp_path: pytest.TempdirFactory) -> None:
        db = tmp_path / "modes.db"
        # Opening twice must not raise
        with ModeStore(db):
            pass
        with ModeStore(db):
            pass

    def test_upsert_get_delete(self, tmp_path: pytest.TempdirFactory) -> None:
        db = tmp_path / "modes.db"
        mode = Mode(
            id="umami",
            label_en="Umami",
            embedding=_unit_vec(99),
            label_local="旨み",
            top_members=["soy_sauce", "parmesan"],
        )
        with ModeStore(db) as store:
            store.upsert([mode])
            result = store.get("umami")

        assert result is not None
        assert result.label_en == "Umami"
        assert result.label_local == "旨み"
        assert result.top_members == ["soy_sauce", "parmesan"]

    def test_query_by_vector(self, tmp_path: pytest.TempdirFactory) -> None:
        db = tmp_path / "modes.db"
        modes = [
            Mode(id=f"m_{i}", label_en=f"mode_{i}", embedding=_unit_vec(i))
            for i in range(4)
        ]
        with ModeStore(db) as store:
            store.upsert(modes)
            results = store.query_by_vector(modes[1].embedding, top_k=4)
        assert len(results) >= 1
        assert results[0].id == modes[1].id

    def test_delete(self, tmp_path: pytest.TempdirFactory) -> None:
        db = tmp_path / "modes.db"
        mode = Mode(id="sour", label_en="Sour", embedding=_unit_vec(5))
        with ModeStore(db) as store:
            store.upsert([mode])
            store.delete("sour")
            assert store.get("sour") is None

    def test_persist_across_reopen(self, tmp_path: pytest.TempdirFactory) -> None:
        db = tmp_path / "modes.db"
        mode = Mode(id="sweet", label_en="Sweet", embedding=_unit_vec(10))

        store = ModeStore(db)
        store.upsert([mode])
        store.close()

        store2 = ModeStore(db)
        result = store2.get("sweet")
        store2.close()

        assert result is not None
        assert result.label_en == "Sweet"
