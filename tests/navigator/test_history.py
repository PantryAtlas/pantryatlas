# tests/navigator/test_history.py
from __future__ import annotations

from datetime import UTC, datetime, timedelta

from pantryatlas.navigator.history import build_history_adjuster, normalize_title

NOW = datetime(2026, 5, 29, 12, 0, 0, tzinfo=UTC)


def _evt(title, *, days_ago=0.0, rating=None):
    cooked = (NOW - timedelta(days=days_ago)).isoformat()
    return {"dish_name": title, "cooked_at": cooked, "rating": rating}


def test_normalize_title_collapses_case_and_space():
    assert normalize_title("Beef Tacos") == normalize_title("  beef   tacos ")


def test_empty_history_is_noop():
    adj = build_history_adjuster([], NOW)
    assert adj("anything") == 0.0


def test_recency_cooked_now_full_penalty_no_rating():
    adj = build_history_adjuster([_evt("Stew", days_ago=0.0)], NOW)
    assert adj("Stew") == -0.05  # full max_penalty, no rating term


def test_recency_decays_to_zero_at_window():
    adj = build_history_adjuster([_evt("Stew", days_ago=14.0)], NOW)
    assert abs(adj("Stew")) < 1e-9


def test_recency_beyond_window_zero():
    adj = build_history_adjuster([_evt("Stew", days_ago=30.0)], NOW)
    assert adj("Stew") == 0.0


def test_rating_five_old_is_full_boost():
    adj = build_history_adjuster([_evt("Cake", days_ago=30.0, rating=5)], NOW)
    assert abs(adj("Cake") - 0.05) < 1e-9


def test_rating_one_old_is_full_penalty():
    adj = build_history_adjuster([_evt("Gruel", days_ago=30.0, rating=1)], NOW)
    assert abs(adj("Gruel") - (-0.05)) < 1e-9


def test_rating_three_is_neutral():
    adj = build_history_adjuster([_evt("Meh", days_ago=30.0, rating=3)], NOW)
    assert abs(adj("Meh")) < 1e-9


def test_unrated_contributes_no_rating_term():
    adj = build_history_adjuster([_evt("Plain", days_ago=30.0, rating=None)], NOW)
    assert adj("Plain") == 0.0


def test_combined_clamped_to_max_adjust():
    # 5-star cooked today: boost(+0.05) - penalty(0.05) = 0.0, still within clamp
    adj = build_history_adjuster([_evt("Fave", days_ago=0.0, rating=5)], NOW)
    assert abs(adj("Fave")) < 1e-9


def test_mean_rating_over_multiple_cooks():
    evts = [_evt("Soup", days_ago=30.0, rating=5), _evt("Soup", days_ago=30.0, rating=1)]
    adj = build_history_adjuster(evts, NOW)  # mean 3 -> neutral
    assert abs(adj("Soup")) < 1e-9


def test_unparseable_cooked_at_no_penalty_keeps_rating():
    evts = [{"dish_name": "X", "cooked_at": "not-a-date", "rating": 5}]
    adj = build_history_adjuster(evts, NOW)
    assert abs(adj("X") - 0.05) < 1e-9  # no recency, full boost


def test_title_match_is_normalized():
    adj = build_history_adjuster([_evt("Beef Tacos", days_ago=0.0)], NOW)
    assert adj("  BEEF   tacos ") == -0.05
