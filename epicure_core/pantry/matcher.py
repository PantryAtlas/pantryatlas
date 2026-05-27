"""Ingredient matcher: exact → fuzzy → semantic resolution.

The ``Matcher`` class accepts a vocab via **dependency injection** — it does
not load any files on its own.  This keeps the matching logic reusable for
both the tiny v0.1 built-in test vocab and the full T-008 canonical-vocab
parquet that downstream repos will provide::

    # Downstream / pantry-navigator usage (T-008 parquet):
    from epicure_core.pantry import Matcher
    from epicure_core.embeddings import embed

    canonical_names = load_from_parquet(...)  # your T-008 output
    embeddings = embed(canonical_names)       # shape (N, 1024), L2-normalised
    matcher = Matcher(canonical_names=canonical_names, embeddings=embeddings)
    result = matcher.resolve("spring onion")  # → Ingredient(canonical_name="onion", ...)

Module-level convenience
------------------------
``resolve(raw_text)`` is provided for tests and quick scripts.  On first call
it lazily builds a ``Matcher`` from the 15-word built-in ``DEFAULT_VOCAB_NAMES``
(embedding via bge-m3 — ~30-60 s on Pi first run, instant after).  The
singleton is cached at module level.

**Do not use the module-level ``resolve()`` in production** — pass your own
``Matcher`` with the full vocab instead.

Fuzzy scorer
------------
``rapidfuzz.fuzz.ratio`` (not ``partial_ratio``, not ``WRatio``).  This
returns a score in [0, 100]; the internal comparison uses ``score / 100``
against ``fuzzy_threshold`` (default 0.85).  Using ``ratio`` (not
``partial_ratio``) prevents multi-word queries like "table salt" from hitting
"salt" via the fuzzy path — those should go through semantic instead.

Semantic path
-------------
Uses cosine similarity between L2-normalised bge-m3 embeddings.  The query
is embedded only when both exact and fuzzy stages miss — avoiding the ~50 ms
ONNX forward pass for common resolutions.

Empirical note (2026-05-27, bge-m3 int8, 15-word vocab)
--------------------------------------------------------
Cross-language synonym pairs (courgette/zucchini, eggplant/aubergine) score
~0.45-0.55 — too low for any useful threshold with a tiny vocab.  The 0.60
threshold is calibrated for **within-language near-synonyms** such as:

    "spring onion" → "onion"  (cosine 0.785)
    "sea salt"     → "salt"   (cosine 0.840)
    "whole milk"   → "milk"   (cosine 0.761)
    "cane sugar"   → "sugar"  (cosine 0.787)

Cross-language resolution (courgette→zucchini) is deferred to v0.2 via
the T-008 aliases column.
"""

from __future__ import annotations

import threading
from collections.abc import Callable
from typing import TYPE_CHECKING

import numpy as np
from rapidfuzz import fuzz

from epicure_core.pantry.models import Ingredient

if TYPE_CHECKING:
    pass


class Matcher:
    """Resolves raw ingredient strings to canonical ``Ingredient`` objects.

    Resolution order:
    1. **Exact** — lowercased string equality against canonical names.
    2. **Fuzzy** — ``rapidfuzz.fuzz.ratio`` ÷ 100 ≥ ``fuzzy_threshold``
       (default 0.85).  Best-scoring candidate wins; ties broken by list order.
    3. **Semantic** — cosine similarity of bge-m3 embeddings ≥
       ``semantic_threshold`` (default 0.60).  The query is embedded lazily
       only when the first two stages miss.

    Args:
        canonical_names: Ordered list of canonical ingredient names.
        embeddings: Pre-computed L2-normalised bge-m3 embeddings, shape
            ``(len(canonical_names), 1024)``.  Must correspond 1-to-1 with
            ``canonical_names``.
        embed_fn: Callable that maps ``list[str] → np.ndarray`` (shape
            ``(N, 1024)``).  Defaults to ``epicure_core.embeddings.embed``
            when omitted.  Injected here to allow testing without the full
            ONNX stack.
        fuzzy_threshold: Minimum ``fuzz.ratio / 100`` to count as a fuzzy
            match.  Default 0.85.
        semantic_threshold: Minimum cosine similarity to count as a semantic
            match.  Default 0.60.
    """

    def __init__(
        self,
        canonical_names: list[str],
        embeddings: np.ndarray,
        embed_fn: Callable[[list[str]], np.ndarray] | None = None,
        fuzzy_threshold: float = 0.85,
        semantic_threshold: float = 0.60,
    ) -> None:
        if len(canonical_names) != embeddings.shape[0]:
            raise ValueError(
                f"canonical_names length ({len(canonical_names)}) must match "
                f"embeddings.shape[0] ({embeddings.shape[0]})"
            )
        self._names = canonical_names
        # Normalise just in case the caller didn't; cost is negligible here.
        norms = np.linalg.norm(embeddings, axis=1, keepdims=True)
        norms = np.where(norms == 0, 1.0, norms)
        self._embs: np.ndarray = (embeddings / norms).astype(np.float32)
        # Resolver for the fuzzy threshold.  We compare fuzz.ratio (0-100)
        # against threshold * 100 to avoid floating-point confusion.
        self._fuzzy_threshold_100: float = fuzzy_threshold * 100
        self._semantic_threshold: float = semantic_threshold
        if embed_fn is None:
            from epicure_core.embeddings import embed as _default_embed

            self._embed_fn: Callable[[list[str]], np.ndarray] = _default_embed
        else:
            self._embed_fn = embed_fn

    # ------------------------------------------------------------------ #
    # Public API                                                           #
    # ------------------------------------------------------------------ #

    def resolve(self, raw_text: str) -> Ingredient | None:
        """Resolve *raw_text* to the best matching canonical ``Ingredient``.

        Returns ``None`` when no stage produces a match above its threshold.

        Args:
            raw_text: Raw ingredient string from user input.

        Returns:
            ``Ingredient`` with the matched ``canonical_name`` and
            ``raw_text`` set to the original input, or ``None``.
        """
        normalised = raw_text.strip().lower()

        # --- Stage 1: exact match ---
        if normalised in self._names:
            return Ingredient(canonical_name=normalised, raw_text=raw_text)

        # --- Stage 2: fuzzy match (fuzz.ratio, 0-100 scale) ---
        best_fuzzy_name, best_fuzzy_score = self._best_fuzzy(normalised)
        if best_fuzzy_score >= self._fuzzy_threshold_100:
            return Ingredient(canonical_name=best_fuzzy_name, raw_text=raw_text)

        # --- Stage 3: semantic match ---
        best_sem_name, best_sem_score = self._best_semantic(normalised)
        if best_sem_score >= self._semantic_threshold:
            return Ingredient(canonical_name=best_sem_name, raw_text=raw_text)

        return None

    # ------------------------------------------------------------------ #
    # Private helpers                                                      #
    # ------------------------------------------------------------------ #

    def _best_fuzzy(self, normalised: str) -> tuple[str, float]:
        """Return the (name, ratio_score) pair with the highest fuzz.ratio."""
        best_name = self._names[0]
        best_score = 0.0
        for name in self._names:
            score = fuzz.ratio(normalised, name)
            if score > best_score:
                best_score = score
                best_name = name
        return best_name, best_score

    def _best_semantic(self, normalised: str) -> tuple[str, float]:
        """Embed *normalised* and return the (name, cosine) pair with the highest similarity."""
        q_emb = self._embed_fn([normalised])  # shape (1, 1024)
        # L2-normalise query
        q_norm = np.linalg.norm(q_emb, axis=1, keepdims=True)
        q_norm = np.where(q_norm == 0, 1.0, q_norm)
        q_unit = (q_emb / q_norm).astype(np.float32)  # (1, 1024)
        # Cosines via dot product (vocab embeddings are pre-normalised)
        cosines: np.ndarray = (self._embs @ q_unit.T).squeeze(axis=1)  # (N,)
        best_idx = int(np.argmax(cosines))
        return self._names[best_idx], float(cosines[best_idx])


# ---------------------------------------------------------------------------
# Module-level singleton + convenience function
# ---------------------------------------------------------------------------

_default_matcher: Matcher | None = None
_default_lock = threading.Lock()


def _get_default_matcher() -> Matcher:
    """Lazily build and cache the default Matcher from the built-in mini-vocab."""
    global _default_matcher
    if _default_matcher is not None:
        return _default_matcher
    with _default_lock:
        if _default_matcher is not None:
            return _default_matcher
        from epicure_core.embeddings import embed
        from epicure_core.pantry._default_vocab import DEFAULT_VOCAB_NAMES

        embeddings = embed(DEFAULT_VOCAB_NAMES)
        _default_matcher = Matcher(
            canonical_names=DEFAULT_VOCAB_NAMES,
            embeddings=embeddings,
        )
        return _default_matcher


def resolve(raw_text: str) -> Ingredient | None:
    """Module-level convenience wrapper around the default Matcher.

    Builds a ``Matcher`` from the built-in 15-word mini-vocab on first call
    (~30-60 s on Pi due to bge-m3 ONNX load; instant after).

    **For production use**, construct your own ``Matcher`` with the full
    T-008 parquet vocab instead of calling this function.

    Args:
        raw_text: Raw ingredient string to resolve.

    Returns:
        ``Ingredient`` or ``None`` (no match).
    """
    return _get_default_matcher().resolve(raw_text)
