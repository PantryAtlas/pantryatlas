"""Query-time recipe facets: cuisine / diet / time, derived from unstructured text.

All keyword lists are in-module constants (no data file → no dependency or
shipping gap). Precision-first: a recipe with no distinctive marker is unclassified.
"""
from __future__ import annotations

import re

# Distinctive cuisine markers (curated for precision; generic cooking words excluded).
# Thai/French dropped (insufficient precision/volume); Indian limited to unambiguous markers.
CUISINES: dict[str, list[str]] = {
    "italian": [
        "spaghetti", "lasagna", "lasagne", "risotto", "marinara", "parmesan",
        "parmigiano", "mozzarella", "ricotta", "prosciutto", "pesto", "fettuccine",
        "gnocchi", "cannoli", "manicotti", "pancetta", "ziti", "alfredo",
    ],
    "mexican": [
        "taco", "tortilla", "salsa", "enchilada", "quesadilla", "guacamole",
        "fajita", "chipotle", "tostada", "burrito", "refried", "tomatillo",
    ],
    "asian": [
        "hoisin", "teriyaki", "miso", "bok choy", "wonton", "szechuan",
        "sichuan", "stir-fry", "stir fry", "oyster sauce", "five spice", "lo mein",
        "sesame oil", "sriracha",
    ],
    "indian": [
        "garam masala", "paneer", "tikka", "tandoori", "naan", "biryani", "korma",
        "masala",
    ],
    "greek": [
        "feta", "tzatziki", "hummus", "falafel", "tahini", "gyro",
        "baklava", "spanakopita", "dolma",
    ],
    "american": [
        "cornbread", "meatloaf", "grits", "sloppy joe", "bbq sauce",
        "barbecue sauce", "jambalaya", "pot roast", "buttermilk biscuit",
    ],
}

# Tie-break priority when a recipe matches multiple cuisines by equal marker count.
_CUISINE_PRIORITY = ["indian", "mexican", "greek", "asian", "italian", "american"]

MEAT_MARKERS: list[str] = [
    "beef", "chicken", "pork", "bacon", "sausage", "ham ", "turkey", "lamb",
    "steak", "veal", "prosciutto", "pancetta", "pepperoni", "salami", "duck",
    "fish", "salmon", "tuna", "shrimp", "crab", "anchovy", "gelatin",
    "chicken broth", "beef broth", "fish sauce",
]
DAIRY_MARKERS: list[str] = [
    "milk", "cheese", "butter", "cream", "yogurt", "parmesan", "mozzarella",
    "cheddar", "ricotta", "ghee", "buttermilk", "custard", "half and half",
]
GLUTEN_MARKERS: list[str] = [
    "flour", "bread", "pasta", "wheat", "barley", "rye", "soy sauce", "breadcrumb",
    "bread crumb", "cracker", "noodle", "tortilla", "couscous", "semolina",
    "beer", "malt",
]

_EXCLUDE_MARKERS = {"meat": MEAT_MARKERS, "dairy": DAIRY_MARKERS, "gluten": GLUTEN_MARKERS}
VALID_EXCLUDES = frozenset(_EXCLUDE_MARKERS)

# Durations not preceded by "every" (frequency, not duration).
_TIME_RE = re.compile(
    r"(?<!every )(\d+)\s*(?:to|-|–)?\s*(\d+)?\s*(minutes?|mins?|hours?|hrs?)\b", re.I
)
_OVERNIGHT_RE = re.compile(r"over\s*night", re.I)


def _blob(title: str, ingredients: list[str]) -> str:
    return (title + " " + " ".join(ingredients)).lower()


def classify_cuisine(title: str, ingredients: list[str]) -> str | None:
    """Return the single best-matching cuisine, or None if no distinctive marker."""
    blob = _blob(title, ingredients)
    scores: dict[str, int] = {}
    for cuisine, markers in CUISINES.items():
        n = sum(1 for m in markers if m in blob)
        if n:
            scores[cuisine] = n
    if not scores:
        return None
    best = max(scores.values())
    tied = [c for c, n in scores.items() if n == best]
    if len(tied) == 1:
        return tied[0]
    for c in _CUISINE_PRIORITY:
        if c in tied:
            return c
    return tied[0]


def detect_excludes(ingredients: list[str]) -> set[str]:
    """Return the subset of {meat, dairy, gluten} detected in the ingredient list."""
    blob = " ".join(ingredients).lower()
    return {name for name, markers in _EXCLUDE_MARKERS.items() if any(m in blob for m in markers)}


def estimate_time_min(instructions: str) -> int | None:
    """Rough TOTAL time estimate (incl. passive chill/bake) in minutes, or None.

    Sums stated durations (ranges counted once, hours ×60); 'overnight' → 480;
    durations preceded by 'every' (a frequency) are ignored.
    """
    if not instructions:
        return None
    total = 0.0
    found = False
    for m in _TIME_RE.finditer(instructions):
        found = True
        lo = int(m.group(1))
        hi = int(m.group(2)) if m.group(2) else lo
        val = (lo + hi) / 2
        if m.group(3).lower().startswith("h"):
            val *= 60
        total += val
    if _OVERNIGHT_RE.search(instructions):
        found = True
        total += 480
    return int(round(total)) if found else None


def passes_filters(
    recipe: dict,
    *,
    cuisine: str | None = None,
    exclude: set[str] | None = None,
    max_time_min: int | None = None,
) -> bool:
    """True if a candidate recipe dict ({title, ingredients, instructions}) passes
    all active filters. Cuisine is STRICT (unclassified hidden); diet hides on
    detection; time keeps unknown-estimate recipes."""
    ingredients = recipe.get("ingredients", []) or []
    if cuisine:
        if classify_cuisine(recipe.get("title", ""), ingredients) != cuisine:
            return False
    if exclude:
        if detect_excludes(ingredients) & exclude:
            return False
    if max_time_min is not None:
        instr = recipe.get("instructions", []) or []
        if isinstance(instr, list):
            instr = " ".join(instr)
        est = estimate_time_min(instr)
        if est is not None and est > max_time_min:
            return False
    return True
