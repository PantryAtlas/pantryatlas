from __future__ import annotations

from pantryatlas.navigator.facets import (
    CUISINES,
    classify_cuisine,
    detect_excludes,
    estimate_time_min,
    passes_filters,
)


def _rec(title, ingredients, instructions=""):
    return {"title": title, "ingredients": ingredients, "instructions": instructions}


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


def test_passes_filters_cuisine_strict():
    mex = _rec("Beef Tacos", ["ground beef", "tortilla", "salsa"])
    unclassified = _rec("Garlic Soup", ["garlic", "water"])
    ital = _rec("Spaghetti", ["spaghetti", "marinara"])
    # match kept; unclassified hidden (strict); other-cuisine hidden
    assert passes_filters(mex, cuisine="mexican") is True
    assert passes_filters(unclassified, cuisine="mexican") is False
    assert passes_filters(ital, cuisine="mexican") is False


def test_passes_filters_diet_hide_on_detect():
    meaty = _rec("Stew", ["beef", "carrot"])
    veg = _rec("Salad", ["lettuce", "tomato"])
    assert passes_filters(meaty, exclude={"meat"}) is False
    assert passes_filters(veg, exclude={"meat"}) is True
    # multiple excludes: any hit hides
    assert passes_filters(_rec("Mac", ["pasta", "cheese"]), exclude={"dairy", "gluten"}) is False


def test_passes_filters_time_keeps_unknown_hides_over_cap():
    quick = _rec("Quick", ["egg"], "Cook 10 minutes.")
    slow = _rec("Slow", ["beef"], "Simmer 3 hours.")
    no_time = _rec("Mystery", ["rice"], "Mix and serve.")
    assert passes_filters(quick, max_time_min=30) is True
    assert passes_filters(slow, max_time_min=30) is False
    assert passes_filters(no_time, max_time_min=30) is True  # unknown estimate kept


def test_passes_filters_all_off_keeps_everything():
    r = _rec("Anything", ["beef", "flour", "cheese"], "Bake 5 hours.")
    assert passes_filters(r) is True
    assert passes_filters(r, cuisine=None, exclude=set(), max_time_min=None) is True


def test_passes_filters_combined():
    # mexican + no-dairy + <=30min: a mexican recipe with cheese is hidden by dairy
    r = _rec("Cheesy Quesadilla", ["tortilla", "cheese", "salsa"], "Cook 10 minutes.")
    assert passes_filters(r, cuisine="mexican") is True
    assert passes_filters(r, cuisine="mexican", exclude={"dairy"}) is False
