import os
import sqlite3
import subprocess
import sys
from pathlib import Path

REPO = Path(__file__).resolve().parents[2]
SCRIPT = REPO / "ops" / "release" / "publish-db.sh"


def _make_db(path, n=3):
    conn = sqlite3.connect(str(path))
    conn.execute("CREATE TABLE recipes_meta (id TEXT PRIMARY KEY, title TEXT)")
    conn.executemany(
        "INSERT INTO recipes_meta VALUES (?, ?)", [(str(i), f"t{i}") for i in range(n)]
    )
    conn.commit()
    conn.close()


def test_publish_dry_run_lists_uploads_and_prints_pins(tmp_path):
    db = tmp_path / "recipes.db"
    _make_db(db, 3)
    env = {**os.environ, "PUBLISH_DRY_RUN": "1", "PYTHON": sys.executable}
    r = subprocess.run(
        ["bash", str(SCRIPT), str(db), "v9.9.9"],
        capture_output=True, text=True, env=env, cwd=str(REPO),
    )
    assert r.returncode == 0, r.stderr
    for key in (
        "db/recipes-v9.9.9.db",
        "db/recipes-v9.9.9.json",
        "db/recipes-latest.json",
        "db/ATTRIBUTION.txt",
    ):
        assert key in r.stdout, f"missing upload for {key}\n{r.stdout}"
    assert 'RECIPES_DB_SHA256="' in r.stdout
