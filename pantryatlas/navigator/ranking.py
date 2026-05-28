"""T-003: Pantry → recipe ranking algorithm (pure Python).

Scores candidate recipes against the current pantry using a weighted formula:

    score = 0.50 * coverage
          + 0.20 * expiration_urgency
          + 0.20 * (1 - substitution_penalty)
          + 0.10 * cultural_fit

All four sub-scores are in [0, 1].  The function is **pure** — callers supply
everything (pantry, candidates, embed_fn).  No DB or model is loaded here.

Design decisions
----------------
- candidate_recipes are ``dict`` with keys matching ``ingest.parse_recipe``
  output: ``title`` (str), ``ingredients`` (list[str]), ``instructions`` (str).
- ``embed_fn`` mirrors ``pantryatlas.embeddings.embed``:
  ``Callable[[list[str]], np.ndarray]`` returning shape ``(N, D)`` L2-unit-norm rows.
- Coverage uses direct string membership against ``pantry`` canonical names
  (Pantry.__contains__). Fuzzy/semantic matching happens at the API layer (T-004).
- Expiration urgency: 0 when no pantry item has ``expires_at`` set; otherwise
  ``(# expiring items used by the recipe) / (# expiring items in pantry)``.
  Window is 7 days by default.
- Substitution penalty per missing ingredient: ``1 - max_cosine(missing, pantry items)``.
  Average over all missing; 0 when nothing is missing.
- Cultural fit: 1.0 if ``cuisine`` (lowercased) appears in recipe title (lowercased),
  else 0.0.  Always 0.0 when ``cuisine`` is None.
- Results sorted descending by score; top ``k`` returned.
"""

from __future__ import annotations

from collections.abc import Callable
from dataclasses import dataclass, field
from typing import Any

import numpy as np

from pantryatlas.pantry.models import Pantry

# ---------------------------------------------------------------------------
# Public types
# ---------------------------------------------------------------------------


@dataclass
class RankedRecipe:
    """A scored recipe with component sub-scores for debuggability.

    Attributes:
        recipe: The original recipe dict (title, ingredients, instructions).
        score: Weighted composite score in [0, 1].
        coverage: Fraction of recipe ingredients present in pantry.
        missing: Recipe ingredients NOT found in the pantry, in order.
        expiration_urgency: Fraction of expiring pantry items consumed by the recipe.
        substitution_penalty: Mean (1 - best_cosine) across missing ingredients.
        cultural_fit: 1.0 if recipe title contains the requested cuisine; else 0.0.
    """

    recipe: dict[str, Any]
    score: float
    coverage: float
    missing: list[str] = field(default_factory=list)
    expiration_urgency: float = 0.0
    substitution_penalty: float = 0.0
    cultural_fit: float = 0.0


# ---------------------------------------------------------------------------
# Score weights (must sum to 1.0)
# ---------------------------------------------------------------------------

_W_COVERAGE: float = 0.50
_W_EXPIRY: float = 0.20
_W_SUBSTITUTION: float = 0.20
_W_CULTURAL: float = 0.10

# Default look-ahead window for expiration urgency
_EXPIRY_WINDOW_DAYS: int = 7


# ---------------------------------------------------------------------------
# Internal helpers
# ---------------------------------------------------------------------------


def _cosine(a: np.ndarray, b: np.ndarray) -> float:
    """Cosine similarity between two 1-D float arrays.

    Both vectors are assumed L2-normalised; falls back to safe division.
    """
    a = np.asarray(a, dtype=np.float32)
    b = np.asarray(b, dtype=np.float32)
    norm_a = float(np.linalg.norm(a))
    norm_b = float(np.linalg.norm(b))
    if norm_a < 1e-9 or norm_b < 1e-9:
        return 0.0
    return float(np.dot(a, b) / (norm_a * norm_b))


def _compute_coverage(
    recipe_ingredients: list[str],
    pantry: Pantry,
) -> tuple[float, list[str]]:
    """Return (coverage_fraction, missing_list).

    Coverage = (# recipe ingredients in pantry) / (# recipe ingredients).
    Missing list preserves the order of ingredients in the recipe.
    Returns (0.0, all_ingredients) if recipe has no ingredients.
    """
    if not recipe_ingredients:
        return 0.0, []

    missing = [ing for ing in recipe_ingredients if ing not in pantry]
    present = len(recipe_ingredients) - len(missing)
    coverage = present / len(recipe_ingredients)
    return coverage, missing


def _compute_expiration_urgency(
    recipe_ingredients: list[str],
    pantry: Pantry,
    expiry_window_days: int = _EXPIRY_WINDOW_DAYS,
) -> float:
    """Return expiration urgency in [0, 1].

    Urgency = (# expiring pantry items that the recipe uses) / (# expiring pantry items).
    0 when there are no expiring items in the pantry.
    """
    expiring = pantry.expiring_within(expiry_window_days)
    if not expiring:
        return 0.0

    recipe_set = set(recipe_ingredients)
    consumed_expiring = sum(1 for ing in expiring if ing.canonical_name in recipe_set)
    return consumed_expiring / len(expiring)


def _compute_substitution_penalty(
    missing: list[str],
    pantry: Pantry,
    embed_fn: Callable[[list[str]], np.ndarray],
) -> float:
    """Return substitution penalty in [0, 1].

    For each missing ingredient, compute the maximum cosine similarity to any
    pantry item.  penalty_i = 1 - max_cosine.  Average over all missing.
    0.0 when nothing is missing.
    """
    if not missing:
        return 0.0

    pantry_names = [ing.canonical_name for ing in pantry]
    if not pantry_names:
        # Empty pantry → no substitutes possible → full penalty
        return 1.0

    # Embed all texts in one batch for efficiency
    all_texts = missing + pantry_names
    all_embs = embed_fn(all_texts)  # shape (len(missing) + len(pantry_names), D)

    missing_embs = all_embs[: len(missing)]         # (|missing|, D)
    pantry_embs = all_embs[len(missing) :]           # (|pantry|, D)

    # L2-normalise (embed_fn should already return unit vectors, but guard)
    def _unit(matrix: np.ndarray) -> np.ndarray:
        norms = np.linalg.norm(matrix, axis=1, keepdims=True)
        norms = np.where(norms < 1e-9, 1.0, norms)
        return matrix / norms

    missing_embs = _unit(missing_embs)
    pantry_embs = _unit(pantry_embs)

    # Cosine matrix: (|missing|, |pantry|) via matmul (both unit-normed)
    cosine_matrix = missing_embs @ pantry_embs.T  # (|missing|, |pantry|)

    # Max cosine for each missing ingredient (nearest pantry substitute)
    max_cosines = cosine_matrix.max(axis=1)  # (|missing|,)

    # Clamp to [0, 1] (cosines should be in [-1, 1]; negative → no sub)
    max_cosines = np.clip(max_cosines, 0.0, 1.0)

    # penalty_i = 1 - max_cosine_i; average across missing
    penalties = 1.0 - max_cosines
    return float(np.mean(penalties))


def _compute_cultural_fit(recipe: dict[str, Any], cuisine: str | None) -> float:
    """Return 1.0 if cuisine appears in recipe title (case-insensitive), else 0.0."""
    if cuisine is None:
        return 0.0
    return 1.0 if cuisine.lower() in recipe.get("title", "").lower() else 0.0


# ---------------------------------------------------------------------------
# Public API
# ---------------------------------------------------------------------------


def rank_recipes(
    pantry: Pantry,
    candidate_recipes: list[dict[str, Any]],
    embed_fn: Callable[[list[str]], np.ndarray],
    k: int = 20,
    *,
    cuisine: str | None = None,
    expiry_window_days: int = _EXPIRY_WINDOW_DAYS,
) -> list[RankedRecipe]:
    """Score and rank candidate recipes against the current pantry.

    Args:
        pantry: The caller's in-memory ``Pantry`` (with optional expiry dates).
        candidate_recipes: List of recipe dicts (keys: title, ingredients, instructions).
            Recipes come pre-filtered from the sqlite-vec layer (T-004); this
            function is responsible for fine-grained scoring only.
        embed_fn: Embedding callable mirroring ``pantryatlas.embeddings.embed``.
            Signature: ``(list[str]) → np.ndarray`` shape ``(N, D)``, L2-normalised.
            Injected to avoid loading the ONNX model in unit tests.
        k: Maximum number of results to return (default 20).
        cuisine: Optional cuisine filter string (e.g. ``'italian'``).  When set,
            recipes whose title contains this string receive cultural_fit=1.0.
        expiry_window_days: Look-ahead window for expiration urgency (default 7).

    Returns:
        List of :class:`RankedRecipe` sorted descending by score, at most ``k`` items.
    """
    if not candidate_recipes:
        return []

    ranked: list[RankedRecipe] = []

    for recipe in candidate_recipes:
        ingredients: list[str] = recipe.get("ingredients", [])

        # --- coverage ---
        coverage, missing = _compute_coverage(ingredients, pantry)

        # --- expiration urgency ---
        expiration_urgency = _compute_expiration_urgency(
            ingredients, pantry, expiry_window_days
        )

        # --- substitution penalty ---
        substitution_penalty = _compute_substitution_penalty(missing, pantry, embed_fn)

        # --- cultural fit ---
        cultural_fit = _compute_cultural_fit(recipe, cuisine)

        # --- weighted score ---
        score = (
            _W_COVERAGE * coverage
            + _W_EXPIRY * expiration_urgency
            + _W_SUBSTITUTION * (1.0 - substitution_penalty)
            + _W_CULTURAL * cultural_fit
        )

        ranked.append(
            RankedRecipe(
                recipe=recipe,
                score=score,
                coverage=coverage,
                missing=missing,
                expiration_urgency=expiration_urgency,
                substitution_penalty=substitution_penalty,
                cultural_fit=cultural_fit,
            )
        )

    # Sort descending by score
    ranked.sort(key=lambda r: r.score, reverse=True)

    return ranked[:k]
