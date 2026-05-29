# tests/navigator/test_kitchen_store.py
from __future__ import annotations

import json
from datetime import date
from pathlib import Path

import pytest

from pantryatlas.pantry.models import Ingredient as Ing
from pantryatlas.pantry.models import Quantity as Qty
from pantryatlas.store.kitchen import KitchenStore


def test_open_creates_tables(tmp_path: Path) -> None:
    store = KitchenStore(tmp_path / "kitchen.db")
    names = {
        r[0]
        for r in store._conn.execute(
            "SELECT name FROM sqlite_master WHERE type='table'"
        ).fetchall()
    }
    assert {
        "pantry_items", "inventory_events", "cook_events", "off_cache", "devices"
    } <= names


def test_migrates_from_pantry_json_once(tmp_path: Path) -> None:
    pj = tmp_path / "pantry.json"
    pj.write_text(
        json.dumps(
            [
                {"canonical_name": "garlic", "raw_text": "2 cloves garlic",
                 "quantity": {"amount": 2.0, "unit": "cloves"},
                 "expires_at": "2026-06-15"},
                {"canonical_name": "tomato", "raw_text": "tomato"},
            ]
        ),
        encoding="utf-8",
    )
    store = KitchenStore(tmp_path / "kitchen.db", pantry_json_path=pj)
    items = {i["canonical_name"]: i for i in store.list_items()}
    assert set(items) == {"garlic", "tomato"}
    assert items["garlic"]["state"] == "present"
    assert items["garlic"]["confidence"] == 1.0
    assert items["garlic"]["source"] == "manual"
    assert items["garlic"]["quantity"] == {"amount": 2.0, "unit": "cloves"}
    assert items["garlic"]["expires_at"] == "2026-06-15"
    # one 'add' ledger row per imported item, tagged source='migration'
    rows = store._conn.execute(
        "SELECT change_type, source FROM inventory_events"
    ).fetchall()
    assert sorted(rows) == [("add", "migration"), ("add", "migration")]
    # json renamed (non-destructive), so re-init is a no-op
    assert not pj.exists()
    assert (tmp_path / "pantry.json.imported").exists()


def test_migration_skips_malformed_json(tmp_path: Path) -> None:
    # Case 1: list with one good item and one malformed item (missing canonical_name).
    pj = tmp_path / "pantry.json"
    pj.write_text(
        json.dumps(
            [
                {"canonical_name": "garlic", "raw_text": "garlic"},
                {"raw_text": "missing canonical_name field"},  # malformed — no canonical_name
            ]
        ),
        encoding="utf-8",
    )
    store = KitchenStore(tmp_path / "kitchen.db", pantry_json_path=pj)
    items = [i["canonical_name"] for i in store.list_items()]
    assert items == ["garlic"], "Good item should be imported"
    assert not pj.exists(), "pantry.json should be renamed"
    assert (tmp_path / "pantry.json.imported").exists()

    # Case 2: top-level JSON is an object → store opens empty, json renamed, no crash.
    db2 = tmp_path / "kitchen2.db"
    pj2 = tmp_path / "pantry2.json"
    pj2.write_text(json.dumps({"not": "a list"}), encoding="utf-8")
    store2 = KitchenStore(db2, pantry_json_path=pj2)
    assert store2.list_items() == [], "Store should be empty for non-list JSON"
    assert not pj2.exists(), "pantry2.json should be renamed"
    assert (tmp_path / "pantry2.json.imported").exists()


def test_migration_is_idempotent(tmp_path: Path) -> None:
    pj = tmp_path / "pantry.json"
    pj.write_text(json.dumps([{"canonical_name": "salt", "raw_text": "salt"}]), encoding="utf-8")
    db = tmp_path / "kitchen.db"
    KitchenStore(db, pantry_json_path=pj)
    # second open: pantry.json is gone, table already populated → no duplicate
    store2 = KitchenStore(db, pantry_json_path=pj)
    assert len(store2.list_items()) == 1


# ---------------------------------------------------------------------------
# Task 2: pantry CRUD + ledger + on-hand
# ---------------------------------------------------------------------------


def test_add_remove_and_ledger(tmp_path: Path) -> None:
    store = KitchenStore(tmp_path / "kitchen.db")
    store.add_item(Ing(canonical_name="garlic", raw_text="garlic"))
    store.add_item(Ing(canonical_name="onion", raw_text="onion",
                       quantity=Qty(1.0, "bulb"), expires_at=date(2026, 6, 1)))
    assert {i["canonical_name"] for i in store.list_items()} == {"garlic", "onion"}
    store.remove_item("garlic")
    assert {i["canonical_name"] for i in store.list_items()} == {"onion"}
    kinds = [r[0] for r in store._conn.execute(
        "SELECT change_type FROM inventory_events ORDER BY id").fetchall()]
    assert kinds == ["add", "add", "adjust"]


def test_on_hand_excludes_used_up(tmp_path: Path) -> None:
    store = KitchenStore(tmp_path / "kitchen.db")
    store.add_item(Ing(canonical_name="garlic", raw_text="garlic"))
    store.add_item(Ing(canonical_name="basil", raw_text="basil"))
    store._conn.execute("UPDATE pantry_items SET state='used_up' WHERE canonical_name='basil'")
    store._conn.commit()
    pantry = store.on_hand()
    names = {ing.canonical_name for ing in pantry}
    assert names == {"garlic"}
    assert "basil" not in pantry


def test_replace_all(tmp_path: Path) -> None:
    store = KitchenStore(tmp_path / "kitchen.db")
    store.add_item(Ing(canonical_name="garlic", raw_text="garlic"))
    store.replace_all([Ing(canonical_name="tomato", raw_text="tomato"),
                       Ing(canonical_name="basil", raw_text="basil")])
    assert {i["canonical_name"] for i in store.list_items()} == {"tomato", "basil"}


# ---------------------------------------------------------------------------
# Task 3: coarse consume transitions
# ---------------------------------------------------------------------------


@pytest.mark.parametrize(
    "start_state, coarse, end_state, end_conf, change_type",
    [
        ("present", "half", "low", 0.5, "consume"),
        ("low", "half", "low", 0.5, "consume"),
        ("used_up", "half", "used_up", 0.0, "consume"),  # used_up stays used_up, not 0.5
        ("present", "used_up", "used_up", 0.0, "consume"),
        ("present", "discarded", "used_up", 0.0, "discard"),
        ("present", "cook", "low", 0.5, "consume"),     # tap-to-cook default: one notch
        ("low", "cook", "used_up", 0.0, "consume"),
    ],
)
def test_consume_transitions(tmp_path, start_state, coarse, end_state, end_conf, change_type):
    store = KitchenStore(tmp_path / "kitchen.db")
    store.add_item(Ing(canonical_name="garlic", raw_text="garlic"))
    store._conn.execute(
        "UPDATE pantry_items SET state=?, confidence=1.0 WHERE canonical_name='garlic'",
        (start_state,),
    )
    store._conn.commit()
    store.consume_item("garlic", coarse, source="manual")
    item = store.get_item("garlic")
    assert item["state"] == end_state
    assert item["confidence"] == end_conf
    last = store._conn.execute(
        "SELECT change_type FROM inventory_events ORDER BY id DESC LIMIT 1").fetchone()[0]
    assert last == change_type


def test_consume_missing_item_is_noop(tmp_path):
    store = KitchenStore(tmp_path / "kitchen.db")
    assert store.consume_item("ghost", "used_up") is None


def test_restore_item(tmp_path):
    store = KitchenStore(tmp_path / "kitchen.db")
    store.add_item(Ing(canonical_name="garlic", raw_text="garlic"))
    store.consume_item("garlic", "used_up")
    store.restore_item("garlic")
    item = store.get_item("garlic")
    assert item["state"] == "present" and item["confidence"] == 1.0
    last = store._conn.execute(
        "SELECT change_type FROM inventory_events ORDER BY id DESC LIMIT 1").fetchone()[0]
    assert last == "observe"


# ---------------------------------------------------------------------------
# Task 4: cook events + soft-decrement + meals
# ---------------------------------------------------------------------------

def test_cook_event_logs_and_decrements(tmp_path):
    store = KitchenStore(tmp_path / "kitchen.db")
    for n in ("garlic", "tomato", "basil"):
        store.add_item(Ing(canonical_name=n, raw_text=n))
    event = store.add_cook_event(
        dish_name="Pasta al pomodoro", servings=2, recipe_id="r1",
        consumed=[{"canonical_name": "garlic", "coarse_amount": "cook"},
                  {"canonical_name": "tomato", "coarse_amount": "cook"},
                  {"canonical_name": "ghost", "coarse_amount": "cook"}],  # not on hand
    )
    assert event["dish_name"] == "Pasta al pomodoro"
    assert event["id"] >= 1
    assert event["matched"] == ["garlic", "tomato"]
    assert event["unmatched"] == ["ghost"]
    # garlic + tomato dropped one notch; basil untouched
    items = {i["canonical_name"]: i for i in store.list_items()}
    assert items["garlic"]["state"] == "low"
    assert items["tomato"]["state"] == "low"
    assert items["basil"]["state"] == "present"


def test_cook_event_with_no_matches_still_logs(tmp_path):
    store = KitchenStore(tmp_path / "kitchen.db")
    event = store.add_cook_event(dish_name="Mystery stew", consumed=[])
    assert event["id"] >= 1
    assert store.list_meals()[0]["dish_name"] == "Mystery stew"


def test_list_meals_newest_first(tmp_path):
    store = KitchenStore(tmp_path / "kitchen.db")
    store.add_cook_event(dish_name="First", consumed=[])
    store.add_cook_event(dish_name="Second", consumed=[])
    meals = store.list_meals(limit=10)
    assert [m["dish_name"] for m in meals] == ["Second", "First"]


# ---------------------------------------------------------------------------
# Task 5: waste tally
# ---------------------------------------------------------------------------

def test_waste_tally_counts_discards_and_expires(tmp_path):
    store = KitchenStore(tmp_path / "kitchen.db")
    for n in ("milk", "bread", "eggs"):
        store.add_item(Ing(canonical_name=n, raw_text=n))
    store.consume_item("milk", "discarded")      # discard
    store.consume_item("bread", "used_up")        # consume — NOT waste
    store.mark_expired("eggs")                     # expire
    tally = store.waste_tally(window_days=30)
    assert tally["discarded"] == 1
    assert tally["expired"] == 1
    assert tally["total"] == 2
    assert set(tally["items"]) == {"milk", "eggs"}


def test_cook_event_discarded_counts_as_waste(tmp_path):
    store = KitchenStore(tmp_path / "kitchen.db")
    store.add_item(Ing(canonical_name="milk", raw_text="milk"))
    store.add_item(Ing(canonical_name="butter", raw_text="butter"))

    # "discarded" consumed item must count as waste + reach used_up state
    store.add_cook_event(
        dish_name="Discard Test",
        consumed=[{"canonical_name": "milk", "coarse_amount": "discarded"}],
    )
    tally = store.waste_tally(window_days=30)
    assert tally["discarded"] == 1, "cook-event discard should count as waste"
    assert store.get_item("milk")["state"] == "used_up"

    # "cook"-default consumed item must NOT count as waste
    store.add_cook_event(
        dish_name="Normal Cook",
        consumed=[{"canonical_name": "butter", "coarse_amount": "cook"}],
    )
    tally2 = store.waste_tally(window_days=30)
    assert tally2["discarded"] == 1, "cook-default should not add to waste tally"


# ---------------------------------------------------------------------------
# SP-B Task 2: off_cache round-trip
# ---------------------------------------------------------------------------


def test_off_cache_round_trip(tmp_path):
    store = KitchenStore(tmp_path / "kitchen.db")
    assert store.get_cached_off("123") is None
    store.cache_off("123", {
        "product_name": "Rice Noodles", "ingredients_tags": ["en:rice-noodles"],
    })
    cached = store.get_cached_off("123")
    assert cached["product_name"] == "Rice Noodles"
    # overwrite is idempotent (cache-through on re-fetch)
    store.cache_off("123", {"product_name": "Rice Noodles v2"})
    assert store.get_cached_off("123")["product_name"] == "Rice Noodles v2"


# ---------------------------------------------------------------------------
# SP-C Task 2: devices registry
# ---------------------------------------------------------------------------


def test_device_enroll_approve_verify_flow(tmp_path):
    store = KitchenStore(tmp_path / "kitchen.db")
    dev = store.enroll_device("Counter Pi", "sensor", kind="pi-cam", caps=["camera"])
    assert dev["status"] == "pending"
    assert dev["device_id"]
    assert "token_hash" not in dev          # never leaked
    assert dev["caps"] == ["camera"]
    # pending → not findable by token
    assert store.device_by_token_hash("deadbeef") is None
    # approve stores a hash; paired
    approved = store.approve_device(dev["device_id"], "hash123")
    assert approved["status"] == "paired" and approved["paired_at"]
    # findable by the exact hash, and only when paired
    found = store.device_by_token_hash("hash123")
    assert found is not None and found["device_id"] == dev["device_id"]
    assert found["last_seen"]               # verify bumped last_seen
    # list never leaks token_hash
    assert all("token_hash" not in d for d in store.list_devices())


def test_device_reject_and_remove(tmp_path):
    store = KitchenStore(tmp_path / "kitchen.db")
    dev = store.enroll_device("X", "compute")
    store.approve_device(dev["device_id"], "h")
    assert store.reject_device(dev["device_id"])["status"] == "rejected"
    assert store.device_by_token_hash("h") is None   # rejected token no longer verifies
    assert store.remove_device(dev["device_id"]) is True
    assert store.get_device(dev["device_id"]) is None
    assert store.reject_device("ghost") is None
    assert store.remove_device("ghost") is False


# ---------------------------------------------------------------------------
# Star Slice 1 Task 1: set_expiry
# ---------------------------------------------------------------------------


def test_set_expiry_sets_and_clears(tmp_path):
    from datetime import date
    store = KitchenStore(tmp_path / "kitchen.db")
    store.add_item(Ing(canonical_name="milk", raw_text="milk"))

    # Set a date — stored as pure YYYY-MM-DD
    item = store.set_expiry("milk", date(2099, 1, 2))
    assert item is not None
    assert item["expires_at"] == "2099-01-02"

    # Clear the date — expires_at drops out of the dict
    item = store.set_expiry("milk", None)
    assert item is not None
    assert "expires_at" not in item


def test_set_expiry_unknown_item_returns_none(tmp_path):
    from datetime import date
    store = KitchenStore(tmp_path / "kitchen.db")
    assert store.set_expiry("ghost", date(2099, 1, 1)) is None


def test_set_expiry_event_is_not_waste(tmp_path):
    from datetime import date
    store = KitchenStore(tmp_path / "kitchen.db")
    store.add_item(Ing(canonical_name="milk", raw_text="milk"))
    store.set_expiry("milk", date(2099, 1, 1))
    tally = store.waste_tally(window_days=30)
    assert tally["total"] == 0  # set_expiry must never count as waste


# ---------------------------------------------------------------------------
# Star Slice 1 Task 2: double-count guards (waste invariant)
# ---------------------------------------------------------------------------


def test_mark_expired_is_idempotent(tmp_path):
    store = KitchenStore(tmp_path / "kitchen.db")
    store.add_item(Ing(canonical_name="eggs", raw_text="eggs"))
    store.mark_expired("eggs")   # first: present -> used_up, logs expire
    store.mark_expired("eggs")   # second: already used_up -> no-op, no log
    tally = store.waste_tally(window_days=30)
    assert tally["expired"] == 1, "a second mark_expired must not double-count"
    assert tally["total"] == 1


def test_discard_does_not_double_count_when_already_used_up(tmp_path):
    store = KitchenStore(tmp_path / "kitchen.db")
    store.add_item(Ing(canonical_name="milk", raw_text="milk"))
    store.consume_item("milk", "discarded")  # present -> used_up, logs discard
    store.consume_item("milk", "discarded")  # already used_up -> no extra discard
    tally = store.waste_tally(window_days=30)
    assert tally["discarded"] == 1, "a second discard on a used_up item must not double-count"
    assert tally["total"] == 1
