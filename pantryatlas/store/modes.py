"""Mode store backed by sqlite-vec.

schema reserved for v0.2 — insert path will be populated by the deferred
ICA+GMM pipeline once cluster centroids are available.
"""

from __future__ import annotations

import json
import sqlite3
from dataclasses import dataclass, field
from pathlib import Path

import numpy as np
import sqlite_vec

_DIM = 1024

_DDL = """
CREATE TABLE IF NOT EXISTS modes_meta (
    id          TEXT PRIMARY KEY,
    label_en    TEXT NOT NULL,
    label_local TEXT,
    top_members TEXT
);
CREATE VIRTUAL TABLE IF NOT EXISTS modes_vec USING vec0(
    id        TEXT PRIMARY KEY,
    embedding float[1024]
);
"""


@dataclass
class Mode:
    """One flavor-mode cluster centroid with its 1024-d embedding."""

    id: str
    label_en: str
    embedding: np.ndarray  # shape (1024,) float32
    label_local: str | None = field(default=None)
    top_members: list[str] | None = field(default=None)


class ModeStore:
    """Persistent mode store backed by sqlite-vec.

    schema reserved for v0.2 — the insert path will be populated by the
    deferred ICA+GMM pipeline once cluster centroids are available from the
    full vocabulary corpus.

    Stores mode metadata and 1024-d float32 embeddings across two coupled
    tables: ``modes_meta`` (regular) and ``modes_vec`` (vec0 virtual table).
    Tables are created idempotently on open.

    Not thread-safe: each thread must use its own store instance
    (sqlite3 ``check_same_thread=True``).
    """

    def __init__(self, db_path: str | Path) -> None:
        self._path = str(db_path)
        self._conn = self._open()

    # ------------------------------------------------------------------
    # Internal helpers
    # ------------------------------------------------------------------

    def _open(self) -> sqlite3.Connection:
        conn = sqlite3.connect(self._path)
        conn.enable_load_extension(True)
        sqlite_vec.load(conn)
        conn.enable_load_extension(False)
        for stmt in _DDL.strip().split(";"):
            stmt = stmt.strip()
            if stmt:
                conn.execute(stmt)
        conn.commit()
        return conn

    @staticmethod
    def _to_blob(arr: np.ndarray) -> bytes:
        return arr.astype(np.float32).tobytes()

    @staticmethod
    def _from_row(row: tuple) -> Mode:
        rid, label_en, label_local, top_members_json, blob = row
        embedding = np.frombuffer(blob, dtype=np.float32).copy()
        top_members = json.loads(top_members_json) if top_members_json else None
        return Mode(
            id=rid,
            label_en=label_en,
            embedding=embedding,
            label_local=label_local,
            top_members=top_members,
        )

    # ------------------------------------------------------------------
    # Public API
    # ------------------------------------------------------------------

    def upsert(self, rows: list[Mode]) -> None:
        """Insert or replace a list of modes.

        Note: schema reserved for v0.2 — in v0.1 this method is implemented
        but the production pipeline does not call it.
        """
        try:
            for row in rows:
                self._conn.execute(
                    """
                    INSERT INTO modes_meta (id, label_en, label_local, top_members)
                    VALUES (?, ?, ?, ?)
                    ON CONFLICT(id) DO UPDATE SET
                        label_en    = excluded.label_en,
                        label_local = excluded.label_local,
                        top_members = excluded.top_members
                    """,
                    (
                        row.id,
                        row.label_en,
                        row.label_local,
                        json.dumps(row.top_members) if row.top_members is not None else None,
                    ),
                )
                # vec0 virtual tables do not support ON CONFLICT / UPSERT syntax;
                # use DELETE + INSERT instead.
                self._conn.execute("DELETE FROM modes_vec WHERE id = ?", (row.id,))
                self._conn.execute(
                    "INSERT INTO modes_vec (id, embedding) VALUES (?, ?)",
                    (row.id, self._to_blob(row.embedding)),
                )
            self._conn.commit()
        except Exception:
            self._conn.rollback()
            raise

    def get(self, id: str) -> Mode | None:
        """Retrieve a single mode by id, or None if not found."""
        row = self._conn.execute(
            """
            SELECT m.id, m.label_en, m.label_local, m.top_members, v.embedding
            FROM modes_meta m
            JOIN modes_vec v ON v.id = m.id
            WHERE m.id = ?
            """,
            (id,),
        ).fetchone()
        if row is None:
            return None
        return self._from_row(row)

    def query_by_vector(
        self,
        vec: np.ndarray,
        top_k: int = 5,
        filters: dict | None = None,
    ) -> list[Mode]:
        """Return the top_k nearest modes by L2 distance.

        Args:
            vec: Query embedding, shape (1024,) float32.
            top_k: Number of results to return.
            filters: Optional dict of metadata filters (reserved for v0.2;
                raises NotImplementedError if non-None).

        Returns:
            List of Mode objects sorted by ascending distance.
        """
        if filters is not None:
            raise NotImplementedError("query filters not yet supported; pass filters=None")
        blob = self._to_blob(vec)
        rows = self._conn.execute(
            """
            WITH knn AS (
                SELECT id, distance
                FROM modes_vec
                WHERE embedding MATCH ?
                ORDER BY distance
                LIMIT ?
            )
            SELECT m.id, m.label_en, m.label_local, m.top_members, v.embedding
            FROM knn
            JOIN modes_meta m ON m.id = knn.id
            JOIN modes_vec v ON v.id = knn.id
            ORDER BY knn.distance
            """,
            (blob, top_k),
        ).fetchall()
        return [self._from_row(r) for r in rows]

    def delete(self, id: str) -> None:
        """Delete a mode by id from both tables."""
        self._conn.execute("DELETE FROM modes_meta WHERE id = ?", (id,))
        self._conn.execute("DELETE FROM modes_vec WHERE id = ?", (id,))
        self._conn.commit()

    def close(self) -> None:
        """Close the underlying database connection."""
        self._conn.close()

    def __enter__(self) -> ModeStore:
        return self

    def __exit__(self, *args: object) -> None:
        self.close()
