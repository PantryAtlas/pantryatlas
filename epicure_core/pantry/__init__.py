"""Pantry primitives and multilingual ingredient matchers.

Public API
----------
- ``Ingredient`` — a single resolved ingredient (canonical name + optional
  quantity and expiry).
- ``Quantity`` — an amount + unit.
- ``Pantry`` — in-memory pantry that deduplicates by canonical name and
  supports expiry filtering.
- ``Matcher`` — three-stage resolver (exact → fuzzy → semantic) with
  dependency-injected vocab.
- ``resolve`` — module-level convenience using the built-in 15-word mini-vocab
  (for testing / quick scripts only; production code should build its own
  ``Matcher`` from the T-008 parquet vocab).
"""

from epicure_core.pantry.matcher import Matcher, resolve
from epicure_core.pantry.models import Ingredient, Pantry, Quantity

__all__ = [
    "Ingredient",
    "Matcher",
    "Pantry",
    "Quantity",
    "resolve",
]
