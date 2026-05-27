"""Tests for Pantry / Ingredient / Quantity dataclasses.

Covers AC-8 (expiry filter) and AC-9 (deduplication).
"""

from __future__ import annotations

from datetime import date, timedelta

from pantryatlas.pantry import Ingredient, Pantry, Quantity

# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------


def _make_ingredient(
    name: str,
    days_until_expiry: int | None = None,
) -> Ingredient:
    """Build an Ingredient with an optional relative expiry."""
    expires_at: date | None = None
    if days_until_expiry is not None:
        expires_at = date.today() + timedelta(days=days_until_expiry)
    return Ingredient(canonical_name=name, raw_text=name, expires_at=expires_at)


# ---------------------------------------------------------------------------
# AC-8: expiring_within filter
# ---------------------------------------------------------------------------


class TestExpiringWithin:
    """AC-8: Pantry with 3 ingredients — 1 expiring in 1 day, 1 in 3 days, 1 with no expiry."""

    def test_expiring_within_2_days_returns_one(self) -> None:
        pantry = Pantry()
        pantry.add(_make_ingredient("garlic", days_until_expiry=1))   # within window
        pantry.add(_make_ingredient("onion", days_until_expiry=3))    # outside window
        pantry.add(_make_ingredient("tomato", days_until_expiry=None))  # no expiry

        expiring = pantry.expiring_within(days=2)

        assert len(expiring) == 1
        assert expiring[0].canonical_name == "garlic"

    def test_expiring_within_includes_today(self) -> None:
        """Items expiring today (days_until_expiry=0) are within any positive window."""
        pantry = Pantry()
        pantry.add(_make_ingredient("butter", days_until_expiry=0))

        assert len(pantry.expiring_within(days=1)) == 1

    def test_expiring_within_excludes_no_expiry(self) -> None:
        pantry = Pantry()
        pantry.add(_make_ingredient("salt", days_until_expiry=None))

        assert len(pantry.expiring_within(days=30)) == 0

    def test_expiring_within_boundary_inclusive(self) -> None:
        """Item expiring in exactly N days is included (boundary is inclusive)."""
        pantry = Pantry()
        pantry.add(_make_ingredient("milk", days_until_expiry=2))

        assert len(pantry.expiring_within(days=2)) == 1

    def test_expiring_within_boundary_exclusive(self) -> None:
        """Item expiring in N+1 days is NOT included."""
        pantry = Pantry()
        pantry.add(_make_ingredient("egg", days_until_expiry=3))

        assert len(pantry.expiring_within(days=2)) == 0


# ---------------------------------------------------------------------------
# AC-9: deduplication
# ---------------------------------------------------------------------------


class TestPantryDedup:
    """AC-9: add() followed by add() of same canonical_name keeps only 1 entry."""

    def test_duplicate_add_keeps_one_entry(self) -> None:
        pantry = Pantry()
        ing1 = Ingredient(canonical_name="garlic", raw_text="garlic")
        ing2 = Ingredient(
            canonical_name="garlic",
            raw_text="3 cloves garlic",
            quantity=Quantity(3.0, "cloves"),
        )

        pantry.add(ing1)
        pantry.add(ing2)

        assert len(pantry) == 1

    def test_duplicate_add_replaces_with_latest(self) -> None:
        """Second add() replaces the first — allows quantity/expiry updates."""
        pantry = Pantry()
        ing1 = Ingredient(canonical_name="garlic", raw_text="garlic")
        ing2 = Ingredient(
            canonical_name="garlic",
            raw_text="fresh garlic",
            quantity=Quantity(2.0, "heads"),
        )

        pantry.add(ing1)
        pantry.add(ing2)

        stored = list(pantry)[0]
        assert stored.raw_text == "fresh garlic"
        assert stored.quantity is not None
        assert stored.quantity.amount == 2.0

    def test_different_names_kept_separately(self) -> None:
        pantry = Pantry()
        pantry.add(Ingredient(canonical_name="garlic", raw_text="garlic"))
        pantry.add(Ingredient(canonical_name="onion", raw_text="onion"))

        assert len(pantry) == 2

    def test_remove_reduces_count(self) -> None:
        pantry = Pantry()
        pantry.add(Ingredient(canonical_name="garlic", raw_text="garlic"))
        pantry.remove("garlic")

        assert len(pantry) == 0

    def test_remove_nonexistent_is_noop(self) -> None:
        pantry = Pantry()
        pantry.remove("nonexistent")  # must not raise

        assert len(pantry) == 0


# ---------------------------------------------------------------------------
# Quantity
# ---------------------------------------------------------------------------


class TestQuantity:
    def test_str_with_unit(self) -> None:
        q = Quantity(2.0, "cups")
        assert str(q) == "2.0 cups"

    def test_str_without_unit(self) -> None:
        q = Quantity(3.0)
        assert str(q) == "3.0"
