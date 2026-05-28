import hashlib
import sqlite3

from pantryatlas.ops import db_publish


def _make_db(path, n=3):
    conn = sqlite3.connect(str(path))
    conn.execute(
        "CREATE TABLE recipes_meta "
        "(id TEXT PRIMARY KEY, title TEXT, language TEXT, "
        "ingredients_json TEXT, instructions TEXT)"
    )
    conn.executemany(
        "INSERT INTO recipes_meta VALUES (?,?,?,?,?)",
        [(str(i), f"t{i}", "en", "[]", "x") for i in range(n)],
    )
    conn.commit()
    conn.close()


def test_sha256_file(tmp_path):
    f = tmp_path / "x.bin"
    f.write_bytes(b"hello")
    assert db_publish.sha256_file(f) == hashlib.sha256(b"hello").hexdigest()


def test_recipe_count(tmp_path):
    db = tmp_path / "r.db"
    _make_db(db, 5)
    assert db_publish.recipe_count(db) == 5


def test_stamp_db_sets_user_version_and_meta(tmp_path):
    db = tmp_path / "r.db"
    _make_db(db, 2)
    db_publish.stamp_db(db, db_version="v0.2.0", built_at="2026-05-28T00:00:00Z")
    conn = sqlite3.connect(str(db))
    assert (
        conn.execute("PRAGMA user_version").fetchone()[0]
        == db_publish.DB_SCHEMA_VERSION
    )
    meta = dict(conn.execute("SELECT key, value FROM _pantryatlas_db_meta").fetchall())
    assert meta["db_version"] == "v0.2.0"
    assert meta["embedding_model"] == db_publish.EMBEDDING_MODEL
    assert meta["built_at"] == "2026-05-28T00:00:00Z"
    assert conn.execute("SELECT COUNT(*) FROM recipes_meta").fetchone()[0] == 2
    conn.close()


def test_stamp_db_idempotent_updates_in_place(tmp_path):
    db = tmp_path / "r.db"
    _make_db(db, 1)
    db_publish.stamp_db(db, db_version="v0.2.0")
    db_publish.stamp_db(db, db_version="v0.2.1")
    conn = sqlite3.connect(str(db))
    n_keys = conn.execute("SELECT COUNT(*) FROM _pantryatlas_db_meta").fetchone()[0]
    val = conn.execute(
        "SELECT value FROM _pantryatlas_db_meta WHERE key='db_version'"
    ).fetchone()[0]
    conn.close()
    assert val == "v0.2.1"
    assert n_keys == 6  # six distinct keys, no duplication


def test_build_manifest_keys_and_types():
    m = db_publish.build_manifest(
        db_version="v0.2.0",
        sha256="abc",
        bytes_=123,
        recipe_count=49965,
        built_at="2026-05-28T00:00:00Z",
    )
    assert m["db_version"] == "v0.2.0"
    assert m["schema_version"] == db_publish.DB_SCHEMA_VERSION
    assert m["recipe_count"] == 49965
    assert m["embedding_model"] == db_publish.EMBEDDING_MODEL
    assert m["url"].endswith("/recipes-v0.2.0.db")
    assert m["sha256"] == "abc"
    assert m["license"] == "CC-BY-NC-4.0"
    assert isinstance(m["bytes"], int)
