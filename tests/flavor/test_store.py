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


def test_cohesion(fs: FlavorStore):
    assert fs.cohesion(["garlic"]) is None  # <2 mapped → None
    assert fs.cohesion(["xyzzy", "qwerty"]) is None  # 0 mapped → None
    c = fs.cohesion(["garlic", "onion", "tomato"])
    assert c is not None and 0.0 <= c <= 1.0


def test_affinity_excludes_pantry_and_equal(fs: FlavorStore):
    # A recipe whose only mapped entities are already in the pantry → None
    assert fs.affinity(["garlic", "onion"], ["garlic", "onion"]) is None
    # Empty pantry → None
    assert fs.affinity(["garlic", "onion"], []) is None
    # Non-pantry recipe entities vs pantry → defined, in [0,1]
    a = fs.affinity(["basil", "tomato"], ["garlic", "onion"])
    assert a is not None and 0.0 <= a <= 1.0


def test_flavor_score_blend(fs: FlavorStore):
    # both None → 0.0
    assert fs.flavor_score(["xyzzy"], []) == 0.0
    # cohesion present, affinity None (empty pantry) → equals cohesion
    coh = fs.cohesion(["garlic", "onion", "tomato"])
    assert fs.flavor_score(["garlic", "onion", "tomato"], []) == pytest.approx(coh)
    # both present → 0.5/0.5 blend
    phrases = ["basil", "tomato", "oregano"]
    pantry = ["garlic", "onion"]
    coh2 = fs.cohesion(phrases)
    aff2 = fs.affinity(phrases, pantry)
    assert coh2 is not None and aff2 is not None
    assert fs.flavor_score(phrases, pantry) == pytest.approx(0.5 * coh2 + 0.5 * aff2)
