"""Default mini-vocab for v0.1 testing.

This 15-word hardcoded list lets AC-4..AC-7 tests run without the T-008
canonical-vocab parquet (which does not exist yet in v0.1).

**Do not use this for production.** Downstream code (pantry-navigator and
similar) must build its own ``Matcher`` from the full T-008 parquet vocab::

    from pantryatlas.pantry import Matcher
    from pantryatlas.embeddings import embed

    canonical_names = load_from_parquet(...)  # T-008 output
    embeddings = embed(canonical_names)
    matcher = Matcher(canonical_names=canonical_names, embeddings=embeddings)

This module is intentionally tiny so bge-m3 startup cost is bounded during
testing (≈30-60 s on Pi first load, instant after).
"""

DEFAULT_VOCAB_NAMES: list[str] = [
    "garlic",
    "onion",
    "tomato",
    "potato",
    "carrot",
    "salt",
    "pepper",
    "olive oil",
    "butter",
    "flour",
    "sugar",
    "egg",
    "milk",
    "rice",
    "chicken",
]
