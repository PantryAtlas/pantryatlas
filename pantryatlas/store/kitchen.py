"""KitchenStore — mutable user state (pantry + event ledger + cook log).

Plain SQLite (no sqlite-vec), so it runs on every Python including this Pi's
3.11 build that lacks ``enable_load_extension``.  Kept separate from the static
``recipes.db``.  Single-writer model: ``check_same_thread=False`` lets FastAPI's
thread pool share one connection; writes are serialised by ``self._lock``
(a ``threading.Lock``) so concurrent FastAPI worker threads cannot interleave
transactions.
"""

from __future__ import annotations

import json
import secrets
import sqlite3
import threading
from datetime import UTC, date, datetime, timedelta
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
CREATE TABLE IF NOT EXISTS off_cache (
    code         TEXT PRIMARY KEY,
    product_json TEXT NOT NULL,
    fetched_at   TEXT NOT NULL
);
CREATE TABLE IF NOT EXISTS devices (
    device_id    TEXT PRIMARY KEY,
    name         TEXT NOT NULL,
    role         TEXT NOT NULL,
    kind         TEXT,
    caps_json    TEXT,
    status       TEXT NOT NULL DEFAULT 'pending',
    token_hash   TEXT,
    enrolled_at  TEXT NOT NULL,
    paired_at    TEXT,
    last_seen    TEXT
);
"""


def _now_iso() -> str:
    return datetime.now(UTC).isoformat()


def _row_to_dict_from_cursor(cursor: sqlite3.Cursor, row: tuple) -> dict[str, Any]:
    """Convert a raw sqlite3 row tuple to a dict using cursor.description."""
    cols = [d[0] for d in cursor.description]
    return dict(zip(cols, row, strict=True))


class KitchenStore:
    def __init__(self, db_path: str | Path, pantry_json_path: str | Path | None = None) -> None:
        self._path = str(db_path)
        self._conn = self._open()
        self._lock = threading.Lock()
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
        return [dict(zip(cols, r, strict=True)) for r in rows]

    def _migrate_from_json(self, json_path: Path) -> None:
        # Only migrate when the table is empty AND the json still exists.
        count = self._conn.execute("SELECT COUNT(*) FROM pantry_items").fetchone()[0]
        if count or not json_path.exists():
            return
        try:
            raw = json.loads(json_path.read_text(encoding="utf-8"))
        except (ValueError, OSError):
            return  # corrupt/unreadable → start empty, never fatal
        # Guard against structurally-malformed but valid JSON (e.g. a dict).
        if not isinstance(raw, list):
            json_path.rename(json_path.with_suffix(json_path.suffix + ".imported"))
            return
        now = _now_iso()
        with self._lock:
            for item in raw:
                try:
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
                except (KeyError, TypeError):
                    continue  # malformed row → skip, don't abort the whole migration
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
            item["quantity"] = {
                "amount": row["quantity_amount"],
                "unit": row["quantity_unit"] or "",
            }
        if row["expires_at"] is not None:
            item["expires_at"] = row["expires_at"]
        return item

    def list_items(self) -> list[dict[str, Any]]:
        rows = self._fetchall("SELECT * FROM pantry_items ORDER BY canonical_name")
        return [self._row_to_dict(r) for r in rows]

    def _log_event(self, canonical_name: str, change_type: str, source: str,
                   detail: dict | None = None) -> None:
        self._conn.execute(
            "INSERT INTO inventory_events (ts, canonical_name, change_type, detail_json, source) "
            "VALUES (?,?,?,?,?)",
            (_now_iso(), canonical_name, change_type,
             json.dumps(detail) if detail else None, source),
        )

    def _upsert_item(self, ingredient: Ingredient, now: str, source: str) -> None:
        """Execute the pantry_items upsert SQL without committing or logging."""
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

    def add_item(self, ingredient: Ingredient, source: str = "manual") -> dict[str, Any]:
        with self._lock:
            now = _now_iso()
            self._upsert_item(ingredient, now, source)
            self._log_event(ingredient.canonical_name, "add", source)
            self._conn.commit()
            return self.get_item(ingredient.canonical_name)

    def get_item(self, canonical_name: str) -> dict[str, Any] | None:
        row = self._fetchone(
            "SELECT * FROM pantry_items WHERE canonical_name=?", (canonical_name,)
        )
        return self._row_to_dict(row) if row is not None else None

    def remove_item(self, canonical_name: str) -> None:
        with self._lock:
            cur = self._conn.execute(
                "DELETE FROM pantry_items WHERE canonical_name=?", (canonical_name,)
            )
            if cur.rowcount:
                self._log_event(canonical_name, "adjust", "manual", {"removed": True})
            self._conn.commit()

    def replace_all(
        self, ingredients: list[Ingredient], source: str = "manual"
    ) -> list[dict[str, Any]]:
        existing = {i["canonical_name"] for i in self.list_items()}
        incoming = {ing.canonical_name for ing in ingredients}
        now = _now_iso()
        with self._lock:
            try:
                for gone in existing - incoming:
                    self._conn.execute(
                        "DELETE FROM pantry_items WHERE canonical_name=?", (gone,)
                    )
                    self._log_event(gone, "adjust", source, {"removed": True})
                for ing in ingredients:
                    self._upsert_item(ing, now, source)
                    self._log_event(ing.canonical_name, "add", source)
                self._conn.commit()
            except Exception:
                self._conn.rollback()
                raise
        return self.list_items()

    def on_hand(self) -> Pantry:
        """Return a Pantry of present+low items for recipe ranking."""
        placeholders = ",".join("?" * len(_ON_HAND_STATES))
        rows = self._fetchall(
            f"SELECT * FROM pantry_items WHERE state IN ({placeholders})",
            _ON_HAND_STATES,
        )
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

    @staticmethod
    def _next_state(state: str, coarse_amount: str) -> tuple[str, float]:
        if coarse_amount == "half":
            if state == "present":
                return ("low", 0.5)
            if state == "used_up":
                # A used-up item cannot be partially restored by a half-consume;
                # it stays used_up with confidence 0.0 (not the contradictory 0.5).
                return ("used_up", 0.0)
            return (state, 0.5)  # 'low' stays low
        if coarse_amount in ("used_up", "discarded"):
            return ("used_up", 0.0)
        # 'cook' (tap-to-cook default): one notch down
        if state == "present":
            return ("low", 0.5)
        return ("used_up", 0.0)

    def consume_item(self, canonical_name: str, coarse_amount: str,
                     source: str = "manual") -> dict[str, Any] | None:
        with self._lock:
            row = self._conn.execute(
                "SELECT state FROM pantry_items WHERE canonical_name=?", (canonical_name,)
            ).fetchone()
            if row is None:
                return None
            new_state, new_conf = self._next_state(row[0], coarse_amount)
            self._conn.execute(
                "UPDATE pantry_items "
                "SET state=?, confidence=?, updated_at=? WHERE canonical_name=?",
                (new_state, new_conf, _now_iso(), canonical_name),
            )
            change_type = "discard" if coarse_amount == "discarded" else "consume"
            # Waste invariant: don't double-count a discard on an already-used_up item.
            if not (change_type == "discard" and row[0] == "used_up"):
                self._log_event(canonical_name, change_type, source,
                                {"coarse_amount": coarse_amount, "prev_state": row[0]})
            self._conn.commit()
            return self.get_item(canonical_name)

    def restore_item(self, canonical_name: str, source: str = "manual") -> dict[str, Any] | None:
        with self._lock:
            now = _now_iso()
            cur = self._conn.execute(
                "UPDATE pantry_items "
                "SET state='present', confidence=1.0, last_observed_at=?, updated_at=? "
                "WHERE canonical_name=?",
                (now, now, canonical_name),
            )
            if not cur.rowcount:
                return None
            self._log_event(canonical_name, "observe", source)
            self._conn.commit()
            return self.get_item(canonical_name)

    def add_cook_event(self, *, dish_name: str, consumed: list[dict[str, Any]],
                       recipe_id: str | None = None, servings: float | None = None,
                       photo_path: str | None = None, rating: int | None = None,
                       notes: str | None = None, source: str = "tap-to-cook") -> dict[str, Any]:
        """Atomically record a cook event and soft-decrement consumed on-hand items."""
        with self._lock:
            on_hand = {
                r[0]
                for r in self._conn.execute(
                    f"SELECT canonical_name FROM pantry_items "
                    f"WHERE state IN ({','.join('?' * len(_ON_HAND_STATES))})",
                    _ON_HAND_STATES,
                ).fetchall()
            }
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
                        state_row = self._conn.execute(
                            "SELECT state FROM pantry_items WHERE canonical_name=?", (name,)
                        ).fetchone()
                        new_state, new_conf = self._next_state(
                            state_row[0], c.get("coarse_amount", "cook")
                        )
                        self._conn.execute(
                            "UPDATE pantry_items SET state=?, confidence=?, updated_at=? "
                            "WHERE canonical_name=?",
                            (new_state, new_conf, _now_iso(), name),
                        )
                        evt_change_type = (
                            "discard" if c.get("coarse_amount") == "discarded" else "consume"
                        )
                        # Waste invariant (mirror consume_item / mark_expired): a discard is
                        # logged only on the transition into used_up. on_hand is a stale
                        # snapshot, so a canonical name repeated as 'discarded' in one payload
                        # would otherwise log twice — guard on the freshly-read prior state.
                        if not (evt_change_type == "discard" and state_row[0] == "used_up"):
                            self._log_event(name, evt_change_type, source,
                                            {"cook_event_id": event_id})
                    else:
                        unmatched.append(name)
                self._conn.commit()
            except Exception:
                self._conn.rollback()
                raise
        return {"id": event_id, "dish_name": dish_name, "matched": matched, "unmatched": unmatched}

    @staticmethod
    def _cook_row_to_dict(row: dict[str, Any]) -> dict[str, Any]:
        return {
            "id": row["id"], "recipe_id": row["recipe_id"], "dish_name": row["dish_name"],
            "servings": row["servings"], "cooked_at": row["cooked_at"],
            "photo_path": row["photo_path"], "rating": row["rating"], "notes": row["notes"],
            "consumed": json.loads(row["consumed_json"]) if row["consumed_json"] else [],
            "source": row["source"],
        }

    def list_meals(self, limit: int = 50) -> list[dict[str, Any]]:
        rows = self._fetchall(
            "SELECT * FROM cook_events ORDER BY id DESC LIMIT ?", (limit,)
        )
        return [self._cook_row_to_dict(r) for r in rows]

    def update_cook_event(self, event_id: int, *, rating: int | None = None,
                          notes: str | None = None) -> dict[str, Any] | None:
        """Attach a rating (1-5) and/or note to an existing cook event.

        Only provided (non-None) fields are written. Returns the updated event
        dict, or None if event_id is unknown. Raises ValueError on bad rating.
        """
        if rating is not None and (
            not isinstance(rating, int) or isinstance(rating, bool) or not 1 <= rating <= 5
        ):
            raise ValueError("rating must be an int in 1..5")
        with self._lock:
            exists = self._conn.execute(
                "SELECT 1 FROM cook_events WHERE id=?", (event_id,)
            ).fetchone()
            if exists is None:
                return None
            sets, params = [], []
            if rating is not None:
                sets.append("rating=?")
                params.append(rating)
            if notes is not None:
                sets.append("notes=?")
                params.append(notes)
            if sets:
                params.append(event_id)
                self._conn.execute(
                    f"UPDATE cook_events SET {', '.join(sets)} WHERE id=?", params
                )
                self._conn.commit()
            row = self._fetchone("SELECT * FROM cook_events WHERE id=?", (event_id,))
        return self._cook_row_to_dict(row)

    def mark_expired(self, canonical_name: str, source: str = "manual") -> dict[str, Any] | None:
        with self._lock:
            row = self._conn.execute(
                "SELECT state FROM pantry_items WHERE canonical_name=?", (canonical_name,)
            ).fetchone()
            if row is None:
                return None
            if row[0] == "used_up":
                # Already off-hand — don't fabricate a second expire event.
                return self.get_item(canonical_name)
            self._conn.execute(
                "UPDATE pantry_items SET state='used_up', confidence=0.0, updated_at=? "
                "WHERE canonical_name=?",
                (_now_iso(), canonical_name),
            )
            self._log_event(canonical_name, "expire", source)
            self._conn.commit()
            return self.get_item(canonical_name)

    def set_expiry(self, canonical_name: str, expires_at: date | None,
                   source: str = "manual") -> dict[str, Any] | None:
        """Set or clear an item's expiry date.

        Stored as a pure ``YYYY-MM-DD`` string (or NULL when cleared) — the web
        ``parseLocalDate`` splits on ``-`` and would NaN on a full ISO datetime.
        Logs a ``set_expiry`` event, which is NOT a waste event.
        """
        iso = expires_at.isoformat() if expires_at is not None else None
        with self._lock:
            cur = self._conn.execute(
                "UPDATE pantry_items SET expires_at=?, updated_at=? "
                "WHERE canonical_name=?",
                (iso, _now_iso(), canonical_name),
            )
            if not cur.rowcount:
                return None
            self._log_event(canonical_name, "set_expiry", source, {"expires_at": iso})
            self._conn.commit()
            return self.get_item(canonical_name)

    def cache_off(self, code: str, product: dict[str, Any]) -> None:
        with self._lock:
            self._conn.execute(
                "INSERT INTO off_cache (code, product_json, fetched_at) VALUES (?,?,?) "
                "ON CONFLICT(code) DO UPDATE SET product_json=excluded.product_json, "
                "fetched_at=excluded.fetched_at",
                (code, json.dumps(product), _now_iso()),
            )
            self._conn.commit()

    def get_cached_off(self, code: str) -> dict[str, Any] | None:
        """Return cached OFF product dict for *code*, or None if not cached.

        The cache is intentionally indefinite in v1 (no TTL); ``fetched_at``
        is stored for a future TTL policy.
        """
        row = self._conn.execute(
            "SELECT product_json FROM off_cache WHERE code=?", (code,)
        ).fetchone()
        return json.loads(row[0]) if row is not None else None

    @staticmethod
    def _device_to_dict(row: dict[str, Any]) -> dict[str, Any]:
        # token_hash is deliberately NOT exposed
        return {
            "device_id": row["device_id"], "name": row["name"], "role": row["role"],
            "kind": row["kind"], "caps": json.loads(row["caps_json"]) if row["caps_json"] else [],
            "status": row["status"], "enrolled_at": row["enrolled_at"],
            "paired_at": row["paired_at"], "last_seen": row["last_seen"],
        }

    def enroll_device(self, name: str, role: str, kind: str | None = None,
                      caps: list[str] | None = None) -> dict[str, Any]:
        device_id = secrets.token_hex(8)
        now = _now_iso()
        with self._lock:
            self._conn.execute(
                "INSERT INTO devices (device_id, name, role, kind, caps_json, status, enrolled_at) "
                "VALUES (?,?,?,?,?, 'pending', ?)",
                (device_id, name, role, kind, json.dumps(caps) if caps else None, now),
            )
            self._conn.commit()
        return self.get_device(device_id)

    def get_device(self, device_id: str) -> dict[str, Any] | None:
        row = self._fetchone("SELECT * FROM devices WHERE device_id=?", (device_id,))
        return self._device_to_dict(row) if row is not None else None

    def list_devices(self) -> list[dict[str, Any]]:
        rows = self._fetchall("SELECT * FROM devices ORDER BY enrolled_at DESC")
        return [self._device_to_dict(r) for r in rows]

    def approve_device(self, device_id: str, token_hash: str) -> dict[str, Any] | None:
        with self._lock:
            cur = self._conn.execute(
                "UPDATE devices SET status='paired', token_hash=?, paired_at=? WHERE device_id=?",
                (token_hash, _now_iso(), device_id),
            )
            if not cur.rowcount:
                return None
            self._conn.commit()
        return self.get_device(device_id)

    def reject_device(self, device_id: str) -> dict[str, Any] | None:
        with self._lock:
            cur = self._conn.execute(
                "UPDATE devices SET status='rejected', token_hash=NULL WHERE device_id=?",
                (device_id,),
            )
            if not cur.rowcount:
                return None
            self._conn.commit()
        return self.get_device(device_id)

    def remove_device(self, device_id: str) -> bool:
        with self._lock:
            cur = self._conn.execute("DELETE FROM devices WHERE device_id=?", (device_id,))
            self._conn.commit()
            return bool(cur.rowcount)

    def device_by_token_hash(self, token_hash: str) -> dict[str, Any] | None:
        with self._lock:
            row = self._conn.execute(
                "SELECT device_id FROM devices WHERE token_hash=? AND status='paired'",
                (token_hash,),
            ).fetchone()
            if row is None:
                return None
            device_id = row[0]
            self._conn.execute(
                "UPDATE devices SET last_seen=? WHERE device_id=?", (_now_iso(), device_id)
            )
            self._conn.commit()
        return self.get_device(device_id)

    def waste_tally(self, window_days: int = 30) -> dict[str, Any]:
        cutoff = (datetime.now(UTC) - timedelta(days=window_days)).isoformat()
        rows = self._conn.execute(
            "SELECT canonical_name, change_type FROM inventory_events "
            "WHERE change_type IN ('discard','expire') AND ts >= ?",
            (cutoff,),
        ).fetchall()
        discarded = sum(1 for r in rows if r[1] == "discard")
        expired = sum(1 for r in rows if r[1] == "expire")
        counts: dict[str, int] = {}
        for r in rows:
            counts[r[0]] = counts.get(r[0], 0) + 1
        by_item = [
            {"name": n, "count": c}
            for n, c in sorted(counts.items(), key=lambda kv: (-kv[1], kv[0]))
        ]
        return {
            "window_days": window_days,
            "discarded": discarded,
            "expired": expired,
            "total": discarded + expired,
            "items": [r[0] for r in rows],
            "by_item": by_item,
        }
