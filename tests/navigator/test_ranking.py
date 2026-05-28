"""Tests for pantryatlas.navigator.ranking module.

TDD: tests written first, then implementation.

All tests use an injected fake embed_fn — no bge-m3 ONNX model required.
"""

from __future__ import annotations

from datetime import date, timedelta

import numpy as np
import pytest

from pantryatlas.navigator.ranking import RankedRecipe, rank_recipes
from pantryatlas.pantry.models import Ingredient, Pantry, Quantity


# ---------------------------------------------------------------------------
# Helpers / fixtures
# ---------------------------------------------------------------------------


def _make_pantry(*names: str, expires: dict[str, date] | None = None) -> Pantry:
    """Build a Pantry from a sequence of canonical names.

    Args:
        *names: Canonical ingredient names.
        expires: Optional mapping from canonical_name → expires_at date.
    """
    p = Pantry()
    for name in names:
        exp = expires.get(name) if expires else None
        p.add(Ingredient(canonical_name=name, raw_text=name, expires_at=exp))
    return p


def _recipe(title: str, *ingredients: str) -> dict:
    """Build a minimal recipe dict compatible with ingest.parse_recipe output."""
    return {"title": title, "ingredients": list(ingredients), "instructions": "cook it"}


def _identity_embed(texts: list[str]) -> np.ndarray:
    """Fake embed_fn that creates unique deterministic unit vectors.

    Each text gets a unique 8-dim unit vector based on a simple hash,
    so distinct texts have low cosine similarity while identical texts
    have cosine=1. This is the default fake for most tests.
    """
    dim = 8
    vecs = []
    for text in texts:
        # Seed with hash of text for determinism
        rng = np.random.default_rng(abs(hash(text)) % (2**31))
        v = rng.standard_normal(dim).astype(np.float32)
        v = v / np.linalg.norm(v)
        vecs.append(v)
    return np.array(vecs, dtype=np.float32)


def _fixed_embed(mapping: dict[str, np.ndarray]):
    """Return an embed_fn that maps known texts to fixed vectors.

    Texts not in mapping get random vectors via _identity_embed.
    """
    def embed_fn(texts: list[str]) -> np.ndarray:
        dim = next(iter(mapping.values())).shape[0]
        result = np.zeros((len(texts), dim), dtype=np.float32)
        for i, t in enumerate(texts):
            if t in mapping:
                v = mapping[t].astype(np.float32)
                norm = np.linalg.norm(v)
                result[i] = v / norm if norm > 0 else v
            else:
                # Fallback: unique random unit vector
                rng = np.random.default_rng(abs(hash(t)) % (2**31))
                v = rng.standard_normal(dim).astype(np.float32)
                result[i] = v / np.linalg.norm(v)
        return result

    return embed_fn


# ---------------------------------------------------------------------------
# AC-1: file exists and imports work
# AC-2: tested by the import at the top of this file — if import fails, all tests fail
# ---------------------------------------------------------------------------


def test_import_exports_exist():
    """Confirm rank_recipes and RankedRecipe are importable."""
    assert callable(rank_recipes)
    assert RankedRecipe is not None


# ---------------------------------------------------------------------------
# AC-3 + AC-4: perfect match recipe → score ≈ 0.70
# ---------------------------------------------------------------------------


def test_perfect_coverage_score():
    """AC-4: pantry == recipe ingredients → score ≈ 0.70.

    score = 0.50*1.0 + 0.20*0 + 0.20*1.0 + 0.10*0 = 0.70
    - coverage = 1.0 (all 5 ingredients present)
    - expiration_urgency = 0 (no expires_at set on any pantry item)
    - substitution_penalty = 0 (no missing ingredients) → (1 - 0) = 1.0
    - cultural_fit = 0 (no cuisine filter)
    """
    pantry = _make_pantry("garlic", "tomato", "basil", "olive oil", "pasta")
    recipe = _recipe("Pasta al Pomodoro", "garlic", "tomato", "basil", "olive oil", "pasta")

    results = rank_recipes(pantry, [recipe], embed_fn=_identity_embed)

    assert len(results) == 1
    r = results[0]
    assert isinstance(r, RankedRecipe)
    assert abs(r.score - 0.70) < 1e-6
    assert abs(r.coverage - 1.0) < 1e-6
    assert r.missing == []
    assert abs(r.expiration_urgency - 0.0) < 1e-6
    assert abs(r.substitution_penalty - 0.0) < 1e-6
    assert abs(r.cultural_fit - 0.0) < 1e-6


# ---------------------------------------------------------------------------
# AC-5: partial coverage → correct coverage fraction + missing list
# ---------------------------------------------------------------------------


def test_partial_coverage_missing():
    """AC-5: pantry={garlic,tomato} + recipe={garlic,tomato,basil} → coverage=2/3, missing=['basil']."""
    pantry = _make_pantry("garlic", "tomato")
    recipe = _recipe("Simple Sauce", "garlic", "tomato", "basil")

    results = rank_recipes(pantry, [recipe], embed_fn=_identity_embed)

    assert len(results) == 1
    r = results[0]
    assert abs(r.coverage - 2 / 3) < 1e-6
    assert r.missing == ["basil"]


# ---------------------------------------------------------------------------
# AC-6: expiring items → recipe consuming them ranks higher
# ---------------------------------------------------------------------------


def test_expiration_urgency_ranking():
    """AC-6: two recipes with equal coverage; consuming an expiring item raises rank.

    recipe_a consumes 'milk' which expires tomorrow → higher urgency → higher score.
    recipe_b does not use 'milk' → urgency = 0.
    """
    tomorrow = date.today() + timedelta(days=1)
    pantry = _make_pantry(
        "flour", "egg", "milk", "butter",
        expires={"milk": tomorrow},
    )

    recipe_a = _recipe("Pancakes", "flour", "egg", "milk", "butter")   # uses expiring milk
    recipe_b = _recipe("Shortbread", "flour", "egg", "butter")         # same coverage ratio: 3/3 = 1.0

    # recipe_b has 3 ingredients all present → coverage=1.0
    # recipe_a has 4 ingredients all present → coverage=1.0
    # urgency for recipe_a > 0 (milk is expiring)
    # urgency for recipe_b = 0 (no expiring ingredient used)

    results = rank_recipes(pantry, [recipe_a, recipe_b], embed_fn=_identity_embed)

    # Both rank, but recipe_a should be strictly higher
    assert len(results) == 2
    a_result = next(r for r in results if r.recipe["title"] == "Pancakes")
    b_result = next(r for r in results if r.recipe["title"] == "Shortbread")

    assert a_result.expiration_urgency > 0.0
    assert b_result.expiration_urgency == 0.0
    assert a_result.score > b_result.score


# ---------------------------------------------------------------------------
# AC-7: substitution penalty ranks recipes
# ---------------------------------------------------------------------------


def test_substitution_penalty_ranking():
    """AC-7: missing ingredient with no close substitute → higher penalty → lower rank.

    Recipe A: high coverage but one missing ingredient with cosine < 0.3 to pantry.
    Recipe B: slightly lower coverage but missing ingredient has high cosine sub in pantry.

    We engineer the embed_fn so:
    - pantry has: 'garlic', 'tomato', 'soy_sauce'
    - recipe_a misses 'mystery_spice' (cosine < 0.3 to all pantry items)
    - recipe_b misses 'soy_sauce_sub' (cosine ≈ 0.9 to 'soy_sauce' in pantry)

    Recipe A has 4/5 coverage (0.8), recipe B has 3/4 coverage (0.75).
    But recipe_b's substitution_penalty is near 0, while recipe_a's is near 1.
    The substitution penalty weight (0.20) should overcome the coverage gap.
    """
    dim = 4
    # Build embedding space:
    # soy_sauce and soy_sauce_sub are nearly identical (cosine ≈ 0.99)
    # mystery_spice is orthogonal to everything in pantry (cosine ≈ 0)
    soy_sauce_vec = np.array([1.0, 0.0, 0.0, 0.0], dtype=np.float32)
    soy_sauce_sub_vec = np.array([0.99, 0.14, 0.0, 0.0], dtype=np.float32)
    garlic_vec = np.array([0.0, 1.0, 0.0, 0.0], dtype=np.float32)
    tomato_vec = np.array([0.0, 0.0, 1.0, 0.0], dtype=np.float32)
    mystery_spice_vec = np.array([0.0, 0.0, 0.0, 1.0], dtype=np.float32)

    # soy_sauce and mystery_spice have cosine = 0 → mystery_spice has no substitute
    # soy_sauce_sub vs soy_sauce cosine ≈ 0.99 → excellent substitute

    mapping = {
        "garlic": garlic_vec,
        "tomato": tomato_vec,
        "soy_sauce": soy_sauce_vec,
        "soy_sauce_sub": soy_sauce_sub_vec,
        "mystery_spice": mystery_spice_vec,
    }
    embed_fn = _fixed_embed(mapping)

    pantry = _make_pantry("garlic", "tomato", "soy_sauce")

    # recipe_a: 4 of 5 present, missing 'mystery_spice' (no sub in pantry)
    recipe_a = _recipe("Mystery Stir Fry", "garlic", "tomato", "soy_sauce", "basil_extra", "mystery_spice")

    # recipe_b: 3 of 4 present, missing 'soy_sauce_sub' (close to 'soy_sauce' in pantry)
    recipe_b = _recipe("Teriyaki Noodles", "garlic", "tomato", "extra_herb", "soy_sauce_sub")

    results = rank_recipes(pantry, [recipe_a, recipe_b], embed_fn=embed_fn)

    assert len(results) == 2
    a_result = next(r for r in results if r.recipe["title"] == "Mystery Stir Fry")
    b_result = next(r for r in results if r.recipe["title"] == "Teriyaki Noodles")

    # recipe_a penalty near 1.0 (mystery_spice orthogonal to all pantry items)
    # recipe_b penalty near 0.0 (soy_sauce_sub ≈ soy_sauce)
    assert a_result.substitution_penalty > b_result.substitution_penalty
    # recipe_b should rank higher despite lower coverage
    assert b_result.score > a_result.score


# ---------------------------------------------------------------------------
# AC-8: cultural_fit with cuisine parameter
# ---------------------------------------------------------------------------


def test_cultural_fit_cuisine_boost():
    """AC-8: with cuisine='italian', recipe with 'italian' in title ranks higher."""
    pantry = _make_pantry("pasta", "tomato", "basil", "garlic", "olive oil")

    recipe_italian = _recipe(
        "Classic Italian Pasta", "pasta", "tomato", "basil", "garlic", "olive oil"
    )
    recipe_generic = _recipe(
        "Pasta with Sauce", "pasta", "tomato", "basil", "garlic", "olive oil"
    )

    # Both have identical ingredients → identical coverage, urgency, substitution
    results = rank_recipes(
        pantry, [recipe_italian, recipe_generic], embed_fn=_identity_embed, cuisine="italian"
    )

    assert len(results) == 2
    italian_result = next(r for r in results if r.recipe["title"] == "Classic Italian Pasta")
    generic_result = next(r for r in results if r.recipe["title"] == "Pasta with Sauce")

    assert italian_result.cultural_fit == 1.0
    assert generic_result.cultural_fit == 0.0
    assert italian_result.score > generic_result.score


# ---------------------------------------------------------------------------
# Additional tests for robustness (AC-3 coverage)
# ---------------------------------------------------------------------------


def test_ranked_recipe_fields():
    """RankedRecipe dataclass has all required fields."""
    pantry = _make_pantry("onion", "garlic")
    recipe = _recipe("Soup", "onion", "garlic", "broth")

    results = rank_recipes(pantry, [recipe], embed_fn=_identity_embed)
    r = results[0]

    assert hasattr(r, "recipe")
    assert hasattr(r, "score")
    assert hasattr(r, "coverage")
    assert hasattr(r, "missing")
    assert hasattr(r, "expiration_urgency")
    assert hasattr(r, "substitution_penalty")
    assert hasattr(r, "cultural_fit")


def test_top_k_limits_results():
    """rank_recipes returns at most k results."""
    pantry = _make_pantry("a", "b", "c")
    recipes = [_recipe(f"Recipe {i}", "a", "b", "c") for i in range(10)]

    results = rank_recipes(pantry, recipes, embed_fn=_identity_embed, k=3)
    assert len(results) <= 3


def test_results_sorted_descending():
    """Results are sorted by score descending."""
    pantry = _make_pantry("garlic", "tomato")
    recipes = [
        _recipe("Full match", "garlic", "tomato"),            # coverage=1.0
        _recipe("Half match", "garlic", "tomato", "basil"),   # coverage=2/3
        _recipe("No match", "egg", "flour", "butter"),        # coverage=0.0
    ]

    results = rank_recipes(pantry, recipes, embed_fn=_identity_embed)
    scores = [r.score for r in results]
    assert scores == sorted(scores, reverse=True)


def test_empty_candidate_list():
    """rank_recipes with no candidates returns empty list."""
    pantry = _make_pantry("garlic", "tomato")
    results = rank_recipes(pantry, [], embed_fn=_identity_embed)
    assert results == []


def test_no_cuisine_cultural_fit_zero():
    """With no cuisine kwarg, cultural_fit is 0.0 for all recipes."""
    pantry = _make_pantry("pasta")
    recipe = _recipe("Italian Pasta", "pasta")

    results = rank_recipes(pantry, [recipe], embed_fn=_identity_embed)
    assert results[0].cultural_fit == 0.0


def test_zero_coverage_recipe_has_nonzero_penalty():
    """A recipe where ALL ingredients are missing has a substitution penalty."""
    # Pantry has nothing in common with the recipe
    pantry = _make_pantry("garlic", "tomato")
    recipe = _recipe("Exotic Dish", "saffron", "truffle", "foie_gras")

    results = rank_recipes(pantry, [recipe], embed_fn=_identity_embed)
    r = results[0]
    assert r.coverage == 0.0
    assert sorted(r.missing) == sorted(["saffron", "truffle", "foie_gras"])
    # substitution_penalty > 0 when all are missing and no close subs
    assert r.substitution_penalty > 0.0
