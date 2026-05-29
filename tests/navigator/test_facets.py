from __future__ import annotations

from pantryatlas.navigator.facets import (
    CUISINES,
    classify_cuisine,
    detect_excludes,
    estimate_time_min,
)


def test_cuisine_precision():
    assert classify_cuisine("Beef Tacos", ["ground beef", "tortilla", "salsa"]) == "mexican"
    assert (
        classify_cuisine("Spaghetti Carbonara", ["spaghetti", "pancetta", "parmesan"])
        == "italian"
    )
    assert (
        classify_cuisine("Chicken Tikka Masala", ["chicken", "garam masala", "paneer"])
        == "indian"
    )
    assert classify_cuisine("BBQ Brisket", ["brisket", "bbq sauce"]) == "american"
    assert classify_cuisine("Greek Salad", ["feta", "olive", "tomato"]) == "greek"
    assert classify_cuisine("Chicken Stir-Fry", ["chicken", "soy sauce", "bok choy"]) == "asian"
    # generic recipe → None (no butter→french false positive)
    assert classify_cuisine("Buttered Toast", ["bread", "butter"]) is None
    # shipped set is exactly these six (Thai/French dropped)
    assert set(CUISINES) == {"italian", "mexican", "asian", "american", "indian", "greek"}


def test_detect_excludes():
    assert detect_excludes(["chicken breast", "onion"]) == {"meat"}
    assert "dairy" in detect_excludes(["milk", "cheddar cheese"])
    assert "gluten" in detect_excludes(["all-purpose flour", "sugar"])
    assert detect_excludes(["soy sauce", "rice"]) >= {"gluten"}  # soy sauce has gluten
    assert detect_excludes(["apple", "carrot", "lettuce"]) == set()


def test_estimate_time_min():
    assert estimate_time_min("Bake for 30 minutes.") == 30
    assert estimate_time_min("Simmer 1 hour.") == 60
    assert estimate_time_min("Cook 30 to 40 minutes.") == 35  # range counted once
    # 'every 2' skipped — only the 20-minute bake counts
    assert estimate_time_min("Stir every 2 minutes while baking 20 minutes.") == 20
    assert estimate_time_min("Chill overnight.") == 480
    assert estimate_time_min("Mix well and serve.") is None  # no duration
