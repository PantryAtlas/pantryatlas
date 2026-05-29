"""Cook-history → bounded ranking adjustment (slice 4).

Pure and time-free: callers inject ``now``. Builds, per normalized dish title, a
small additive score nudge that demotes recently-cooked dishes and boosts
highly-rated ones. A title with no cook events yields exactly ``0.0`` so ranking
is byte-identical to no-history behavior.
"""
from __future__ import annotations

from collections.abc import Callable
from datetime import datetime

_RECENCY_WINDOW_DAYS: int = 14
_MAX_PENALTY: float = 0.05
_MAX_BOOST: float = 0.05
_MAX_ADJUST: float = 0.05


def normalize_title(s: str) -> str:
    """Lowercase + collapse internal whitespace (the cook-event join key)."""
    return " ".join(s.lower().split())


def _clamp(x: float, lo: float, hi: float) -> float:
    return lo if x < lo else hi if x > hi else x


def build_history_adjuster(
    cook_events: list[dict],
    now: datetime,
    *,
    window_days: int = _RECENCY_WINDOW_DAYS,
    max_penalty: float = _MAX_PENALTY,
    max_boost: float = _MAX_BOOST,
    max_adjust: float = _MAX_ADJUST,
) -> Callable[[str], float]:
    """Return ``title -> adjustment`` in ``[-max_adjust, +max_adjust]``.

    Pure given ``now``. Per normalized title: recency penalty from the most-recent
    ``cooked_at`` (full ``max_penalty`` if cooked now, 0 at/after ``window_days``),
    and a rating term from the mean of *rated* cooks (5 -> +max_boost, 3 -> 0,
    1 -> -max_boost). Unparseable/missing ``cooked_at`` contributes no penalty but
    its rating still counts. Titles with no events map to ``0.0``.
    """
    # title -> [min_days_ago_or_None, sum_rating, n_rated]
    agg: dict[str, list] = {}
    for ev in cook_events:
        title = normalize_title(str(ev.get("dish_name", "")))
        if not title:
            continue
        slot = agg.setdefault(title, [None, 0.0, 0])
        raw = ev.get("cooked_at")
        days: float | None = None
        if isinstance(raw, str):
            try:
                cooked = datetime.fromisoformat(raw)
                days = max(0.0, (now - cooked).total_seconds() / 86400.0)
            except ValueError:
                days = None
        if days is not None and (slot[0] is None or days < slot[0]):
            slot[0] = days
        rating = ev.get("rating")
        if isinstance(rating, (int, float)) and rating is not None:
            slot[1] += float(rating)
            slot[2] += 1

    adjustments: dict[str, float] = {}
    for title, (min_days, sum_rating, n_rated) in agg.items():
        if min_days is None:
            recency_penalty = 0.0
        else:
            recency_penalty = max_penalty * _clamp(
                (window_days - min_days) / window_days, 0.0, 1.0
            )
        if n_rated:
            mean = sum_rating / n_rated
            rating_term = max_boost * _clamp((mean - 3.0) / 2.0, -1.0, 1.0)
        else:
            rating_term = 0.0
        adjustments[title] = _clamp(rating_term - recency_penalty, -max_adjust, max_adjust)

    def adjuster(title: str) -> float:
        return adjustments.get(normalize_title(title), 0.0)

    return adjuster
