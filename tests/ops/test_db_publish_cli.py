import json
import sqlite3
import subprocess
import sys


def _make_db(path, n=4):
    conn = sqlite3.connect(str(path))
    conn.execute("CREATE TABLE recipes_meta (id TEXT PRIMARY KEY, title TEXT)")
    conn.executemany(
        "INSERT INTO recipes_meta VALUES (?, ?)", [(str(i), f"t{i}") for i in range(n)]
    )
    conn.commit()
    conn.close()


def test_cli_writes_manifests_and_prints_pins(tmp_path):
    db = tmp_path / "recipes.db"
    _make_db(db, 4)
    out = tmp_path / "out"
    r = subprocess.run(
        [
            sys.executable, "-m", "pantryatlas.ops.db_publish",
            "--db", str(db), "--version", "v9.9.9", "--out-dir", str(out),
        ],
        capture_output=True, text=True,
    )
    assert r.returncode == 0, r.stderr
    per_version = out / "recipes-v9.9.9.json"
    latest = out / "recipes-latest.json"
    assert per_version.exists() and latest.exists()
    m = json.loads(per_version.read_text())
    assert m["recipe_count"] == 4
    assert m["db_version"] == "v9.9.9"
    from pantryatlas.ops import db_publish
    assert m["sha256"] == db_publish.sha256_file(db)
    assert 'RECIPES_DB_URL="' in r.stdout
    assert 'RECIPES_DB_SHA256="' in r.stdout
