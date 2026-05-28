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


def _row_to_dict_from_cursor(cursor: sqlite3.Cursor, row: tuple) -> dict[str, Any]:
    """Convert a raw sqlite3 row tuple to a dict using cursor.description."""
    cols = [d[0] for d in cursor.description]
    return dict(zip(cols, row))


class KitchenStore:
    def __init__(self, db_path: str | Path, pantry_json_path: str | Path | None = None) -> None:
        self._path = str(db_path)
        self._conn = self._open()
        if pantry_json_path is not None:
            self._migrate_from_json(Path(pantry_json_path))

    def _open(self) -> sqlite3.Connection:
        Path(self._path).parent.mkdir(parents=True, exist_ok=True)
        # No row_factory — keep raw tuples so direct _conn.execute().fetchall()
        # calls in tests return plain tuples (comparable + sortable).
        conn = sqlite3.connect(self._path, check_same_thread=False)
        for stmt in _DDL.strip().split(";"):
            stmt = stmt.strip()
            if stmt:
                conn.execute(stmt)
        conn.commit()
        return conn

    def _fetchone(self, sql: str, params: tuple = ()) -> dict[str, Any] | None:
        cur = self._conn.execute(sql, params)
        row = cur.fetchone()
        if row is None:
            return None
        return _row_to_dict_from_cursor(cur, row)

    def _fetchall(self, sql: str, params: tuple = ()) -> list[dict[str, Any]]:
        cur = self._conn.execute(sql, params)
        rows = cur.fetchall()
        cols = [d[0] for d in cur.description]
        return [dict(zip(cols, r)) for r in rows]

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
    def _row_to_dict(row: dict[str, Any]) -> dict[str, Any]:
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
        rows = self._fetchall("SELECT * FROM pantry_items ORDER BY canonical_name")
        return [self._row_to_dict(r) for r in rows]
