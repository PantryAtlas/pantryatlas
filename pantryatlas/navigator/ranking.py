"""T-003: Pantry → recipe ranking algorithm (pure Python).

Scores candidate recipes against the current pantry using a weighted formula:

    score = 0.50 * coverage
          + 0.20 * expiration_urgency
          + 0.20 * (1 - substitution_penalty)
          + 0.10 * flavor

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

import logging
from collections.abc import Callable
from dataclasses import dataclass, field
from typing import Any

import numpy as np

from pantryatlas.pantry.models import Pantry

_log = logging.getLogger(__name__)

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
    flavor: float = 0.0


# ---------------------------------------------------------------------------
# Score weights (must sum to 1.0)
# ---------------------------------------------------------------------------

_W_COVERAGE: float = 0.50
_W_EXPIRY: float = 0.20
_W_SUBSTITUTION: float = 0.20
_W_CULTURAL: float = 0.0   # superseded by flavor (slice 3); cuisine ranking → slice 2
_W_FLAVOR: float = 0.10

# Default look-ahead window for expiration urgency
_EXPIRY_WINDOW_DAYS: int = 7


# ---------------------------------------------------------------------------
# Internal helpers
# ---------------------------------------------------------------------------


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


def _unit(matrix: np.ndarray) -> np.ndarray:
    """L2-normalise rows; guard against zero-norm rows."""
    norms = np.linalg.norm(matrix, axis=1, keepdims=True)
    norms = np.where(norms < 1e-9, 1.0, norms)
    return matrix / norms


def _substitute_matches(
    missing_unique: list[str],
    pantry_names: list[str],
    embed_fn: Callable[[list[str]], np.ndarray],
) -> dict[str, tuple[str, float]]:
    """Return ``{missing_text: (best_pantry_name, cosine)}`` for each missing item.

    Embeds all unique missing items plus the pantry names in a SINGLE batched
    ``embed_fn`` call (the embedding model is the slow part on Pi — ~16 short
    strings/sec — so one call instead of one-per-recipe is the whole game).
    ``cosine`` is the raw best-match similarity (callers clamp/threshold).
    Returns an empty dict when there is nothing to match.
    """
    if not missing_unique or not pantry_names:
        return {}

    all_embs = embed_fn(missing_unique + pantry_names)
    missing_embs = _unit(all_embs[: len(missing_unique)])
    pantry_embs = _unit(all_embs[len(missing_unique) :])

    cosine_matrix = missing_embs @ pantry_embs.T  # (|missing|, |pantry|)

    out: dict[str, tuple[str, float]] = {}
    for i, text in enumerate(missing_unique):
        j = int(np.argmax(cosine_matrix[i]))
        out[text] = (pantry_names[j], float(cosine_matrix[i][j]))
    return out


def _penalty_from_matches(
    missing: list[str],
    pantry_names: list[str],
    matches: dict[str, tuple[str, float]],
) -> float:
    """Mean (1 - clamped best-cosine) across a recipe's missing ingredients.

    0.0 when nothing is missing; 1.0 when the pantry is empty (no substitutes).
    """
    if not missing:
        return 0.0
    if not pantry_names:
        return 1.0
    sims = [min(max(matches[m][1], 0.0), 1.0) for m in missing]
    return float(np.mean([1.0 - s for s in sims]))


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
    embed_fn: Callable[[list[str]], np.ndarray] | None = None,
    k: int = 20,
    *,
    cuisine: str | None = None,
    expiry_window_days: int = _EXPIRY_WINDOW_DAYS,
    compute_substitution: bool = True,
    flavor_fn: Callable[[list[str], list[str]], float] | None = None,
    flavor_top_n: int = 250,
    history_fn: Callable[[str], float] | None = None,
) -> list[RankedRecipe]:
    """Score and rank candidate recipes against the current pantry.

    Two operating modes drive the navigator's instant-then-refine UX:

    - ``compute_substitution=False`` (**fast mode**): scores coverage,
      expiration and cultural fit only — no embedding, so it returns instantly
      even for tens of thousands of candidates.  ``substitution_penalty`` is set
      to ``0.0`` (optimistic), which means the substitution term contributes a
      constant ``0.20`` to every score and therefore does not affect ordering.
      ``embed_fn`` may be ``None`` here.
    - ``compute_substitution=True`` (**refine mode**): additionally embeds every
      unique missing ingredient across the candidate set in a SINGLE batched
      ``embed_fn`` call and computes the real substitution penalty.  Because the
      fast mode was optimistic, refining can only ever *lower* scores, so cards
      converge downward — a stable settle animation on the client.

    Args:
        pantry: The caller's in-memory ``Pantry`` (with optional expiry dates).
        candidate_recipes: List of recipe dicts (keys: title, ingredients, instructions).
        embed_fn: Embedding callable mirroring ``pantryatlas.embeddings.embed``.
            Required when ``compute_substitution=True``; ignored otherwise.
        k: Maximum number of results to return (default 20).
        cuisine: Optional cuisine filter string (e.g. ``'italian'``).
        expiry_window_days: Look-ahead window for expiration urgency (default 7).
        compute_substitution: Whether to compute the embedding-based substitution
            penalty (refine mode) or skip it (fast mode).
        history_fn: Optional ``title -> bounded adjustment`` added to each
            candidate's score; ``None`` = no history effect.

    Returns:
        List of :class:`RankedRecipe` sorted descending by score, at most ``k`` items.
    """
    if not candidate_recipes:
        return []
    if compute_substitution and embed_fn is None:
        raise ValueError("embed_fn is required when compute_substitution=True")

    pantry_names = [ing.canonical_name for ing in pantry]

    # Pass 1 — cheap signals (no embedding): coverage, expiration, cultural fit.
    prelim: list[tuple[dict[str, Any], float, list[str], float, float]] = []
    for recipe in candidate_recipes:
        ingredients: list[str] = recipe.get("ingredients", [])
        coverage, missing = _compute_coverage(ingredients, pantry)
        expiration_urgency = _compute_expiration_urgency(
            ingredients, pantry, expiry_window_days
        )
        cultural_fit = _compute_cultural_fit(recipe, cuisine)
        prelim.append((recipe, coverage, missing, expiration_urgency, cultural_fit))

    # Pass 2 — substitution (refine mode only): one batched embedding call for
    # all unique missing ingredients across the whole candidate set.
    matches: dict[str, tuple[str, float]] = {}
    if compute_substitution and pantry_names:
        unique_missing = sorted({m for (_, _, missing, _, _) in prelim for m in missing})
        matches = _substitute_matches(unique_missing, pantry_names, embed_fn)  # type: ignore[arg-type]

    # Phase A: non-flavor score for every candidate.
    scored: list[
        tuple[dict[str, Any], float, list[str], float, float, float, float]
    ] = []
    for recipe, coverage, missing, expiration_urgency, cultural_fit in prelim:
        substitution_penalty = (
            _penalty_from_matches(missing, pantry_names, matches)
            if compute_substitution
            else 0.0
        )
        nonflavor = (
            _W_COVERAGE * coverage
            + _W_EXPIRY * expiration_urgency
            + _W_SUBSTITUTION * (1.0 - substitution_penalty)
            + _W_CULTURAL * cultural_fit
        )
        if history_fn is not None:
            nonflavor += history_fn(recipe.get("title", ""))
        scored.append(
            (recipe, coverage, missing, expiration_urgency, cultural_fit,
             substitution_penalty, nonflavor)
        )

    # Phase B: compute flavor only for the top-N by non-flavor score (perf cap).
    flavor_indices = set(range(len(scored)))
    if flavor_fn is not None and len(scored) > flavor_top_n:
        ordered = sorted(range(len(scored)), key=lambda i: scored[i][6], reverse=True)
        flavor_indices = set(ordered[:flavor_top_n])
        _log.info(
            "flavor capped to top %d of %d candidates", flavor_top_n, len(scored)
        )

    ranked: list[RankedRecipe] = []
    for i, (recipe, coverage, missing, expiration_urgency, cultural_fit,
            substitution_penalty, nonflavor) in enumerate(scored):
        flavor = 0.0
        if flavor_fn is not None and i in flavor_indices:
            flavor = flavor_fn(recipe.get("ingredients", []), pantry_names)
        score = nonflavor + _W_FLAVOR * flavor
        if score < 0.0:
            score = 0.0
        elif score > 1.0:
            score = 1.0
        ranked.append(
            RankedRecipe(
                recipe=recipe,
                score=score,
                coverage=coverage,
                missing=missing,
                expiration_urgency=expiration_urgency,
                substitution_penalty=substitution_penalty,
                cultural_fit=cultural_fit,
                flavor=flavor,
            )
        )

    ranked.sort(key=lambda r: r.score, reverse=True)
    return ranked[:k]


# Minimum cosine similarity for a pantry item to be offered as a swap. Below
# this, the UX shows "no close swap" rather than a misleading suggestion.
SWAP_SIMILARITY_FLOOR: float = 0.5


def compute_swaps(
    recipe_ingredients: list[str],
    pantry: Pantry,
    embed_fn: Callable[[list[str]], np.ndarray],
    *,
    sim_floor: float = SWAP_SIMILARITY_FLOOR,
) -> list[dict[str, Any]]:
    """Suggest pantry swaps for a single recipe's missing ingredients.

    For each missing ingredient (in recipe order, de-duplicated), find the
    closest pantry item by embedding cosine.  When the best match clears
    ``sim_floor`` it is offered as ``best_swap`` with its ``similarity``;
    otherwise ``best_swap`` is ``None`` and ``reason`` is ``"no_close_match"``.

    Returns a list of ``{"missing", "best_swap", "similarity", "reason"}`` dicts.
    """
    pantry_names = [ing.canonical_name for ing in pantry]
    seen: set[str] = set()
    missing_ordered: list[str] = []
    for ing in recipe_ingredients:
        if ing not in pantry and ing not in seen:
            seen.add(ing)
            missing_ordered.append(ing)

    matches = _substitute_matches(missing_ordered, pantry_names, embed_fn)

    swaps: list[dict[str, Any]] = []
    for ing in missing_ordered:
        match = matches.get(ing)
        if match is None:
            swaps.append(
                {"missing": ing, "best_swap": None, "similarity": 0.0, "reason": "no_pantry"}
            )
            continue
        name, cosine = match
        similarity = min(max(cosine, 0.0), 1.0)
        if similarity >= sim_floor:
            swaps.append(
                {"missing": ing, "best_swap": name, "similarity": similarity, "reason": None}
            )
        else:
            swaps.append(
                {
                    "missing": ing,
                    "best_swap": None,
                    "similarity": similarity,
                    "reason": "no_close_match",
                }
            )
    return swaps
