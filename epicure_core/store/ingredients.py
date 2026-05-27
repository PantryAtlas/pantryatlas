"""Ingredient store backed by sqlite-vec."""

from __future__ import annotations

import json
import sqlite3
from dataclasses import dataclass, field
from pathlib import Path

import numpy as np
import sqlite_vec

_DIM = 1024

_DDL = """
CREATE TABLE IF NOT EXISTS ingredients_meta (
    id             TEXT PRIMARY KEY,
    canonical_name TEXT NOT NULL,
    language       TEXT NOT NULL,
    aliases        TEXT,
    source         TEXT
);
CREATE VIRTUAL TABLE IF NOT EXISTS ingredients_vec USING vec0(
    id        TEXT PRIMARY KEY,
    embedding float[1024]
);
"""


@dataclass
class Ingredient:
    """One ingredient with its 1024-d embedding."""

    id: str
    canonical_name: str
    language: str
    embedding: np.ndarray  # shape (1024,) float32
    aliases: list[str] | None = field(default=None)
    source: str | None = field(default=None)


class IngredientStore:
    """Persistent ingredient store backed by sqlite-vec.

    Stores ingredient metadata and 1024-d float32 embeddings across two
    coupled tables: ``ingredients_meta`` (regular) and ``ingredients_vec``
    (vec0 virtual table). Tables are created idempotently on open.

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
    def _from_row(row: tuple) -> Ingredient:
        rid, canonical_name, language, aliases_json, source, blob = row
        embedding = np.frombuffer(blob, dtype=np.float32).copy()
        aliases = json.loads(aliases_json) if aliases_json else None
        return Ingredient(
            id=rid,
            canonical_name=canonical_name,
            language=language,
            embedding=embedding,
            aliases=aliases,
            source=source,
        )

    # ------------------------------------------------------------------
    # Public API
    # ------------------------------------------------------------------

    def upsert(self, rows: list[Ingredient]) -> None:
        """Insert or replace a list of ingredients."""
        try:
            for row in rows:
                self._conn.execute(
                    """
                    INSERT INTO ingredients_meta (id, canonical_name, language, aliases, source)
                    VALUES (?, ?, ?, ?, ?)
                    ON CONFLICT(id) DO UPDATE SET
                        canonical_name = excluded.canonical_name,
                        language       = excluded.language,
                        aliases        = excluded.aliases,
                        source         = excluded.source
                    """,
                    (
                        row.id,
                        row.canonical_name,
                        row.language,
                        json.dumps(row.aliases) if row.aliases is not None else None,
                        row.source,
                    ),
                )
                # vec0 virtual tables do not support ON CONFLICT / UPSERT syntax;
                # use DELETE + INSERT instead.
                self._conn.execute("DELETE FROM ingredients_vec WHERE id = ?", (row.id,))
                self._conn.execute(
                    "INSERT INTO ingredients_vec (id, embedding) VALUES (?, ?)",
                    (row.id, self._to_blob(row.embedding)),
                )
            self._conn.commit()
        except Exception:
            self._conn.rollback()
            raise

    def get(self, id: str) -> Ingredient | None:
        """Retrieve a single ingredient by id, or None if not found."""
        row = self._conn.execute(
            """
            SELECT m.id, m.canonical_name, m.language, m.aliases, m.source, v.embedding
            FROM ingredients_meta m
            JOIN ingredients_vec v ON v.id = m.id
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
    ) -> list[Ingredient]:
        """Return the top_k nearest ingredients by L2 distance.

        Args:
            vec: Query embedding, shape (1024,) float32.
            top_k: Number of results to return.
            filters: Optional dict of metadata filters (reserved for v0.2;
                raises NotImplementedError if non-None).

        Returns:
            List of Ingredient objects sorted by ascending distance.
        """
        if filters is not None:
            raise NotImplementedError("query filters not yet supported; pass filters=None")
        blob = self._to_blob(vec)
        rows = self._conn.execute(
            """
            WITH knn AS (
                SELECT id, distance
                FROM ingredients_vec
                WHERE embedding MATCH ?
                ORDER BY distance
                LIMIT ?
            )
            SELECT m.id, m.canonical_name, m.language, m.aliases, m.source, v.embedding
            FROM knn
            JOIN ingredients_meta m ON m.id = knn.id
            JOIN ingredients_vec v ON v.id = knn.id
            ORDER BY knn.distance
            """,
            (blob, top_k),
        ).fetchall()
        return [self._from_row(r) for r in rows]

    def delete(self, id: str) -> None:
        """Delete an ingredient by id from both tables."""
        self._conn.execute("DELETE FROM ingredients_meta WHERE id = ?", (id,))
        self._conn.execute("DELETE FROM ingredients_vec WHERE id = ?", (id,))
        self._conn.commit()

    def close(self) -> None:
        """Close the underlying database connection."""
        self._conn.close()

    def __enter__(self) -> IngredientStore:
        return self

    def __exit__(self, *args: object) -> None:
        self.close()
