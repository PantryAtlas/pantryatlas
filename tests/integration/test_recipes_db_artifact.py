"""Live check: pull the published DB from R2 and verify it matches the manifest.

Marked pi_integration (network) — deselected in CI; run after publishing:
    pytest tests/integration/test_recipes_db_artifact.py -m pi_integration -v
"""

import json
import sqlite3
import urllib.request

import pytest

from pantryatlas.ops import db_publish

MANIFEST_URL = "https://dl.pantryatlas.org/db/recipes-latest.json"

pytestmark = pytest.mark.pi_integration


def test_published_db_matches_manifest(tmp_path):
    with urllib.request.urlopen(MANIFEST_URL, timeout=30) as resp:
        manifest = json.load(resp)
    db = tmp_path / "recipes.db"
    with urllib.request.urlopen(manifest["url"], timeout=120) as resp:
        db.write_bytes(resp.read())

    assert db_publish.sha256_file(db) == manifest["sha256"]

    conn = sqlite3.connect(db)  # plain sqlite3 — recipes_meta is a normal table
    try:
        count = conn.execute("SELECT COUNT(*) FROM recipes_meta").fetchone()[0]
    finally:
        conn.close()
    assert count == manifest["recipe_count"]
