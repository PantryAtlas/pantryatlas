"""Recipe store backed by sqlite-vec."""

from __future__ import annotations

import json
import sqlite3
from dataclasses import dataclass, field
from pathlib import Path

import numpy as np
import sqlite_vec

_DIM = 1024

_DDL = """
CREATE TABLE IF NOT EXISTS recipes_meta (
    id                TEXT PRIMARY KEY,
    title             TEXT NOT NULL,
    language          TEXT NOT NULL,
    ingredients_json  TEXT,
    instructions      TEXT
);
CREATE VIRTUAL TABLE IF NOT EXISTS recipes_vec USING vec0(
    id        TEXT PRIMARY KEY,
    embedding float[1024]
);
"""


@dataclass
class Recipe:
    """One recipe with its 1024-d embedding."""

    id: str
    title: str
    language: str
    embedding: np.ndarray  # shape (1024,) float32
    ingredients_json: list[str] | None = field(default=None)
    instructions: str | None = field(default=None)


class RecipeStore:
    """Persistent recipe store backed by sqlite-vec.

    Stores recipe metadata and 1024-d float32 embeddings across two coupled
    tables: ``recipes_meta`` (regular) and ``recipes_vec`` (vec0 virtual
    table). Tables are created idempotently on open.

    Thread safety: the underlying connection is opened with
    ``check_same_thread=False`` to allow FastAPI's thread-pool handlers to
    share the same instance.  Concurrent *writes* are not safe — all write
    operations should be serialised by the caller (single-writer model).
    """

    def __init__(self, db_path: str | Path) -> None:
        self._path = str(db_path)
        self._conn = self._open()

    # ------------------------------------------------------------------
    # Internal helpers
    # ------------------------------------------------------------------

    def _open(self) -> sqlite3.Connection:
        # check_same_thread=False: allows the same connection to be used from
        # FastAPI's thread-pool handlers.  Single-writer usage is safe here.
        conn = sqlite3.connect(self._path, check_same_thread=False)
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
    def _from_row(row: tuple) -> Recipe:
        rid, title, language, ingredients_json, instructions, blob = row
        embedding = np.frombuffer(blob, dtype=np.float32).copy()
        ingredients = json.loads(ingredients_json) if ingredients_json else None
        return Recipe(
            id=rid,
            title=title,
            language=language,
            embedding=embedding,
            ingredients_json=ingredients,
            instructions=instructions,
        )

    # ------------------------------------------------------------------
    # Public API
    # ------------------------------------------------------------------

    def upsert(self, rows: list[Recipe]) -> None:
        """Insert or replace a list of recipes."""
        try:
            for row in rows:
                self._conn.execute(
                    """
                    INSERT INTO recipes_meta (id, title, language, ingredients_json, instructions)
                    VALUES (?, ?, ?, ?, ?)
                    ON CONFLICT(id) DO UPDATE SET
                        title            = excluded.title,
                        language         = excluded.language,
                        ingredients_json = excluded.ingredients_json,
                        instructions     = excluded.instructions
                    """,
                    (
                        row.id,
                        row.title,
                        row.language,
                        (
                            json.dumps(row.ingredients_json)
                            if row.ingredients_json is not None
                            else None
                        ),
                        row.instructions,
                    ),
                )
                # vec0 virtual tables do not support ON CONFLICT / UPSERT syntax;
                # use DELETE + INSERT instead.
                self._conn.execute("DELETE FROM recipes_vec WHERE id = ?", (row.id,))
                self._conn.execute(
                    "INSERT INTO recipes_vec (id, embedding) VALUES (?, ?)",
                    (row.id, self._to_blob(row.embedding)),
                )
            self._conn.commit()
        except Exception:
            self._conn.rollback()
            raise

    def get(self, id: str) -> Recipe | None:
        """Retrieve a single recipe by id, or None if not found."""
        row = self._conn.execute(
            """
            SELECT m.id, m.title, m.language, m.ingredients_json, m.instructions, v.embedding
            FROM recipes_meta m
            JOIN recipes_vec v ON v.id = m.id
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
    ) -> list[Recipe]:
        """Return the top_k nearest recipes by L2 distance.

        Args:
            vec: Query embedding, shape (1024,) float32.
            top_k: Number of results to return.
            filters: Optional dict of metadata filters (reserved for v0.2;
                raises NotImplementedError if non-None).

        Returns:
            List of Recipe objects sorted by ascending distance.
        """
        if filters is not None:
            raise NotImplementedError("query filters not yet supported; pass filters=None")
        blob = self._to_blob(vec)
        rows = self._conn.execute(
            """
            WITH knn AS (
                SELECT id, distance
                FROM recipes_vec
                WHERE embedding MATCH ?
                ORDER BY distance
                LIMIT ?
            )
            SELECT m.id, m.title, m.language, m.ingredients_json, m.instructions, v.embedding
            FROM knn
            JOIN recipes_meta m ON m.id = knn.id
            JOIN recipes_vec v ON v.id = knn.id
            ORDER BY knn.distance
            """,
            (blob, top_k),
        ).fetchall()
        return [self._from_row(r) for r in rows]

    def delete(self, id: str) -> None:
        """Delete a recipe by id from both tables."""
        self._conn.execute("DELETE FROM recipes_meta WHERE id = ?", (id,))
        self._conn.execute("DELETE FROM recipes_vec WHERE id = ?", (id,))
        self._conn.commit()

    def count(self) -> int:
        """Return the total number of recipes stored."""
        row = self._conn.execute("SELECT COUNT(*) FROM recipes_meta").fetchone()
        return row[0] if row else 0

    @staticmethod
    def _split_steps(text: str | None) -> list[str]:
        """Split a stored instruction blob into a list of step strings.

        RecipeNLG directions are stored as one string with steps on separate
        lines, each typically prefixed with ``- ``.  The navigator UI renders
        instructions as a list, so normalise to ``list[str]`` here (the single
        point where store rows enter the recipe-ranking pipeline).
        """
        if not text:
            return []
        steps: list[str] = []
        for raw_line in text.split("\n"):
            line = raw_line.strip()
            if line.startswith("- "):
                line = line[2:].strip()
            elif line.startswith("-"):
                line = line[1:].strip()
            if line:
                steps.append(line)
        return steps

    def iter_overlapping(self, canonical_names: list[str]) -> list[dict]:
        """Return recipe dicts whose ingredients_json overlaps any canonical name.

        Scans recipes_meta.ingredients_json in Python (no vec search) — suitable
        for the text-overlap pre-filter step in POST /navigator/recipes/from-pantry.
        Returns list of ``{title, ingredients, instructions}`` dicts, where
        ``instructions`` is a ``list[str]`` of steps.
        """
        if not canonical_names:
            return []
        name_set = set(canonical_names)
        rows = self._conn.execute(
            "SELECT title, ingredients_json, instructions FROM recipes_meta"
        ).fetchall()
        results = []
        for title, ingredients_json, instructions in rows:
            if not ingredients_json:
                continue
            ings = json.loads(ingredients_json)
            if any(ing in name_set for ing in ings):
                results.append(
                    {
                        "title": title,
                        "ingredients": ings,
                        "instructions": self._split_steps(instructions),
                    }
                )
        return results

    def close(self) -> None:
        """Close the underlying database connection."""
        self._conn.close()

    def __enter__(self) -> RecipeStore:
        return self

    def __exit__(self, *args: object) -> None:
        self.close()
