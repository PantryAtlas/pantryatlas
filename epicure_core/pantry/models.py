"""Pantry dataclasses: Quantity, Ingredient, Pantry.

These are pure Python dataclasses — no I/O, no embeddings.  The embedding
and matching logic lives in ``epicure_core.pantry.matcher``.

Deduplication
-------------
``Pantry`` stores ingredients keyed by ``canonical_name``.  A second
``add()`` for the same canonical name replaces the previous entry (so callers
can update quantity or expiry without explicit remove + re-add).
"""

from __future__ import annotations

from dataclasses import dataclass, field
from datetime import date, timedelta


@dataclass
class Quantity:
    """An amount + optional unit, e.g. ``Quantity(amount=2.0, unit='cloves')``."""

    amount: float
    unit: str = ""

    def __str__(self) -> str:
        if self.unit:
            return f"{self.amount} {self.unit}"
        return str(self.amount)


@dataclass
class Ingredient:
    """A single resolved ingredient.

    Attributes:
        canonical_name: Normalised name from the vocab (lower-case,
            singular, English or the primary language of the vocab in use).
        raw_text: The original string the user typed before resolution.
        quantity: Optional amount + unit.
        expires_at: Optional expiry date.  ``None`` means "no expiry
            recorded" (e.g. dry pantry staples).
    """

    canonical_name: str
    raw_text: str
    quantity: Quantity | None = None
    expires_at: date | None = None


@dataclass
class Pantry:
    """An in-memory pantry that deduplicates by canonical ingredient name.

    Internal storage is a ``dict`` keyed by ``canonical_name`` so that a
    second ``add()`` call for the same canonical name replaces the first.

    Usage::

        pantry = Pantry()
        pantry.add(Ingredient(canonical_name="garlic", raw_text="garlic"))
        pantry.add(Ingredient(canonical_name="garlic", raw_text="2 heads garlic",
                              quantity=Quantity(2.0, "heads")))
        assert len(pantry) == 1  # only the latest entry kept
    """

    _store: dict[str, Ingredient] = field(default_factory=dict, init=False, repr=False)

    # ------------------------------------------------------------------ #
    # Mutation                                                             #
    # ------------------------------------------------------------------ #

    def add(self, ingredient: Ingredient) -> None:
        """Add or replace an ingredient (keyed by canonical_name)."""
        self._store[ingredient.canonical_name] = ingredient

    def remove(self, canonical_name: str) -> None:
        """Remove an ingredient by canonical name (no-op if not present)."""
        self._store.pop(canonical_name, None)

    # ------------------------------------------------------------------ #
    # Queries                                                              #
    # ------------------------------------------------------------------ #

    def expiring_within(self, days: int) -> list[Ingredient]:
        """Return ingredients whose expiry falls within the next *days* days.

        Items with ``expires_at=None`` are excluded.  Items that are already
        past their expiry date ARE included (they are within ``days`` days,
        in the sense that they need attention now).

        Args:
            days: Look-ahead window in calendar days (inclusive boundary).

        Returns:
            List of ingredients with ``expires_at <= date.today() + timedelta(days)``.
        """
        cutoff = date.today() + timedelta(days=days)
        return [
            ing
            for ing in self._store.values()
            if ing.expires_at is not None and ing.expires_at <= cutoff
        ]

    def __len__(self) -> int:
        return len(self._store)

    def __iter__(self):  # type: ignore[override]
        return iter(self._store.values())

    def __contains__(self, canonical_name: str) -> bool:
        return canonical_name in self._store
