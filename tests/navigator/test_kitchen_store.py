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
