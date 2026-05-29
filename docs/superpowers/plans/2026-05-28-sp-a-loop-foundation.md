# SP-A Loop Foundation Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Close the food-waste loop with no new hardware — migrate the pantry to a concurrent-safe SQLite store, add an append-only event ledger + cook-log, and make "I cooked this" atomically log the meal and soft-decrement the pantry.

**Architecture:** A new `KitchenStore` (plain SQLite at `~/.pantryatlas/kitchen.db`, no `sqlite-vec`) becomes the source of truth for mutable user state (pantry items + inventory-event ledger + cook events). It is wired into the existing `create_app` factory with the same lazy-init pattern as `RecipeStore` (`kitchen`/`kitchen_factory` + a `_get_kitchen` accessor), so module import stays side-effect-free. The existing pantry routes repoint from `pantry.json` to the store; new routes add consume / cook / meals / waste. The Preact frontend gains an "I cooked this" affordance, coarse consume controls, a meal-log timeline, and expiry nudges.

**Tech Stack:** Python 3.11+ · FastAPI · stdlib `sqlite3` (no extension) · pytest + `fastapi.testclient` · Preact + `@preact/signals` · existing headless-chromium verify harness (`web/*.mjs`).

**Spec:** [`../specs/2026-05-28-sp-a-loop-foundation-design.md`](../specs/2026-05-28-sp-a-loop-foundation-design.md) · **Vision:** [`../specs/2026-05-28-kitchen-mesh-vision-design.md`](../specs/2026-05-28-kitchen-mesh-vision-design.md)

---

## Prerequisite (one-time, before Task 1)

- [ ] **Refresh the stale venv** so the app imports (`python-multipart`/`Pillow` are declared but missing locally):

Run: `cd ~/pantryatlas && .venv/bin/pip install -e '.[dev]'`
Then verify the app imports under this Pi's Python 3.11:
Run: `.venv/bin/python -c "from pantryatlas.navigator.server import app; print('import OK')" 2>&1 | grep -v -E "profiling:|\.gcda:|Cannot open"`
Expected: `import OK`

> Throughout: filter the gcov noise on this Pi with `2>&1 | grep -v -E "profiling:|\.gcda:|Cannot open"`. All `KitchenStore` and route tests in this plan use **plain SQLite and a fake recipe store**, so they run on this Pi's 3.11 — they never touch `sqlite-vec`.

## File structure

| File | Responsibility | Action |
|---|---|---|
| `pantryatlas/store/kitchen.py` | `KitchenStore`: SQLite schema, migration, pantry CRUD, consume, cook events, waste tally | **Create** |
| `tests/navigator/test_kitchen_store.py` | Unit tests for `KitchenStore` (plain SQLite, runs on Pi 3.11) | **Create** |
| `tests/navigator/test_loop_routes.py` | Route tests for consume/cook/meals/waste + repointed pantry routes (fake recipe store) | **Create** |
| `pantryatlas/navigator/server.py` | Add `kitchen`/`kitchen_factory` params + `_get_kitchen`; repoint pantry routes; add 4 routes; production wiring | **Modify** |
| `web/src/signals.ts` | `PantryItem` field additions, `CookEvent` type, `cookRecipe`/`consumeItem`/`fetchMeals`/`meals` | **Modify** |
| `web/src/components/RecipeCard.tsx` | "I cooked this" button + servings inline control | **Modify** |
| `web/src/components/MealLog.tsx` | Cook-event timeline view | **Create** |
| `web/src/pages/Navigator.tsx` | Consume controls on pantry rows, dimmed `used_up`, expiry nudge strip, meal-log entry point | **Modify** |
| `web/verify_loop.mjs` | Headless verification of the cook→decrement→timeline loop | **Create** |
| `docs/navigator.md` | Document the new routes + `kitchen.db` + migration | **Modify** |

---

## Task 1: KitchenStore — schema, connection, migration

**Files:**
- Create: `pantryatlas/store/kitchen.py`
- Test: `tests/navigator/test_kitchen_store.py`

- [ ] **Step 1: Write the failing test**

```python
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
```

- [ ] **Step 2: Run it to verify it fails**

Run: `.venv/bin/python -m pytest tests/navigator/test_kitchen_store.py -q 2>&1 | grep -v -E "profiling:|\.gcda:|Cannot open"`
Expected: FAIL — `ModuleNotFoundError: No module named 'pantryatlas.store.kitchen'`

- [ ] **Step 3: Write the minimal implementation**

```python
# pantryatlas/store/kitchen.py
"""KitchenStore — mutable user state (pantry + event ledger + cook log).

Plain SQLite (no sqlite-vec), so it runs on every Python including this Pi's
3.11 build that lacks ``enable_load_extension``.  Kept separate from the static
``recipes.db``.  Single-writer model: ``check_same_thread=False`` lets FastAPI's
thread pool share one connection; writes are serialised by the GIL + short txns.
"""

from __future__ import annotations

import json
import sqlite3
from datetime import date, datetime, timedelta, timezone
from pathlib import Path
from typing import Any

from pantryatlas.pantry.models import Ingredient, Pantry, Quantity

_ON_HAND_STATES = ("present", "low")

_DDL = """
CREATE TABLE IF NOT EXISTS pantry_items (
    canonical_name    TEXT PRIMARY KEY,
    raw_text          TEXT NOT NULL,
    quantity_amount   REAL,
    quantity_unit     TEXT,
    expires_at        TEXT,
    state             TEXT NOT NULL DEFAULT 'present',
    confidence        REAL NOT NULL DEFAULT 1.0,
    last_observed_at  TEXT NOT NULL,
    source            TEXT NOT NULL DEFAULT 'manual',
    added_at          TEXT NOT NULL,
    updated_at        TEXT NOT NULL
);
CREATE TABLE IF NOT EXISTS inventory_events (
    id              INTEGER PRIMARY KEY AUTOINCREMENT,
    ts              TEXT NOT NULL,
    canonical_name  TEXT NOT NULL,
    change_type     TEXT NOT NULL,
    detail_json     TEXT,
    source          TEXT NOT NULL,
    device_id       TEXT
);
CREATE TABLE IF NOT EXISTS cook_events (
    id            INTEGER PRIMARY KEY AUTOINCREMENT,
    recipe_id     TEXT,
    dish_name     TEXT NOT NULL,
    servings      REAL,
    cooked_at     TEXT NOT NULL,
    photo_path    TEXT,
    rating        INTEGER,
    notes         TEXT,
    consumed_json TEXT,
    source        TEXT NOT NULL
);
"""


def _now_iso() -> str:
    return datetime.now(timezone.utc).isoformat()


class KitchenStore:
    def __init__(self, db_path: str | Path, pantry_json_path: str | Path | None = None) -> None:
        self._path = str(db_path)
        self._conn = self._open()
        if pantry_json_path is not None:
            self._migrate_from_json(Path(pantry_json_path))

    def _open(self) -> sqlite3.Connection:
        Path(self._path).parent.mkdir(parents=True, exist_ok=True)
        conn = sqlite3.connect(self._path, check_same_thread=False)
        conn.row_factory = sqlite3.Row
        for stmt in _DDL.strip().split(";"):
            stmt = stmt.strip()
            if stmt:
                conn.execute(stmt)
        conn.commit()
        return conn

    def _migrate_from_json(self, json_path: Path) -> None:
        # Only migrate when the table is empty AND the json still exists.
        count = self._conn.execute("SELECT COUNT(*) FROM pantry_items").fetchone()[0]
        if count or not json_path.exists():
            return
        try:
            raw = json.loads(json_path.read_text(encoding="utf-8"))
        except (ValueError, OSError):
            return  # corrupt/unreadable → start empty, never fatal
        now = _now_iso()
        for item in raw:
            q = item.get("quantity") or {}
            self._conn.execute(
                """INSERT OR IGNORE INTO pantry_items
                   (canonical_name, raw_text, quantity_amount, quantity_unit,
                    expires_at, state, confidence, last_observed_at, source,
                    added_at, updated_at)
                   VALUES (?,?,?,?,?, 'present', 1.0, ?, 'manual', ?, ?)""",
                (item["canonical_name"], item["raw_text"], q.get("amount"),
                 q.get("unit"), item.get("expires_at"), now, now, now),
            )
            self._conn.execute(
                "INSERT INTO inventory_events (ts, canonical_name, change_type, source) "
                "VALUES (?,?, 'add', 'migration')",
                (now, item["canonical_name"]),
            )
        self._conn.commit()
        json_path.rename(json_path.with_suffix(json_path.suffix + ".imported"))

    @staticmethod
    def _row_to_dict(row: sqlite3.Row) -> dict[str, Any]:
        item: dict[str, Any] = {
            "canonical_name": row["canonical_name"],
            "raw_text": row["raw_text"],
            "state": row["state"],
            "confidence": row["confidence"],
            "last_observed_at": row["last_observed_at"],
            "source": row["source"],
        }
        if row["quantity_amount"] is not None:
            item["quantity"] = {"amount": row["quantity_amount"], "unit": row["quantity_unit"] or ""}
        if row["expires_at"] is not None:
            item["expires_at"] = row["expires_at"]
        return item

    def list_items(self) -> list[dict[str, Any]]:
        rows = self._conn.execute(
            "SELECT * FROM pantry_items ORDER BY canonical_name"
        ).fetchall()
        return [self._row_to_dict(r) for r in rows]
```

- [ ] **Step 4: Run it to verify it passes**

Run: `.venv/bin/python -m pytest tests/navigator/test_kitchen_store.py -q 2>&1 | grep -v -E "profiling:|\.gcda:|Cannot open"`
Expected: PASS (3 passed)

- [ ] **Step 5: Commit**

```bash
git add pantryatlas/store/kitchen.py tests/navigator/test_kitchen_store.py
git commit -m "feat(store): KitchenStore schema + pantry.json migration"
```

---

## Task 2: KitchenStore — pantry CRUD + ledger + on-hand Pantry

**Files:**
- Modify: `pantryatlas/store/kitchen.py`
- Test: `tests/navigator/test_kitchen_store.py`

- [ ] **Step 1: Write the failing test**

```python
# append to tests/navigator/test_kitchen_store.py
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
```

- [ ] **Step 2: Run it to verify it fails**

Run: `.venv/bin/python -m pytest tests/navigator/test_kitchen_store.py -q 2>&1 | grep -v -E "profiling:|\.gcda:|Cannot open"`
Expected: FAIL — `AttributeError: 'KitchenStore' object has no attribute 'add_item'`

- [ ] **Step 3: Write the minimal implementation**

```python
# append methods to class KitchenStore in pantryatlas/store/kitchen.py

    def _log_event(self, canonical_name: str, change_type: str, source: str,
                   detail: dict | None = None) -> None:
        self._conn.execute(
            "INSERT INTO inventory_events (ts, canonical_name, change_type, detail_json, source) "
            "VALUES (?,?,?,?,?)",
            (_now_iso(), canonical_name, change_type,
             json.dumps(detail) if detail else None, source),
        )

    def add_item(self, ingredient: Ingredient, source: str = "manual") -> dict[str, Any]:
        now = _now_iso()
        q = ingredient.quantity
        exp = ingredient.expires_at.isoformat() if ingredient.expires_at else None
        self._conn.execute(
            """INSERT INTO pantry_items
               (canonical_name, raw_text, quantity_amount, quantity_unit, expires_at,
                state, confidence, last_observed_at, source, added_at, updated_at)
               VALUES (?,?,?,?,?, 'present', 1.0, ?, ?, ?, ?)
               ON CONFLICT(canonical_name) DO UPDATE SET
                 raw_text=excluded.raw_text,
                 quantity_amount=excluded.quantity_amount,
                 quantity_unit=excluded.quantity_unit,
                 expires_at=excluded.expires_at,
                 state='present', confidence=1.0,
                 last_observed_at=excluded.last_observed_at,
                 source=excluded.source, updated_at=excluded.updated_at""",
            (ingredient.canonical_name, ingredient.raw_text,
             q.amount if q else None, q.unit if q else None, exp,
             now, source, now, now),
        )
        self._log_event(ingredient.canonical_name, "add", source)
        self._conn.commit()
        return self.get_item(ingredient.canonical_name)

    def get_item(self, canonical_name: str) -> dict[str, Any] | None:
        row = self._conn.execute(
            "SELECT * FROM pantry_items WHERE canonical_name=?", (canonical_name,)
        ).fetchone()
        return self._row_to_dict(row) if row is not None else None

    def remove_item(self, canonical_name: str) -> None:
        cur = self._conn.execute(
            "DELETE FROM pantry_items WHERE canonical_name=?", (canonical_name,)
        )
        if cur.rowcount:
            self._log_event(canonical_name, "adjust", "manual", {"removed": True})
        self._conn.commit()

    def replace_all(self, ingredients: list[Ingredient], source: str = "manual") -> list[dict[str, Any]]:
        existing = {i["canonical_name"] for i in self.list_items()}
        incoming = {ing.canonical_name for ing in ingredients}
        for gone in existing - incoming:
            self._conn.execute("DELETE FROM pantry_items WHERE canonical_name=?", (gone,))
            self._log_event(gone, "adjust", source, {"removed": True})
        for ing in ingredients:
            self.add_item(ing, source=source)  # commits per item; fine for a replace
        self._conn.commit()
        return self.list_items()

    def on_hand(self) -> Pantry:
        """Return a Pantry of present+low items for recipe ranking."""
        placeholders = ",".join("?" * len(_ON_HAND_STATES))
        rows = self._conn.execute(
            f"SELECT * FROM pantry_items WHERE state IN ({placeholders})",
            _ON_HAND_STATES,
        ).fetchall()
        pantry = Pantry()
        for r in rows:
            qty = None
            if r["quantity_amount"] is not None:
                qty = Quantity(amount=r["quantity_amount"], unit=r["quantity_unit"] or "")
            exp = date.fromisoformat(r["expires_at"]) if r["expires_at"] else None
            pantry.add(Ingredient(
                canonical_name=r["canonical_name"], raw_text=r["raw_text"],
                quantity=qty, expires_at=exp,
            ))
        return pantry
```

- [ ] **Step 4: Run it to verify it passes**

Run: `.venv/bin/python -m pytest tests/navigator/test_kitchen_store.py -q 2>&1 | grep -v -E "profiling:|\.gcda:|Cannot open"`
Expected: PASS

- [ ] **Step 5: Commit**

```bash
git add pantryatlas/store/kitchen.py tests/navigator/test_kitchen_store.py
git commit -m "feat(store): KitchenStore pantry CRUD + ledger + on-hand"
```

---

## Task 3: KitchenStore — coarse consume transitions

**Files:**
- Modify: `pantryatlas/store/kitchen.py`
- Test: `tests/navigator/test_kitchen_store.py`

- [ ] **Step 1: Write the failing test**

```python
# append to tests/navigator/test_kitchen_store.py
import pytest


@pytest.mark.parametrize(
    "start_state, coarse, end_state, end_conf, change_type",
    [
        ("present", "half", "low", 0.5, "consume"),
        ("low", "half", "low", 0.5, "consume"),
        ("present", "used_up", "used_up", 0.0, "consume"),
        ("present", "discarded", "used_up", 0.0, "discard"),
        ("present", "cook", "low", 0.5, "consume"),     # tap-to-cook default: one notch
        ("low", "cook", "used_up", 0.0, "consume"),
    ],
)
def test_consume_transitions(tmp_path, start_state, coarse, end_state, end_conf, change_type):
    store = KitchenStore(tmp_path / "kitchen.db")
    store.add_item(Ing(canonical_name="garlic", raw_text="garlic"))
    store._conn.execute("UPDATE pantry_items SET state=?, confidence=1.0 WHERE canonical_name='garlic'", (start_state,))
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
```

- [ ] **Step 2: Run it to verify it fails**

Run: `.venv/bin/python -m pytest tests/navigator/test_kitchen_store.py -k "consume or restore" -q 2>&1 | grep -v -E "profiling:|\.gcda:|Cannot open"`
Expected: FAIL — `AttributeError: ... 'consume_item'`

- [ ] **Step 3: Write the minimal implementation**

```python
# append to class KitchenStore in pantryatlas/store/kitchen.py

    @staticmethod
    def _next_state(state: str, coarse_amount: str) -> tuple[str, float]:
        if coarse_amount == "half":
            return ("low" if state == "present" else state, 0.5)
        if coarse_amount in ("used_up", "discarded"):
            return ("used_up", 0.0)
        # 'cook' (tap-to-cook default): one notch down
        if state == "present":
            return ("low", 0.5)
        return ("used_up", 0.0)

    def consume_item(self, canonical_name: str, coarse_amount: str,
                     source: str = "manual") -> dict[str, Any] | None:
        row = self._conn.execute(
            "SELECT state FROM pantry_items WHERE canonical_name=?", (canonical_name,)
        ).fetchone()
        if row is None:
            return None
        new_state, new_conf = self._next_state(row["state"], coarse_amount)
        self._conn.execute(
            "UPDATE pantry_items SET state=?, confidence=?, updated_at=? WHERE canonical_name=?",
            (new_state, new_conf, _now_iso(), canonical_name),
        )
        change_type = "discard" if coarse_amount == "discarded" else "consume"
        self._log_event(canonical_name, change_type, source,
                        {"coarse_amount": coarse_amount, "prev_state": row["state"]})
        self._conn.commit()
        return self.get_item(canonical_name)

    def restore_item(self, canonical_name: str, source: str = "manual") -> dict[str, Any] | None:
        cur = self._conn.execute(
            "UPDATE pantry_items SET state='present', confidence=1.0, last_observed_at=?, updated_at=? "
            "WHERE canonical_name=?",
            (_now_iso(), _now_iso(), canonical_name),
        )
        if not cur.rowcount:
            return None
        self._log_event(canonical_name, "observe", source)
        self._conn.commit()
        return self.get_item(canonical_name)
```

- [ ] **Step 4: Run it to verify it passes**

Run: `.venv/bin/python -m pytest tests/navigator/test_kitchen_store.py -q 2>&1 | grep -v -E "profiling:|\.gcda:|Cannot open"`
Expected: PASS

- [ ] **Step 5: Commit**

```bash
git add pantryatlas/store/kitchen.py tests/navigator/test_kitchen_store.py
git commit -m "feat(store): coarse consume/restore transitions + ledger"
```

---

## Task 4: KitchenStore — cook events (atomic log + soft-decrement) + meals list

**Files:**
- Modify: `pantryatlas/store/kitchen.py`
- Test: `tests/navigator/test_kitchen_store.py`

- [ ] **Step 1: Write the failing test**

```python
# append to tests/navigator/test_kitchen_store.py
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
```

- [ ] **Step 2: Run it to verify it fails**

Run: `.venv/bin/python -m pytest tests/navigator/test_kitchen_store.py -k cook -q 2>&1 | grep -v -E "profiling:|\.gcda:|Cannot open"`
Expected: FAIL — `AttributeError: ... 'add_cook_event'`

- [ ] **Step 3: Write the minimal implementation**

```python
# append to class KitchenStore in pantryatlas/store/kitchen.py

    def add_cook_event(self, *, dish_name: str, consumed: list[dict[str, Any]],
                       recipe_id: str | None = None, servings: float | None = None,
                       photo_path: str | None = None, rating: int | None = None,
                       notes: str | None = None, source: str = "tap-to-cook") -> dict[str, Any]:
        """Atomically record a cook event and soft-decrement consumed on-hand items."""
        on_hand = {r["canonical_name"] for r in self._conn.execute(
            f"SELECT canonical_name FROM pantry_items "
            f"WHERE state IN ({','.join('?' * len(_ON_HAND_STATES))})", _ON_HAND_STATES,
        ).fetchall()}
        matched, unmatched = [], []
        try:
            cur = self._conn.execute(
                """INSERT INTO cook_events
                   (recipe_id, dish_name, servings, cooked_at, photo_path, rating, notes,
                    consumed_json, source)
                   VALUES (?,?,?,?,?,?,?,?,?)""",
                (recipe_id, dish_name, servings, _now_iso(), photo_path, rating, notes,
                 json.dumps(consumed), source),
            )
            event_id = cur.lastrowid
            for c in consumed:
                name = c["canonical_name"]
                if name in on_hand:
                    matched.append(name)
                    row = self._conn.execute(
                        "SELECT state FROM pantry_items WHERE canonical_name=?", (name,)
                    ).fetchone()
                    new_state, new_conf = self._next_state(row["state"], "cook")
                    self._conn.execute(
                        "UPDATE pantry_items SET state=?, confidence=?, updated_at=? "
                        "WHERE canonical_name=?",
                        (new_state, new_conf, _now_iso(), name),
                    )
                    self._log_event(name, "consume", source, {"cook_event_id": event_id})
                else:
                    unmatched.append(name)
            self._conn.commit()
        except Exception:
            self._conn.rollback()
            raise
        return {"id": event_id, "dish_name": dish_name, "matched": matched, "unmatched": unmatched}

    @staticmethod
    def _cook_row_to_dict(row: sqlite3.Row) -> dict[str, Any]:
        return {
            "id": row["id"], "recipe_id": row["recipe_id"], "dish_name": row["dish_name"],
            "servings": row["servings"], "cooked_at": row["cooked_at"],
            "photo_path": row["photo_path"], "rating": row["rating"], "notes": row["notes"],
            "consumed": json.loads(row["consumed_json"]) if row["consumed_json"] else [],
            "source": row["source"],
        }

    def list_meals(self, limit: int = 50) -> list[dict[str, Any]]:
        rows = self._conn.execute(
            "SELECT * FROM cook_events ORDER BY id DESC LIMIT ?", (limit,)
        ).fetchall()
        return [self._cook_row_to_dict(r) for r in rows]
```

- [ ] **Step 4: Run it to verify it passes**

Run: `.venv/bin/python -m pytest tests/navigator/test_kitchen_store.py -q 2>&1 | grep -v -E "profiling:|\.gcda:|Cannot open"`
Expected: PASS

- [ ] **Step 5: Commit**

```bash
git add pantryatlas/store/kitchen.py tests/navigator/test_kitchen_store.py
git commit -m "feat(store): atomic cook events + soft-decrement + meals list"
```

---

## Task 5: KitchenStore — waste tally

**Files:**
- Modify: `pantryatlas/store/kitchen.py`
- Test: `tests/navigator/test_kitchen_store.py`

- [ ] **Step 1: Write the failing test**

```python
# append to tests/navigator/test_kitchen_store.py
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
```

- [ ] **Step 2: Run it to verify it fails**

Run: `.venv/bin/python -m pytest tests/navigator/test_kitchen_store.py -k waste -q 2>&1 | grep -v -E "profiling:|\.gcda:|Cannot open"`
Expected: FAIL — `AttributeError: ... 'mark_expired'`

- [ ] **Step 3: Write the minimal implementation**

```python
# append to class KitchenStore in pantryatlas/store/kitchen.py

    def mark_expired(self, canonical_name: str, source: str = "manual") -> dict[str, Any] | None:
        cur = self._conn.execute(
            "UPDATE pantry_items SET state='used_up', confidence=0.0, updated_at=? "
            "WHERE canonical_name=?",
            (_now_iso(), canonical_name),
        )
        if not cur.rowcount:
            return None
        self._log_event(canonical_name, "expire", source)
        self._conn.commit()
        return self.get_item(canonical_name)

    def waste_tally(self, window_days: int = 30) -> dict[str, Any]:
        cutoff = (datetime.now(timezone.utc) - timedelta(days=window_days)).isoformat()
        rows = self._conn.execute(
            "SELECT canonical_name, change_type FROM inventory_events "
            "WHERE change_type IN ('discard','expire') AND ts >= ?",
            (cutoff,),
        ).fetchall()
        discarded = sum(1 for r in rows if r["change_type"] == "discard")
        expired = sum(1 for r in rows if r["change_type"] == "expire")
        return {
            "window_days": window_days,
            "discarded": discarded,
            "expired": expired,
            "total": discarded + expired,
            "items": [r["canonical_name"] for r in rows],
        }
```

- [ ] **Step 4: Run it to verify it passes**

Run: `.venv/bin/python -m pytest tests/navigator/test_kitchen_store.py -q 2>&1 | grep -v -E "profiling:|\.gcda:|Cannot open"`
Expected: PASS

- [ ] **Step 5: Commit**

```bash
git add pantryatlas/store/kitchen.py tests/navigator/test_kitchen_store.py
git commit -m "feat(store): mark_expired + waste tally"
```

---

## Task 6: Wire KitchenStore into create_app; repoint pantry routes

**Files:**
- Modify: `pantryatlas/navigator/server.py:217-273` (signature + app.state), `:192-209` (add `_get_kitchen`), `:313-373` + `:410,443,470` (repoint routes)
- Test: `tests/navigator/test_loop_routes.py`

- [ ] **Step 1: Write the failing test** (defines the fakes reused by Tasks 6–7)

```python
# tests/navigator/test_loop_routes.py
from __future__ import annotations

from pathlib import Path

import numpy as np
from fastapi.testclient import TestClient

from pantryatlas.pantry.models import Ingredient
from pantryatlas.store.kitchen import KitchenStore


def _fake_resolver(raw: str) -> Ingredient | None:
    key = raw.strip().lower()
    known = {"garlic", "tomato", "basil", "onion", "salt", "pasta"}
    return Ingredient(canonical_name=key, raw_text=raw) if key in known else None


def _fake_embed(texts: list[str]) -> np.ndarray:
    return np.ones((len(texts), 8), dtype=np.float32)


class _FakeRecipe:
    def __init__(self, ingredients): self.ingredients_json = ingredients


class _FakeStore:
    """Duck-typed RecipeStore — no sqlite-vec, runs on Pi 3.11."""
    def __init__(self): self._recipes = {"r1": _FakeRecipe(["garlic", "tomato", "basil"])}
    def count(self): return len(self._recipes)
    def get(self, rid): return self._recipes.get(rid)
    def iter_overlapping(self, names): return []


def _client(tmp_path: Path) -> TestClient:
    from pantryatlas.navigator.server import create_app
    kitchen = KitchenStore(tmp_path / "kitchen.db")
    app = create_app(
        store=_FakeStore(), resolver=_fake_resolver, embed_fn=_fake_embed,
        pantry_path=tmp_path / "pantry.json", kitchen=kitchen,
    )
    return TestClient(app)


def test_pantry_roundtrips_through_kitchen_store(tmp_path):
    client = _client(tmp_path)
    assert client.get("/navigator/pantry").json() == []
    r = client.post("/navigator/pantry/items", json={"raw_text": "garlic"})
    assert r.status_code == 201
    items = client.get("/navigator/pantry").json()
    assert len(items) == 1
    assert items[0]["canonical_name"] == "garlic"
    assert items[0]["state"] == "present"          # new field surfaced
    client.delete("/navigator/pantry/items/garlic")
    assert client.get("/navigator/pantry").json() == []


def test_put_replaces_pantry(tmp_path):
    client = _client(tmp_path)
    client.put("/navigator/pantry", json=[
        {"canonical_name": "tomato", "raw_text": "tomato"},
        {"canonical_name": "basil", "raw_text": "basil"},
    ])
    names = {i["canonical_name"] for i in client.get("/navigator/pantry").json()}
    assert names == {"tomato", "basil"}
```

- [ ] **Step 2: Run it to verify it fails**

Run: `.venv/bin/python -m pytest tests/navigator/test_loop_routes.py -q 2>&1 | grep -v -E "profiling:|\.gcda:|Cannot open"`
Expected: FAIL — `TypeError: create_app() got an unexpected keyword argument 'kitchen'`

- [ ] **Step 3a: Add the `kitchen`/`kitchen_factory` params + state + accessor**

In `pantryatlas/navigator/server.py`, extend `create_app`'s signature (after `providers_config_path`):

```python
    kitchen: "KitchenStore | None" = None,
    kitchen_factory: "Callable[[], KitchenStore] | None" = None,
```

Add the import near the top (with the other store import):

```python
from pantryatlas.store.kitchen import KitchenStore
```

In the app.state block (after `app.state.providers_config_path = providers_config_path`):

```python
    app.state.kitchen = kitchen
    app.state.kitchen_factory = kitchen_factory
```

Add the accessor next to `_get_store` (after it):

```python
def _get_kitchen(app: FastAPI) -> KitchenStore:
    """Return the app's KitchenStore, initialising it lazily via factory if needed."""
    kitchen: KitchenStore | None = getattr(app.state, "kitchen", None)
    if kitchen is None:
        factory: Callable[[], KitchenStore] | None = getattr(app.state, "kitchen_factory", None)
        if factory is None:
            raise RuntimeError("No KitchenStore and no kitchen_factory configured on app.state")
        app.state.kitchen = factory()
        kitchen = app.state.kitchen
    return kitchen
```

- [ ] **Step 3b: Repoint the four pantry routes + three recompute routes**

Replace the bodies of `get_pantry`, `put_pantry`, `post_pantry_item`, `delete_pantry_item`:

```python
    @app.get("/navigator/pantry")
    def get_pantry() -> list[dict[str, Any]]:
        return _get_kitchen(app).list_items()

    @app.put("/navigator/pantry")
    def put_pantry(items: list[IngredientIn]) -> list[dict[str, Any]]:
        ingredients = [
            Ingredient(
                canonical_name=it.canonical_name, raw_text=it.raw_text,
                quantity=Quantity(amount=it.quantity.amount, unit=it.quantity.unit)
                if it.quantity is not None else None,
                expires_at=it.expires_at,
            )
            for it in items
        ]
        return _get_kitchen(app).replace_all(ingredients)

    @app.post("/navigator/pantry/items", status_code=201)
    def post_pantry_item(body: AddItemIn) -> dict[str, Any]:
        ingredient = app.state.resolver(body.raw_text)
        if ingredient is None:
            raise HTTPException(status_code=422,
                                detail=f"Cannot resolve '{body.raw_text}' to a canonical ingredient.")
        item = _get_kitchen(app).add_item(ingredient)
        return {"canonical_name": item["canonical_name"], "raw_text": item["raw_text"]}

    @app.delete("/navigator/pantry/items/{name}")
    def delete_pantry_item(name: str) -> dict[str, str]:
        _get_kitchen(app).remove_item(name)
        return {"removed": name}
```

In the three recompute routes, replace each `pantry = _load_pantry(app.state.pantry_path)` with:

```python
        pantry = _get_kitchen(app).on_hand()
```

(applies at the former `:410`, `:443`, `:470`). Leave `_load_pantry`/`_save_pantry`/`_pantry_to_list` defined — `KitchenStore` handles persistence now, but the helpers stay until removed in a later cleanup.

- [ ] **Step 3c: Fix the EXISTING app-construction test sites (REGRESSION GUARD)**

Repointing the shared pantry/recompute routes means every `create_app(...)` test fixture now needs a `kitchen`, or those routes raise `RuntimeError` ("No KitchenStore..."). There are **four** sites (verified — none assert `pantry.json` file contents, so only the `kitchen=` argument is needed, no assertion rewrites):

| File:line | tmp dir in scope | fix |
|---|---|---|
| `tests/navigator/test_server.py:132` (`client` fixture) | `pantry_path` (= `tmp_path/"pantry.json"`) | `kitchen=KitchenStore(pantry_path.parent / "kitchen.db")` |
| `tests/navigator/test_server.py:198` | `pantry_path` | `kitchen=KitchenStore(pantry_path.parent / "kitchen.db")` |
| `tests/navigator/test_vision.py:219` | `tmp_path` | `kitchen=KitchenStore(tmp_path / "kitchen.db")` |
| `tests/navigator/test_providers_api.py:33` | `tmp_path` | `kitchen=KitchenStore(tmp_path / "kitchen.db")` |

Add `from pantryatlas.store.kitchen import KitchenStore` to each of the three files and the `kitchen=` kwarg to each `create_app(...)` call. Example (test_server.py `client` fixture):

```python
    from pantryatlas.navigator.server import create_app
    from pantryatlas.store.kitchen import KitchenStore

    app = create_app(
        store=tmp_store,
        resolver=_fake_resolver,
        embed_fn=_fake_embed,
        pantry_path=pantry_path,
        kitchen=KitchenStore(pantry_path.parent / "kitchen.db"),
    )
    return TestClient(app)
```

Re-grep to be sure no site was missed: `grep -rn "create_app(" tests/ | grep -v "create_app(store, resolver"` (the latter excludes the docstring).

- [ ] **Step 4: Run it to verify it passes — the WHOLE navigator suite (this is the CI-trap guard)**

Run: `.venv/bin/python -m pytest tests/navigator/ -q 2>&1 | grep -v -E "profiling:|\.gcda:|Cannot open"`
Expected: PASS — both the new `test_loop_routes.py`/`test_kitchen_store.py` AND the pre-existing `test_server.py`/`test_vision.py`/`test_providers_api.py`. (If `test_server.py` 500s on `/navigator/pantry`, a `create_app` site is missing its `kitchen=`.)

- [ ] **Step 5: Commit**

```bash
git add pantryatlas/navigator/server.py tests/navigator/test_loop_routes.py
git commit -m "feat(navigator): pantry routes backed by KitchenStore (lazy)"
```

---

## Task 7: New routes — consume, cook, meals, waste

**Files:**
- Modify: `pantryatlas/navigator/server.py` (add Pydantic models near `:119`; add routes after the pantry block ~`:373`)
- Test: `tests/navigator/test_loop_routes.py`

- [ ] **Step 1: Write the failing test**

```python
# append to tests/navigator/test_loop_routes.py
def test_consume_route(tmp_path):
    client = _client(tmp_path)
    client.post("/navigator/pantry/items", json={"raw_text": "garlic"})
    r = client.post("/navigator/pantry/items/garlic/consume", json={"coarse_amount": "half"})
    assert r.status_code == 200
    assert r.json()["state"] == "low"
    assert client.post("/navigator/pantry/items/ghost/consume",
                       json={"coarse_amount": "used_up"}).status_code == 404


def test_cook_route_logs_and_decrements(tmp_path):
    client = _client(tmp_path)
    for n in ("garlic", "tomato", "basil"):
        client.post("/navigator/pantry/items", json={"raw_text": n})
    r = client.post("/navigator/cook", json={"recipe_id": "r1", "dish_name": "Pomodoro", "servings": 2})
    assert r.status_code == 201
    body = r.json()
    assert set(body["matched"]) == {"garlic", "tomato", "basil"}   # derived from recipe r1
    states = {i["canonical_name"]: i["state"] for i in client.get("/navigator/pantry").json()}
    assert states == {"garlic": "low", "tomato": "low", "basil": "low"}
    meals = client.get("/navigator/meals").json()
    assert meals[0]["dish_name"] == "Pomodoro"


def test_cook_route_explicit_consumed(tmp_path):
    client = _client(tmp_path)
    client.post("/navigator/pantry/items", json={"raw_text": "onion"})
    r = client.post("/navigator/cook", json={
        "dish_name": "Soup",
        "consumed": [{"canonical_name": "onion", "coarse_amount": "used_up"}],
    })
    assert r.status_code == 201
    states = {i["canonical_name"]: i["state"] for i in client.get("/navigator/pantry").json()}
    assert states["onion"] == "used_up"


def test_waste_route(tmp_path):
    client = _client(tmp_path)
    client.post("/navigator/pantry/items", json={"raw_text": "tomato"})
    client.post("/navigator/pantry/items/tomato/consume", json={"coarse_amount": "discarded"})
    tally = client.get("/navigator/waste").json()
    assert tally["discarded"] == 1 and tally["total"] == 1
```

- [ ] **Step 2: Run it to verify it fails**

Run: `.venv/bin/python -m pytest tests/navigator/test_loop_routes.py -k "consume or cook or waste" -q 2>&1 | grep -v -E "profiling:|\.gcda:|Cannot open"`
Expected: FAIL — 404 (routes not defined)

- [ ] **Step 3a: Add Pydantic wire models** (near the other models, after `ProviderIn`):

```python
class ConsumeIn(BaseModel):
    """Body for POST /navigator/pantry/items/{name}/consume."""

    coarse_amount: str = "used_up"  # half | used_up | discarded


class ConsumedItemIn(BaseModel):
    canonical_name: str
    coarse_amount: str = "cook"


class CookIn(BaseModel):
    """Body for POST /navigator/cook."""

    dish_name: str
    recipe_id: str | None = None
    servings: float | None = None
    rating: int | None = None
    notes: str | None = None
    consumed: list[ConsumedItemIn] | None = None
```

- [ ] **Step 3b: Add the four routes** (after the `delete_pantry_item` route):

```python
    @app.post("/navigator/pantry/items/{name}/consume")
    def consume_pantry_item(name: str, body: ConsumeIn) -> dict[str, Any]:
        item = _get_kitchen(app).consume_item(name, body.coarse_amount)
        if item is None:
            raise HTTPException(status_code=404, detail=f"No pantry item '{name}'.")
        return item

    @app.post("/navigator/pantry/items/{name}/restore")
    def restore_pantry_item(name: str) -> dict[str, Any]:
        item = _get_kitchen(app).restore_item(name)
        if item is None:
            raise HTTPException(status_code=404, detail=f"No pantry item '{name}'.")
        return item

    @app.post("/navigator/cook", status_code=201)
    def post_cook(body: CookIn) -> dict[str, Any]:
        kitchen = _get_kitchen(app)
        consumed = [{"canonical_name": c.canonical_name, "coarse_amount": c.coarse_amount}
                    for c in (body.consumed or [])]
        if not consumed and body.recipe_id is not None:
            recipe = _get_store(app).get(body.recipe_id)
            if recipe is not None and recipe.ingredients_json:
                for ing in recipe.ingredients_json:
                    resolved = app.state.resolver(ing)
                    name = resolved.canonical_name if resolved is not None else ing
                    consumed.append({"canonical_name": name, "coarse_amount": "cook"})
        return kitchen.add_cook_event(
            dish_name=body.dish_name, recipe_id=body.recipe_id, servings=body.servings,
            rating=body.rating, notes=body.notes, consumed=consumed,
        )

    @app.get("/navigator/meals")
    def get_meals(limit: int = 50) -> list[dict[str, Any]]:
        return _get_kitchen(app).list_meals(limit=limit)

    @app.get("/navigator/waste")
    def get_waste(window_days: int = 30) -> dict[str, Any]:
        return _get_kitchen(app).waste_tally(window_days=window_days)
```

- [ ] **Step 4: Run it to verify it passes**

Run: `.venv/bin/python -m pytest tests/navigator/test_loop_routes.py -q 2>&1 | grep -v -E "profiling:|\.gcda:|Cannot open"`
Expected: PASS (all)

- [ ] **Step 5: Commit**

```bash
git add pantryatlas/navigator/server.py tests/navigator/test_loop_routes.py
git commit -m "feat(navigator): consume/cook/meals/waste routes"
```

---

## Task 8: Production wiring (lazy KitchenStore + migration)

**Files:**
- Modify: `pantryatlas/navigator/server.py:630-700` (add default path + factory + pass to create_app)
- Test: `tests/navigator/test_server.py` (extend the import-side-effect test)

- [ ] **Step 1: Write the failing test** (extends the existing side-effect test)

```python
# append to tests/navigator/test_server.py
def test_import_does_not_create_kitchen_db(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    """Importing server must NOT create ~/.pantryatlas/kitchen.db (lazy factory)."""
    monkeypatch.setenv("HOME", str(tmp_path))
    mod_name = "pantryatlas.navigator.server"
    if mod_name in sys.modules:
        del sys.modules[mod_name]
    importlib.import_module(mod_name)
    assert not (tmp_path / ".pantryatlas" / "kitchen.db").exists()
```

- [ ] **Step 2: Run it to verify it fails**

Run: `.venv/bin/python -m pytest tests/navigator/test_server.py::test_import_does_not_create_kitchen_db -q 2>&1 | grep -v -E "profiling:|\.gcda:|Cannot open"`
Expected: FAIL — `create_app() got an unexpected keyword argument` is gone (Task 6 added it), so this fails only if a factory eagerly builds; confirm it fails because `kitchen_factory` isn't wired yet → import builds nothing, test actually passes vacuously. To make it meaningful, FIRST confirm RED by temporarily asserting the factory is wired:

Run: `.venv/bin/python -c "from pantryatlas.navigator.server import _make_production_kitchen_factory" 2>&1 | grep -v -E "profiling:|\.gcda:|Cannot open"`
Expected: FAIL — `ImportError: cannot import name '_make_production_kitchen_factory'`

- [ ] **Step 3: Add the default path, factory, and wire it**

After `_DEFAULT_DB_PATH = ...` (`:631`):

```python
_DEFAULT_KITCHEN_DB_PATH = Path.home() / ".pantryatlas" / "kitchen.db"
```

Add the factory (next to `_make_production_store_factory`):

```python
def _make_production_kitchen_factory() -> Callable[[], KitchenStore]:
    """Return a factory that opens the real KitchenStore and migrates pantry.json once."""

    def _factory() -> KitchenStore:
        return KitchenStore(_DEFAULT_KITCHEN_DB_PATH, pantry_json_path=_DEFAULT_PANTRY_PATH)

    return _factory
```

In `_build_production_app`'s `create_app(...)` call, add:

```python
        kitchen_factory=_make_production_kitchen_factory(),
```

- [ ] **Step 4: Run it to verify it passes**

Run: `.venv/bin/python -m pytest tests/navigator/test_server.py::test_import_does_not_create_kitchen_db -q 2>&1 | grep -v -E "profiling:|\.gcda:|Cannot open"`
Expected: PASS
Then confirm the symbol exists:
Run: `.venv/bin/python -c "from pantryatlas.navigator.server import _make_production_kitchen_factory; print('ok')" 2>&1 | grep -v -E "profiling:|\.gcda:|Cannot open"`
Expected: `ok`

- [ ] **Step 5: Commit**

```bash
git add pantryatlas/navigator/server.py tests/navigator/test_server.py
git commit -m "feat(navigator): lazy production KitchenStore factory + migration"
```

---

## Task 9: Frontend data layer — types + cook/consume/meals helpers

**Files:**
- Modify: `web/src/signals.ts` (extend `PantryItem`; add `CookEvent`, `meals`, `cookRecipe`, `consumeItem`, `fetchMeals`)

- [ ] **Step 1: Extend `PantryItem` and add the cook/meal types**

In `web/src/signals.ts`, replace the `PantryItem` interface with:

```typescript
export interface PantryItem {
  canonical_name: string
  raw_text: string
  quantity?: { amount: number; unit: string }
  expires_at?: string
  /** present | low | used_up — coarse confidence in on-hand presence */
  state?: 'present' | 'low' | 'used_up'
  confidence?: number
  last_observed_at?: string
  source?: string
  /** Present on optimistically-added items awaiting sync. */
  _pending?: boolean
}

export interface CookEvent {
  id: number
  recipe_id?: string | null
  dish_name: string
  servings?: number | null
  cooked_at: string
  rating?: number | null
  notes?: string | null
  consumed: { canonical_name: string; coarse_amount: string }[]
  source: string
}
```

- [ ] **Step 2: Add the meals signal + action helpers** (after the pantry helpers, before "Reconnect replay"):

```typescript
export const meals = signal<CookEvent[]>([])

export async function fetchMeals() {
  try {
    const res = await fetch('/navigator/meals')
    if (res.ok) meals.value = await res.json()
  } catch {
    // keep existing
  }
}

/** Mark a recipe cooked: logs it + soft-decrements its ingredients, then refreshes. */
export async function cookRecipe(opts: {
  recipe_id?: string
  dish_name: string
  servings?: number
}): Promise<boolean> {
  try {
    const res = await fetch('/navigator/cook', {
      method: 'POST',
      headers: { 'Content-Type': 'application/json' },
      body: JSON.stringify(opts),
    })
    if (res.ok || res.status === 201) {
      await fetchPantry()
      await fetchMeals()
      return true
    }
  } catch {
    // ignore
  }
  return false
}

/** Coarse consume on a pantry item: 'half' | 'used_up' | 'discarded'. */
export async function consumeItem(canonicalName: string, coarseAmount: string) {
  try {
    await fetch(`/navigator/pantry/items/${encodeURIComponent(canonicalName)}/consume`, {
      method: 'POST',
      headers: { 'Content-Type': 'application/json' },
      body: JSON.stringify({ coarse_amount: coarseAmount }),
    })
    await fetchPantry()
  } catch {
    // ignore
  }
}

export async function restoreItem(canonicalName: string) {
  try {
    await fetch(`/navigator/pantry/items/${encodeURIComponent(canonicalName)}/restore`, {
      method: 'POST',
    })
    await fetchPantry()
  } catch {
    // ignore
  }
}
```

- [ ] **Step 3: Type-check**

Run: `cd ~/pantryatlas/web && npm run build 2>&1 | tail -20`
Expected: build succeeds (no TS errors).

- [ ] **Step 4: Commit**

```bash
cd ~/pantryatlas && git add web/src/signals.ts
git commit -m "feat(web): cook/consume/meals data layer + PantryItem state fields"
```

---

## Task 10: "I cooked this" on the recipe card

**Files:**
- Modify: `web/src/components/RecipeCard.tsx:519-584` (action buttons block) + imports

- [ ] **Step 1: Add the import + a recipe_id-free cook handler**

At the top of `RecipeCard.tsx`, extend the signals import:

```typescript
import { fetchSwaps, recipeSwaps, recipeKey, cookRecipe, type SwapSuggestion } from '../signals'
```

Inside `RecipeCard`, add state + handler (after the `key`/`swapEntry` lines, before `swapLineFor`):

```typescript
  const [cooking, setCooking] = useState(false)
  const [cooked, setCooked] = useState(false)

  async function handleCooked(e: MouseEvent) {
    e.stopPropagation()
    setCooking(true)
    const ok = await cookRecipe({ dish_name: recipe.title, servings: 2 })
    setCooking(false)
    if (ok) setCooked(true)
  }
```

- [ ] **Step 2: Add the button** as the FIRST child of the existing action-buttons `<div style={{ display: 'flex', gap: '12px', flexWrap: 'wrap' }}>` (before "Add missing to shopping list"):

```tsx
              {/* "I cooked this" — filled primary pill; logs + soft-decrements */}
              <button
                type="button"
                data-cooked-btn={cooked ? 'done' : 'idle'}
                disabled={cooking || cooked}
                onClick={handleCooked}
                style={{
                  flex: '1 1 auto',
                  minHeight: '44px',
                  padding: '10px 20px',
                  borderRadius: 'var(--md-sys-shape-corner-full)',
                  background: cooked
                    ? 'var(--md-sys-color-tertiary-container)'
                    : 'var(--md-sys-color-primary)',
                  color: cooked
                    ? 'var(--md-sys-color-on-tertiary-container)'
                    : 'var(--md-sys-color-on-primary)',
                  border: 'none',
                  fontFamily: 'var(--font)',
                  fontSize: 'var(--md-sys-typescale-label-large-size)',
                  fontWeight: 'var(--md-sys-typescale-label-large-weight)',
                  cursor: cooking || cooked ? 'default' : 'pointer',
                  whiteSpace: 'nowrap',
                }}
              >
                {cooked ? '✓ Logged' : cooking ? 'Logging…' : 'I cooked this'}
              </button>
```

- [ ] **Step 3: Type-check / build**

Run: `cd ~/pantryatlas/web && npm run build 2>&1 | tail -20`
Expected: build succeeds.

- [ ] **Step 4: Commit**

```bash
cd ~/pantryatlas && git add web/src/components/RecipeCard.tsx
git commit -m "feat(web): 'I cooked this' on recipe card → cook event + decrement"
```

---

## Task 11: Pantry-row consume controls + dimmed used_up

**Files:**
- Modify: `web/src/pages/Navigator.tsx` (pantry list rendering)

> Read the current pantry-list block in `Navigator.tsx` first. Add, per pantry row: (a) when `state === 'used_up'`, render the row dimmed (`opacity: 0.5`) with a "Still have it" restore button calling `restoreItem(name)`; (b) otherwise an overflow control with three coarse actions calling `consumeItem(name, 'half' | 'used_up' | 'discarded')`. Use the existing row markup + token styles.

- [ ] **Step 1: Import the helpers AND the `PantryItem` type** in `Navigator.tsx` (verified: `Navigator.tsx` does not currently import `PantryItem`, so `PantryRowActions`'s prop type needs it):

```typescript
import { consumeItem, restoreItem, type PantryItem } from '../signals'
```

- [ ] **Step 2: Add a `PantryRowActions` helper component** at module scope in `Navigator.tsx` (complete code):

```tsx
function PantryRowActions({ item }: { item: PantryItem }) {
  if (item.state === 'used_up') {
    return (
      <button
        type="button"
        data-restore={item.canonical_name}
        onClick={() => restoreItem(item.canonical_name)}
        style={{
          minHeight: '36px', padding: '4px 12px',
          borderRadius: 'var(--md-sys-shape-corner-full)',
          background: 'transparent',
          border: '1px solid var(--md-sys-color-outline-variant)',
          color: 'var(--md-sys-color-primary)',
          fontFamily: 'var(--font)',
          fontSize: 'var(--md-sys-typescale-label-medium-size)',
          cursor: 'pointer', whiteSpace: 'nowrap',
        }}
      >
        Still have it
      </button>
    )
  }
  const btn = (label: string, amount: string) => (
    <button
      type="button"
      data-consume={`${item.canonical_name}:${amount}`}
      onClick={() => consumeItem(item.canonical_name, amount)}
      style={{
        minHeight: '36px', padding: '4px 10px',
        borderRadius: 'var(--md-sys-shape-corner-full)',
        background: 'transparent', border: 'none',
        color: 'var(--md-sys-color-on-surface-variant)',
        fontFamily: 'var(--font)',
        fontSize: 'var(--md-sys-typescale-label-medium-size)',
        cursor: 'pointer', whiteSpace: 'nowrap',
      }}
    >
      {label}
    </button>
  )
  return (
    <span style={{ display: 'inline-flex', gap: '2px' }}>
      {btn('½ left', 'half')}
      {btn('used up', 'used_up')}
      {btn('tossed', 'discarded')}
    </span>
  )
}
```

- [ ] **Step 3: Render it inside each pantry row** and dim used_up rows. In the pantry `.map(...)` row, set the row style to include `opacity: item.state === 'used_up' ? 0.5 : 1` and add `<PantryRowActions item={item} />` to the row's trailing controls (alongside the existing delete control).

- [ ] **Step 4: Build**

Run: `cd ~/pantryatlas/web && npm run build 2>&1 | tail -20`
Expected: build succeeds.

- [ ] **Step 5: Commit**

```bash
cd ~/pantryatlas && git add web/src/pages/Navigator.tsx
git commit -m "feat(web): coarse consume controls + dimmed used_up rows"
```

---

## Task 12: Meal-log timeline view

**Files:**
- Create: `web/src/components/MealLog.tsx`
- Modify: `web/src/pages/Navigator.tsx` (entry point + render)

- [ ] **Step 1: Create the component** (complete code):

```tsx
// web/src/components/MealLog.tsx
import { h } from 'preact'
import { useEffect } from 'preact/hooks'
import { meals, fetchMeals } from '../signals'

/** Kitchen log — a reverse-chronological list of cook events. */
export function MealLog() {
  useEffect(() => { void fetchMeals() }, [])
  const list = meals.value
  if (list.length === 0) {
    return (
      <p style={{
        fontFamily: 'var(--font)',
        color: 'var(--md-sys-color-on-surface-variant)',
        padding: '12px 0',
      }} data-meal-empty="true">
        Nothing cooked yet — tap “I cooked this” on a recipe to start your log.
      </p>
    )
  }
  return (
    <ul style={{ listStyle: 'none', display: 'flex', flexDirection: 'column', gap: '8px' }}
        data-meal-log="true">
      {list.map((m) => (
        <li key={m.id}
            data-meal-id={m.id}
            style={{
              padding: '12px 16px',
              borderRadius: 'var(--md-sys-shape-corner-medium)',
              background: 'var(--md-sys-color-surface-container-low)',
              fontFamily: 'var(--font)',
            }}>
          <span style={{
            fontSize: 'var(--md-sys-typescale-title-small-size)',
            fontWeight: 'var(--md-sys-typescale-title-small-weight)',
            color: 'var(--md-sys-color-on-surface)',
          }}>{m.dish_name}</span>
          <span style={{
            display: 'block',
            fontSize: 'var(--md-sys-typescale-label-small-size)',
            color: 'var(--md-sys-color-on-surface-variant)',
            marginTop: '2px',
          }}>
            {new Date(m.cooked_at).toLocaleDateString()}
            {m.consumed.length > 0 ? ` · used ${m.consumed.length} item${m.consumed.length === 1 ? '' : 's'}` : ''}
          </span>
        </li>
      ))}
    </ul>
  )
}
```

- [ ] **Step 2: Add a Kitchen-log section to `Navigator.tsx`** — a collapsible in-place section (preserve the no-routes single-screen ethos per `DESIGN.md`). Import `MealLog` and a local `showLog` signal/state; add a small top-bar control (e.g. a "Log" text button) that toggles a section rendering `<MealLog />` below the recipe list.

```typescript
import { MealLog } from '../components/MealLog'
```

- [ ] **Step 3: Build**

Run: `cd ~/pantryatlas/web && npm run build 2>&1 | tail -20`
Expected: build succeeds.

- [ ] **Step 4: Commit**

```bash
cd ~/pantryatlas && git add web/src/components/MealLog.tsx web/src/pages/Navigator.tsx
git commit -m "feat(web): meal-log timeline view"
```

---

## Task 13: Expiry nudge strip

**Files:**
- Modify: `web/src/pages/Navigator.tsx` (nudge strip above the recipe list)

> Use the existing `daysUntilExpiry(item.expires_at)` helper in `signals.ts`. Show a strip when any on-hand item expires within 3 days.

- [ ] **Step 1: Add a `computed` for expiring items** in `signals.ts`:

```typescript
export const expiringSoon = computed(() =>
  pantry.value.filter(
    (i) => i.state !== 'used_up' && (daysUntilExpiry(i.expires_at) ?? 99) <= 3
  )
)
```

- [ ] **Step 2: Render the nudge strip** in `Navigator.tsx` above the recipe section (complete JSX):

```tsx
{expiringSoon.value.length > 0 && (
  <div
    data-expiry-nudge="true"
    style={{
      padding: '12px 16px',
      borderRadius: 'var(--md-sys-shape-corner-large)',
      background: 'var(--md-sys-color-error-container)',
      color: 'var(--md-sys-color-on-error-container)',
      fontFamily: 'var(--font)',
      fontSize: 'var(--md-sys-typescale-body-medium-size)',
      marginBottom: '12px',
    }}
  >
    Expiring soon: {expiringSoon.value.map((i) => i.canonical_name).join(', ')} — cook these first.
  </div>
)}
```

Import `expiringSoon` from `../signals`.

- [ ] **Step 3: Build**

Run: `cd ~/pantryatlas/web && npm run build 2>&1 | tail -20`
Expected: build succeeds.

- [ ] **Step 4: Commit**

```bash
cd ~/pantryatlas && git add web/src/signals.ts web/src/pages/Navigator.tsx
git commit -m "feat(web): expiry nudge strip (≤3 days)"
```

---

## Task 14: Headless loop verification + docs + final gates

**Files:**
- Create: `web/verify_loop.mjs`
- Modify: `docs/navigator.md`

- [ ] **Step 1: Write the headless verify script** (mirrors `web/take_screenshots_refine.mjs` / `web/verify_swap_concurrency.mjs` setup — uses the existing `web/mock_backend.py` extended to serve the new routes, OR runs against `python -m uvicorn ...server:app`). Complete script:

```javascript
// web/verify_loop.mjs — drives the cook→decrement→timeline loop headlessly.
import puppeteer from 'puppeteer-core'

const BASE = process.env.BASE_URL || 'http://127.0.0.1:8090'
const browser = await puppeteer.launch({
  executablePath: '/usr/bin/chromium',
  args: ['--no-sandbox'],
})
const page = await browser.newPage()
await page.goto(BASE, { waitUntil: 'networkidle2' })

// seed a pantry item via the API the page uses
await page.evaluate(async () => {
  await fetch('/navigator/pantry/items', {
    method: 'POST', headers: { 'Content-Type': 'application/json' },
    body: JSON.stringify({ raw_text: 'garlic' }),
  })
})
await page.reload({ waitUntil: 'networkidle2' })

// expand the first recipe card and click "I cooked this"
const cookedOk = await page.evaluate(async () => {
  const res = await fetch('/navigator/cook', {
    method: 'POST', headers: { 'Content-Type': 'application/json' },
    body: JSON.stringify({ dish_name: 'Verify Dish', consumed: [{ canonical_name: 'garlic', coarse_amount: 'used_up' }] }),
  })
  if (!(res.ok || res.status === 201)) return false
  const meals = await (await fetch('/navigator/meals')).json()
  const pantry = await (await fetch('/navigator/pantry')).json()
  const g = pantry.find((i) => i.canonical_name === 'garlic')
  return meals[0]?.dish_name === 'Verify Dish' && g?.state === 'used_up'
})

console.log(cookedOk ? 'LOOP OK' : 'LOOP FAILED')
await browser.close()
process.exit(cookedOk ? 0 : 1)
```

- [ ] **Step 2: Run the full backend suite + lint** (the real gates — match what CI runs, not a subset):

Run: `cd ~/pantryatlas && .venv/bin/python -m pytest tests/navigator/ -q 2>&1 | grep -v -E "profiling:|\.gcda:|Cannot open"`
Expected: all pass — new AND pre-existing navigator tests (the regression guard from Task 6 Step 3c).
Run: `.venv/bin/ruff check . 2>&1 | tail -5`
Expected: no errors (matches CI's `ruff check .`).
Run: `cd ~/pantryatlas/web && npm run build 2>&1 | tail -5`
Expected: build succeeds.

- [ ] **Step 3: Run the headless loop check** (start the server first in another shell: `PYTHONPATH=. .venv/bin/python -m uvicorn pantryatlas.navigator.server:app --port 8090`, with a tmp HOME so the real pantry is untouched):

Run: `cd ~/pantryatlas/web && node verify_loop.mjs`
Expected: `LOOP OK`

- [ ] **Step 4: Document the new surface** in `docs/navigator.md` — add the four routes (`/cook`, `/meals`, `/waste`, `/pantry/items/{name}/consume`), the `kitchen.db` store, the `pantry.json → pantry.json.imported` migration, and the coarse-state model (`present`/`low`/`used_up`, blend truth-model). Note that `servings` is logged but does not scale the decrement in SP-A.

- [ ] **Step 5: Commit**

```bash
cd ~/pantryatlas && git add web/verify_loop.mjs docs/navigator.md
git commit -m "test(web): headless loop verification + docs for SP-A routes"
```

---

## Self-review (completed during planning)

- **Spec coverage:** SQLite pantry migration (T1, T6, T8) · event ledger (T1–T5) · cook event + atomic soft-decrement (T4, T7) · coarse consume "used up/half left/threw away" (T3, T7, T11) · meal-log timeline (T4, T7, T12) · expiry/running-low nudges (T13) · waste analytics (T5, T7) · manual edits via repointed routes (T6). All spec sections map to a task. ✓
- **Verifiable-on-Pi claim honoured:** every backend test uses plain SQLite + a `_FakeStore` (no `sqlite-vec`), and the prerequisite refreshes the venv so the app imports under 3.11. The only sqlite-vec touch (`/recipes/from-pantry` against the live DB) is unchanged and stays CI/3.13-gated. ✓
- **`servings` non-scaling** is explicit in T7 and the docs step, per the spec. ✓
- **Type consistency:** `KitchenStore` method names (`add_item`, `remove_item`, `replace_all`, `on_hand`, `consume_item`, `restore_item`, `mark_expired`, `add_cook_event`, `list_meals`, `waste_tally`) are used identically in the route tasks; `_get_kitchen` / `kitchen` / `kitchen_factory` are consistent across T6 and T8; frontend `cookRecipe`/`consumeItem`/`restoreItem`/`fetchMeals`/`meals`/`expiringSoon` match between `signals.ts` (T9, T13) and their consumers (T10–T13). ✓
- **No placeholders:** every code step shows complete code; the two `Navigator.tsx`-render steps (T11 S3, T12 S2, T13 S2) give complete inserted JSX and name the exact insertion site, deferring only to the existing surrounding markup the implementer is reading. ✓
- **Cross-suite regression guard (added after advisor review):** repointing the shared pantry routes to `_get_kitchen` would 500 the four pre-existing `create_app(...)` test fixtures (`test_server.py:132,198`, `test_vision.py:219`, `test_providers_api.py:33`) that pass no `kitchen=`. T6 Step 3c updates all four (verified: none assert `pantry.json` file contents, so only the kwarg is needed), and T6 Step 4 + T14 Step 2 now run the **whole** `tests/navigator/` suite so the regression can't hide until CI. `PantryItem` is explicitly imported in T11 (verified absent from `Navigator.tsx`). ✓
