# tests/navigator/test_kitchen_store.py
from __future__ import annotations

import json
from datetime import date
from pathlib import Path

from pantryatlas.store.kitchen import KitchenStore


def test_open_creates_tables(tmp_path: Path) -> None:
    store = KitchenStore(tmp_path / "kitchen.db")
    names = {
        r[0]
        for r in store._conn.execute(
            "SELECT name FROM sqlite_master WHERE type='table'"
        ).fetchall()
    }
    assert {"pantry_items", "inventory_events", "cook_events"} <= names


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
from pantryatlas.pantry.models import Ingredient as Ing, Quantity as Qty


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
