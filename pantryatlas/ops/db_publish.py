"""Publish helpers for the prebuilt recipe DB artifact.

Pure, testable building blocks used by ops/release/publish-db.sh:
- sha256_file  : checksum a file
- recipe_count : row count of recipes_meta (plain sqlite3, no vec extension)
- stamp_db     : write version/model metadata into a recipes.db (idempotent)
- build_manifest : assemble the release manifest dict

CLI (`python -m pantryatlas.ops.db_publish`) stamps a DB, writes per-version and
latest manifest JSON to an output dir, and prints the bootstrap pins.
"""

from __future__ import annotations

import argparse
import datetime as _dt
import hashlib
import json
import sqlite3
from pathlib import Path
from typing import Any

DB_SCHEMA_VERSION = 1
EMBEDDING_MODEL = "bge-m3-int8-onnx"
SOURCE = "RecipeNLG"
LICENSE = "CC-BY-NC-4.0"
DEFAULT_BASE_URL = "https://dl.pantryatlas.org/db"


def sha256_file(path: str | Path, *, chunk_size: int = 1 << 20) -> str:
    h = hashlib.sha256()
    with open(path, "rb") as fh:
        for chunk in iter(lambda: fh.read(chunk_size), b""):
            h.update(chunk)
    return h.hexdigest()


def recipe_count(db_path: str | Path) -> int:
    conn = sqlite3.connect(str(db_path))
    try:
        return conn.execute("SELECT COUNT(*) FROM recipes_meta").fetchone()[0]
    finally:
        conn.close()


def _utcnow() -> str:
    return _dt.datetime.now(_dt.UTC).strftime("%Y-%m-%dT%H:%M:%SZ")


def stamp_db(
    db_path: str | Path,
    *,
    db_version: str,
    embedding_model: str = EMBEDDING_MODEL,
    schema_version: int = DB_SCHEMA_VERSION,
    source: str = SOURCE,
    license: str = LICENSE,
    built_at: str | None = None,
) -> dict[str, str]:
    """Write version/model metadata into the DB. Idempotent.

    Sets ``PRAGMA user_version`` and upserts rows into ``_pantryatlas_db_meta``.
    Returns the metadata dict written.
    """
    meta = {
        "db_version": db_version,
        "embedding_model": embedding_model,
        "schema_version": str(schema_version),
        "source": source,
        "license": license,
        "built_at": built_at or _utcnow(),
    }
    conn = sqlite3.connect(str(db_path))
    try:
        conn.execute(f"PRAGMA user_version = {int(schema_version)}")
        conn.execute(
            "CREATE TABLE IF NOT EXISTS _pantryatlas_db_meta "
            "(key TEXT PRIMARY KEY, value TEXT)"
        )
        conn.executemany(
            "INSERT INTO _pantryatlas_db_meta (key, value) VALUES (?, ?) "
            "ON CONFLICT(key) DO UPDATE SET value = excluded.value",
            list(meta.items()),
        )
        conn.commit()
    finally:
        conn.close()
    return meta


def build_manifest(
    *,
    db_version: str,
    sha256: str,
    bytes_: int,
    recipe_count: int,
    built_at: str,
    embedding_model: str = EMBEDDING_MODEL,
    schema_version: int = DB_SCHEMA_VERSION,
    source: str = SOURCE,
    license: str = LICENSE,
    base_url: str = DEFAULT_BASE_URL,
) -> dict[str, Any]:
    return {
        "db_version": db_version,
        "schema_version": schema_version,
        "embedding_model": embedding_model,
        "recipe_count": recipe_count,
        "source": source,
        "license": license,
        "url": f"{base_url}/recipes-{db_version}.db",
        "sha256": sha256,
        "bytes": bytes_,
        "built_at": built_at,
    }


def main() -> None:
    parser = argparse.ArgumentParser(prog="pantryatlas.ops.db_publish")
    parser.add_argument("--db", type=Path, required=True, help="Path to recipes.db")
    parser.add_argument(
        "--version", required=True, help="Release version, e.g. v0.2.0"
    )
    parser.add_argument("--base-url", default=DEFAULT_BASE_URL)
    parser.add_argument(
        "--built-at", default=None, help="ISO-8601 UTC; defaults to DB file mtime"
    )
    parser.add_argument(
        "--out-dir", type=Path, required=True, help="Directory for manifest JSON"
    )
    args = parser.parse_args()

    if not args.db.exists():
        parser.error(f"DB not found: {args.db}")

    built_at = args.built_at or _dt.datetime.fromtimestamp(
        args.db.stat().st_mtime, _dt.UTC
    ).strftime("%Y-%m-%dT%H:%M:%SZ")

    stamp_db(args.db, db_version=args.version, built_at=built_at)
    sha = sha256_file(args.db)
    size = args.db.stat().st_size
    count = recipe_count(args.db)
    manifest = build_manifest(
        db_version=args.version,
        sha256=sha,
        bytes_=size,
        recipe_count=count,
        built_at=built_at,
        base_url=args.base_url,
    )

    args.out_dir.mkdir(parents=True, exist_ok=True)
    body = json.dumps(manifest, indent=2) + "\n"
    (args.out_dir / f"recipes-{args.version}.json").write_text(body)
    (args.out_dir / "recipes-latest.json").write_text(body)

    print("# --- paste into ops/pi-bootstrap.sh ---")
    print(f'RECIPES_DB_URL="{manifest["url"]}"')
    print(f'RECIPES_DB_SHA256="{sha}"')
    print(f"# recipes={count} bytes={size} built_at={built_at}")


if __name__ == "__main__":
    main()
