from __future__ import annotations

from pathlib import Path

import pytest

from pantryatlas.flavor.store import FlavorStore

PARQUET = Path(__file__).resolve().parents[2] / "pantryatlas" / "data" / "compounds.parquet"


@pytest.fixture(scope="module")
def fs() -> FlavorStore:
    return FlavorStore(PARQUET)


def _name(fs: FlavorStore, phrase: str) -> str | None:
    eid = fs.entity_for(phrase)
    return fs.entity_name(eid) if eid is not None else None


def test_matcher_precision(fs: FlavorStore):
    # exact + multiword (longest wins)
    assert _name(fs, "garlic") == "Garlic"
    assert _name(fs, "cream cheese") == "Cream Cheese"
    assert _name(fs, "sweet potato") == "Sweet Potato"
    assert _name(fs, "peanut butter") == "Peanut Butter"
    # generic head-noun → modifier wins
    assert _name(fs, "coconut milk") == "Coconut"
    assert _name(fs, "almond milk") == "Almond"
    assert _name(fs, "almond butter") == "Almond"
    # head-noun for noisy phrases
    assert _name(fs, "ribs celery") == "Celery"
    assert _name(fs, "red onion") == "Onion"
    assert _name(fs, "ground beef") == "Beef"
    # blocklist / non-foods → None
    assert fs.entity_for("baking soda") is None
    assert fs.entity_for("cream of tartar") is None
    # unmappable → None
    assert fs.entity_for("xyzzy widget") is None


def test_jaccard(fs: FlavorStore):
    g = fs.entity_for("garlic")
    o = fs.entity_for("onion")
    assert fs.jaccard(g, g) == 1.0
    j = fs.jaccard(g, o)
    assert 0.0 <= j <= 1.0
    assert fs.jaccard(g, o) == fs.jaccard(o, g)  # symmetric + cached
