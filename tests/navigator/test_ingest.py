"""Tests for pantryatlas.navigator.ingest module."""

from __future__ import annotations

from pantryatlas.navigator.ingest import (
    curate,
    extract_ingredient_lines,
    parse_recipe,
)


def test_parse_recipe_basic():
    """Test parse_recipe with a valid synthetic input."""
    recipe_text = """Chocolate Chip Cookies

Ingredients:
- 2 cups flour
- 1 cup butter
- 1 cup sugar
- 2 eggs
- 1 tsp vanilla
- 2 cups chocolate chips

Directions:
- Mix ingredients and bake at 350F for 10 minutes."""

    result = parse_recipe(recipe_text)
    assert result is not None
    assert result["title"] == "Chocolate Chip Cookies"
    assert len(result["ingredients"]) >= 4  # Should extract at least flour, butter, sugar, eggs
    assert "chocolate chips" in result["ingredients"]
    assert "bake" in result["instructions"].lower()


def test_parse_recipe_none_input():
    """Test that parse_recipe returns None for None/empty input."""
    assert parse_recipe(None) is None
    assert parse_recipe("") is None
    assert parse_recipe("   \n  \n  ") is None


def test_parse_recipe_empty_ingredients():
    """Test that parse_recipe returns None when no Ingredients block."""
    recipe_text = """My Recipe

This is a recipe without a proper Ingredients block.

Directions:
- Do something."""

    result = parse_recipe(recipe_text)
    assert result is None


def test_parse_recipe_fewer_than_three_ingredients():
    """Test that parse_recipe returns None or minimal for fewer than 3 ingredients."""
    recipe_text = """Simple Recipe

Ingredients:
- salt
- pepper

Directions:
- Mix together."""

    result = parse_recipe(recipe_text)
    # parse_recipe itself doesn't filter by count; that's done in curate()
    # But it should parse what's there
    if result:
        assert len(result["ingredients"]) == 2


def test_extract_ingredient_lines():
    """Test extract_ingredient_lines with various formats."""
    recipe_text = """Test Recipe

Ingredients:
- 2 cups flour
- 1/2 cup sugar
- 3 eggs, beaten
- 1 tbsp vanilla extract
- (not an ingredient)

Directions:
- Mix and bake."""

    lines = extract_ingredient_lines(recipe_text)
    assert len(lines) >= 3
    # flour, sugar, eggs, vanilla should be parsed
    assert any("flour" in line for line in lines)
    assert any("sugar" in line for line in lines)


def test_curate_requires_minimum_ingredients():
    """Test that curate discards rows with fewer than 3 ingredients."""
    rows = [
        {"title": "Too Few", "ingredients": ["salt", "pepper"], "instructions": "mix"},
        {
            "title": "Just Right",
            "ingredients": ["flour", "sugar", "butter"],
            "instructions": "bake",
        },
        {"title": "Also Few", "ingredients": ["water"], "instructions": "heat"},
    ]

    result = curate(rows, limit=10)
    assert len(result["selected"]) == 1
    assert result["selected"][0]["title"] == "Just Right"
    discarded_count = sum(count for _, count in result["discarded"])
    assert discarded_count == 2


def test_curate_balances_buckets():
    """Test that curate balances ingredient-count buckets."""
    # Create 90 synthetic rows: 30 in 3-5 range, 30 in 6-8, 30 in 9+
    rows = []
    for i in range(30):
        rows.append({
            "title": f"Recipe3_{i}",
            "ingredients": ["ing"] * (3 + i % 3),  # 3-5 ingredients
            "instructions": "cook",
        })
    for i in range(30):
        rows.append({
            "title": f"Recipe6_{i}",
            "ingredients": ["ing"] * (6 + i % 3),  # 6-8 ingredients
            "instructions": "cook",
        })
    for i in range(30):
        rows.append({
            "title": f"Recipe9_{i}",
            "ingredients": ["ing"] * (9 + i % 5),  # 9+ ingredients
            "instructions": "cook",
        })

    result = curate(rows, limit=30)
    selected = result["selected"]
    buckets = result["buckets"]

    # With limit=30 and 3 buckets, target per bucket = 10
    # So each bucket should have at least 10 (25% of 30 is 7.5, 25% check is >= 25%)
    assert len(selected) >= 25  # Should get close to limit
    assert buckets["3-5"] >= 7  # At least 25% of target (rough estimate)
    assert buckets["6-8"] >= 7
    assert buckets["9+"] >= 7


def test_curate_empty_input():
    """Test curate with empty input."""
    result = curate([], limit=10)
    assert len(result["selected"]) == 0
    assert len(result["discarded"]) > 0
    assert result["buckets"]["3-5"] == 0
    assert result["buckets"]["6-8"] == 0
    assert result["buckets"]["9+"] == 0


def test_curate_discards_under_3_ingredients():
    """Test that curate explicitly discards rows with too few ingredients."""
    rows = [
        {"title": "Low1", "ingredients": ["water"], "instructions": ""},
        {"title": "Low2", "ingredients": ["salt", "pepper"], "instructions": ""},
        {"title": "Good", "ingredients": ["a", "b", "c", "d"], "instructions": ""},
    ]

    result = curate(rows, limit=10)
    assert len(result["selected"]) == 1
    assert result["selected"][0]["title"] == "Good"

    discarded = dict(result["discarded"])
    assert discarded.get("too few ingredients", 0) == 2
