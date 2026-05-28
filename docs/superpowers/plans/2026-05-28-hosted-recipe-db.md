# Hosted Recipe DB Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Distribute the prebuilt 49,965-recipe sqlite-vec DB as a versioned, sha256-pinned Cloudflare R2 artifact so every install fetches it in seconds instead of the ~5.2h Pi-CPU ingest.

**Architecture:** Testable Python core in `pantryatlas/ops/db_publish.py` (stamp DB, build manifest, checksum) following the existing `pantryatlas/ops/` pattern; thin bash wrappers around it — an operator-run `ops/release/publish-db.sh` (Python + `wrangler r2 object put`) and a new idempotent `stage_db_download` in `ops/pi-bootstrap.sh` that shares a sourceable `ops/lib/fetch.sh` `fetch_verified` helper with the existing Gemma stage.

**Tech Stack:** Python 3.11 (stdlib `sqlite3`, `hashlib`, `json`, `argparse`), bash, `curl`, `sha256sum`, Cloudflare R2 via `wrangler` 4.x, pytest.

**Spec:** `docs/superpowers/specs/2026-05-28-hosted-recipe-db-design.md`

---

## Operator prerequisites (manual, one-time — not code tasks)

These require Cloudflare dashboard / account actions and are done by the operator, not an implementing agent. Listed here so the plan is self-contained.

1. **Create the bucket:**
   `npx -y wrangler r2 bucket create pantryatlas-artifacts`
2. **Confirm wrangler can write R2** (OAuth scope or an R2-scoped API token):
   `echo hi > /tmp/hc.txt && npx -y wrangler r2 object put pantryatlas-artifacts/healthcheck.txt --file /tmp/hc.txt --remote` then
   `npx -y wrangler r2 object delete pantryatlas-artifacts/healthcheck.txt --remote`.
   If this fails on auth, create an API token with **R2 edit** and `export CLOUDFLARE_API_TOKEN=...`.
3. **Public read access — dashboard step (wrangler cannot do this):** R2 → `pantryatlas-artifacts` → Settings → attach custom domain `dl.pantryatlas.org`. Until that DNS is live, enable the managed `r2.dev` URL and use it in the bootstrap pins instead of `dl.pantryatlas.org`.

---

## File structure

| File | New/Mod | Responsibility |
|---|---|---|
| `pantryatlas/ops/db_publish.py` | new | Pure helpers: `sha256_file`, `stamp_db`, `recipe_count`, `build_manifest`, + `main()` CLI |
| `tests/ops/test_db_publish.py` | new | Unit tests for the helpers |
| `tests/ops/test_db_publish_cli.py` | new | Subprocess test of `python -m pantryatlas.ops.db_publish` |
| `ops/lib/fetch.sh` | new | Sourceable `fetch_verified <url> <sha256> <dest>` |
| `tests/ops/test_fetch_verified.py` | new | Subprocess test of `fetch_verified` (good + sha-mismatch) |
| `ops/pi-bootstrap.sh` | mod | Source `fetch.sh`; refactor Gemma stage; add `PANTRYATLAS_DATA_DIR`, DB pins, `stage_db_download`; make sourceable |
| `tests/ops/test_bootstrap_db_stage.py` | new | Syntax check + stamp-skip behavior of `stage_db_download` |
| `ops/release/publish-db.sh` | new | Operator-run: stamp + manifests (Python) + `wrangler` uploads; `PUBLISH_DRY_RUN` mode |
| `ops/release/ATTRIBUTION.txt` | new | RecipeNLG CC-BY-NC-4.0 notice uploaded with the artifact |
| `tests/ops/test_publish_db.py` | new | Dry-run subprocess test of `publish-db.sh` |
| `tests/integration/test_recipes_db_artifact.py` | new | `pi_integration` live check: manifest → download → sha → count |
| `README.md`, `docs/install-pi5.md`, `ops/release/README.md` | mod/new | Document auto-fetch + the publish runbook |

---

### Task 1: Python publish helpers

**Files:**
- Create: `pantryatlas/ops/db_publish.py`
- Test: `tests/ops/test_db_publish.py`

- [ ] **Step 1: Write the failing tests**

Create `tests/ops/test_db_publish.py`:

```python
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
```

- [ ] **Step 2: Run tests to verify they fail**

Run: `pytest tests/ops/test_db_publish.py -q`
Expected: FAIL — `ModuleNotFoundError: No module named 'pantryatlas.ops.db_publish'`.

- [ ] **Step 3: Write the implementation**

Create `pantryatlas/ops/db_publish.py`:

```python
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
    return _dt.datetime.now(_dt.timezone.utc).strftime("%Y-%m-%dT%H:%M:%SZ")


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
```

- [ ] **Step 4: Run tests to verify they pass**

Run: `pytest tests/ops/test_db_publish.py -q`
Expected: PASS (5 passed).

- [ ] **Step 5: Commit**

```bash
git add pantryatlas/ops/db_publish.py tests/ops/test_db_publish.py
git commit -m "feat(ops): db_publish helpers — stamp, checksum, manifest"
```

---

### Task 2: Publish CLI (`python -m pantryatlas.ops.db_publish`)

**Files:**
- Modify: `pantryatlas/ops/db_publish.py` (append `main()` + `__main__` guard)
- Test: `tests/ops/test_db_publish_cli.py`

- [ ] **Step 1: Write the failing test**

Create `tests/ops/test_db_publish_cli.py`:

```python
import json
import sqlite3
import subprocess
import sys
from pathlib import Path


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
    # sha in manifest matches the (now-stamped) db on disk
    from pantryatlas.ops import db_publish
    assert m["sha256"] == db_publish.sha256_file(db)
    assert 'RECIPES_DB_URL="' in r.stdout
    assert 'RECIPES_DB_SHA256="' in r.stdout
```

- [ ] **Step 2: Run test to verify it fails**

Run: `pytest tests/ops/test_db_publish_cli.py -q`
Expected: FAIL — non-zero exit (`db_publish` has no `__main__` / argparse yet).

- [ ] **Step 3: Append the CLI to `pantryatlas/ops/db_publish.py`**

Add at the end of the file:

```python
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
        args.db.stat().st_mtime, _dt.timezone.utc
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
```

- [ ] **Step 4: Run test to verify it passes**

Run: `pytest tests/ops/test_db_publish_cli.py -q`
Expected: PASS (1 passed).

- [ ] **Step 5: Commit**

```bash
git add pantryatlas/ops/db_publish.py tests/ops/test_db_publish_cli.py
git commit -m "feat(ops): db_publish CLI — stamp, write manifests, print pins"
```

---

### Task 3: `fetch_verified` shell helper

**Files:**
- Create: `ops/lib/fetch.sh`
- Test: `tests/ops/test_fetch_verified.py`

- [ ] **Step 1: Write the failing test**

Create `tests/ops/test_fetch_verified.py`:

```python
import hashlib
import subprocess
from pathlib import Path

REPO = Path(__file__).resolve().parents[2]
FETCH = REPO / "ops" / "lib" / "fetch.sh"


def _run(url, sha, dest):
    cmd = f'source "{FETCH}"; fetch_verified "{url}" "{sha}" "{dest}"'
    return subprocess.run(["bash", "-c", cmd], capture_output=True, text=True)


def test_fetch_verified_good(tmp_path):
    src = tmp_path / "src.bin"
    src.write_bytes(b"payload-data")
    sha = hashlib.sha256(b"payload-data").hexdigest()
    dest = tmp_path / "dest.bin"
    r = _run(f"file://{src}", sha, dest)
    assert r.returncode == 0, r.stderr
    assert dest.read_bytes() == b"payload-data"


def test_fetch_verified_sha_mismatch_aborts_no_file(tmp_path):
    src = tmp_path / "src.bin"
    src.write_bytes(b"payload-data")
    dest = tmp_path / "dest.bin"
    r = _run(f"file://{src}", "0" * 64, dest)
    assert r.returncode != 0
    assert not dest.exists()
    assert not (tmp_path / "dest.bin.tmp").exists()
```

- [ ] **Step 2: Run test to verify it fails**

Run: `pytest tests/ops/test_fetch_verified.py -q`
Expected: FAIL — `fetch.sh` does not exist (`source` errors, non-zero).

- [ ] **Step 3: Write `ops/lib/fetch.sh`**

```bash
#!/usr/bin/env bash
# Shared download helper, sourced by ops/pi-bootstrap.sh.
#
#   fetch_verified <url> <expected_sha256> <dest>
#
# Downloads to <dest>.tmp, verifies sha256, atomically moves into place.
# On mismatch or download failure: removes the partial and returns non-zero.

fetch_verified() {
    local url="$1" expected="$2" dest="$3"
    local tmp="$dest.tmp"
    if ! curl -fL --retry 3 -o "$tmp" "$url"; then
        echo "ERROR: download failed: $url" >&2
        rm -f "$tmp"
        return 1
    fi
    local actual
    actual="$(sha256sum "$tmp" | awk '{print $1}')"
    if [ "$actual" != "$expected" ]; then
        echo "ERROR: SHA256 mismatch for $url: expected $expected, got $actual" >&2
        rm -f "$tmp"
        return 1
    fi
    mv "$tmp" "$dest"
}
```

- [ ] **Step 4: Run test to verify it passes**

Run: `pytest tests/ops/test_fetch_verified.py -q`
Expected: PASS (2 passed).

- [ ] **Step 5: Commit**

```bash
git add ops/lib/fetch.sh tests/ops/test_fetch_verified.py
git commit -m "feat(ops): sourceable fetch_verified helper (curl + sha256 + atomic mv)"
```

---

### Task 4: Wire the DB stage into `pi-bootstrap.sh`

**Files:**
- Modify: `ops/pi-bootstrap.sh`
- Test: `tests/ops/test_bootstrap_db_stage.py`

- [ ] **Step 1: Write the failing test**

Create `tests/ops/test_bootstrap_db_stage.py`:

```python
import subprocess
from pathlib import Path

REPO = Path(__file__).resolve().parents[2]
SCRIPT = REPO / "ops" / "pi-bootstrap.sh"


def test_bootstrap_syntax_ok():
    r = subprocess.run(["bash", "-n", str(SCRIPT)], capture_output=True, text=True)
    assert r.returncode == 0, r.stderr


def test_stage_db_download_skips_when_stamp_present(tmp_path):
    stamps = tmp_path / "stamps"
    stamps.mkdir()
    (stamps / "07-db-download.done").touch()
    data = tmp_path / "data"
    cmd = (
        f'export STAMPS_DIR="{stamps}"; '
        f'export PANTRYATLAS_DATA_DIR="{data}"; '
        f'source "{SCRIPT}"; '
        f"stage_db_download"
    )
    r = subprocess.run(["bash", "-c", cmd], capture_output=True, text=True)
    assert r.returncode == 0, r.stderr
    assert not data.exists()  # skipped — no fetch attempted
```

- [ ] **Step 2: Run test to verify it fails**

Run: `pytest tests/ops/test_bootstrap_db_stage.py -q`
Expected: FAIL — `stage_db_download: command not found` (and the sourced script currently runs `main` on source).

- [ ] **Step 3a: Make config vars overridable + add data dir + DB pins**

In `ops/pi-bootstrap.sh`, find the config block (around lines 28-33):

```bash
PANTRYATLAS_HOME="${PANTRYATLAS_HOME:-$HOME/pantryatlas}"
PANTRYATLAS_VENV="$PANTRYATLAS_HOME/venv"
LLAMA_CPP_DIR="$PANTRYATLAS_HOME/llama.cpp"
MODELS_DIR="$PANTRYATLAS_HOME/models"
STAMPS_DIR="$PANTRYATLAS_HOME/.bootstrap-stamps"
REPO_DIR="${REPO_DIR:-$HOME/pantryatlas}"
```

Replace with (makes `STAMPS_DIR` overridable, adds data dir + DB pins):

```bash
PANTRYATLAS_HOME="${PANTRYATLAS_HOME:-$HOME/pantryatlas}"
PANTRYATLAS_VENV="$PANTRYATLAS_HOME/venv"
LLAMA_CPP_DIR="$PANTRYATLAS_HOME/llama.cpp"
MODELS_DIR="$PANTRYATLAS_HOME/models"
STAMPS_DIR="${STAMPS_DIR:-$PANTRYATLAS_HOME/.bootstrap-stamps}"
REPO_DIR="${REPO_DIR:-$HOME/pantryatlas}"

# Runtime data dir (where the app + systemd unit read recipes.db). Distinct from
# PANTRYATLAS_HOME above, which is the install root.
PANTRYATLAS_DATA_DIR="${PANTRYATLAS_DATA_DIR:-$HOME/.pantryatlas}"

# Prebuilt recipe DB artifact — update these pins after each
# `ops/release/publish-db.sh` run (use the r2.dev URL until dl.pantryatlas.org
# is attached in the Cloudflare dashboard).
RECIPES_DB_URL="https://dl.pantryatlas.org/db/recipes-v0.2.0.db"
RECIPES_DB_SHA256="REPLACE_AFTER_FIRST_PUBLISH"
```

- [ ] **Step 3b: Source `fetch.sh` after the config block**

Immediately after the config block, add:

```bash
SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
# shellcheck source=ops/lib/fetch.sh
source "$SCRIPT_DIR/lib/fetch.sh"
```

- [ ] **Step 3c: Refactor the Gemma stage to use `fetch_verified`**

Replace the body of `stage_gemma_download` (the `curl ... .tmp`, `sha256sum`, mismatch `if`, and `mv` lines) so the function reads:

```bash
stage_gemma_download() {
    local stamp="$STAMPS_DIR/04-gemma-download.done"
    local gguf="$MODELS_DIR/gemma-4-E4B-it-Q4_K_M.gguf"
    if [ -f "$stamp" ]; then
        log "gemma download: already done"
        return 0
    fi
    mkdir -p "$MODELS_DIR"
    log "gemma download: fetching ~5 GB GGUF..."
    fetch_verified "$GEMMA4_GGUF_URL" "$GEMMA4_GGUF_SHA256" "$gguf"
    touch "$stamp"
    log "gemma download: done (verified)"
}
```

- [ ] **Step 3d: Add `stage_db_download`**

Add a new function (e.g. directly after `stage_gemma_download`):

```bash
stage_db_download() {
    local stamp="$STAMPS_DIR/07-db-download.done"
    if [ -f "$stamp" ]; then
        log "db download: already done"
        return 0
    fi
    if [ "$RECIPES_DB_SHA256" = "REPLACE_AFTER_FIRST_PUBLISH" ]; then
        echo "ERROR: RECIPES_DB_SHA256 not set — run ops/release/publish-db.sh and update the pins" >&2
        exit 3
    fi
    mkdir -p "$PANTRYATLAS_DATA_DIR"
    log "db download: fetching prebuilt recipes.db..."
    fetch_verified "$RECIPES_DB_URL" "$RECIPES_DB_SHA256" \
        "$PANTRYATLAS_DATA_DIR/recipes.db"
    touch "$stamp"
    log "db download: done (verified)"
}
```

- [ ] **Step 3e: Call it from `main()` + make the script sourceable**

In `main()`, add `stage_db_download` after `stage_gemma_download`:

```bash
    stage_apt_install
    stage_venv
    stage_llama_cpp
    stage_gemma_download
    stage_db_download
    stage_pip_install
    stage_web_build
    stage_smoke_test
```

And replace the final line `main "$@"` with:

```bash
if [[ "${BASH_SOURCE[0]}" == "${0}" ]]; then
    main "$@"
fi
```

- [ ] **Step 4: Run test to verify it passes**

Run: `pytest tests/ops/test_bootstrap_db_stage.py -q`
Expected: PASS (2 passed).

- [ ] **Step 5: Commit**

```bash
git add ops/pi-bootstrap.sh tests/ops/test_bootstrap_db_stage.py
git commit -m "feat(ops): pi-bootstrap fetches prebuilt recipes.db via shared helper"
```

---

### Task 5: Operator publish script + attribution

**Files:**
- Create: `ops/release/publish-db.sh`
- Create: `ops/release/ATTRIBUTION.txt`
- Test: `tests/ops/test_publish_db.py`

- [ ] **Step 1: Write the failing test**

Create `tests/ops/test_publish_db.py`:

```python
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
    env = {
        "PUBLISH_DRY_RUN": "1",
        "PYTHON": sys.executable,
        "PATH": __import__("os").environ["PATH"],
    }
    r = subprocess.run(
        ["bash", str(SCRIPT), str(db), "v9.9.9"],
        capture_output=True, text=True, env=env,
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
```

- [ ] **Step 2: Run test to verify it fails**

Run: `pytest tests/ops/test_publish_db.py -q`
Expected: FAIL — `publish-db.sh` does not exist.

- [ ] **Step 3a: Write `ops/release/ATTRIBUTION.txt`**

```text
PantryAtlas recipe database — data attribution
===============================================

This database is derived from the RecipeNLG dataset.

  RecipeNLG: A Cooking Recipes Dataset for Semi-Structured Text Generation.
  Michal Bien, Michal Gilski, Martyna Maciejewska, Wojciech Taisner,
  Dawid Wisniewski, Agnieszka Lawrynowicz. INLG 2020.
  https://recipenlg.cs.put.poznan.pl/

License: Creative Commons Attribution-NonCommercial 4.0 International
         (CC-BY-NC-4.0) — https://creativecommons.org/licenses/by-nc/4.0/

The recipe text and derived embeddings in this artifact are provided for
non-commercial use. Attribution to RecipeNLG must accompany redistribution.
```

- [ ] **Step 3b: Write `ops/release/publish-db.sh`**

```bash
#!/usr/bin/env bash
# Publish a prebuilt recipes.db to Cloudflare R2 + manifests.
#
#   ops/release/publish-db.sh <db-path> <version>
#
# Env:
#   PUBLISH_DRY_RUN=1        skip wrangler uploads; print what would be uploaded
#   PYTHON=<interp>          python interpreter (default: python3)
#   PANTRYATLAS_R2_BUCKET    bucket name (default: pantryatlas-artifacts)
set -euo pipefail

DB="${1:?usage: publish-db.sh <db-path> <version>}"
VERSION="${2:?usage: publish-db.sh <db-path> <version>}"
PYTHON="${PYTHON:-python3}"
BUCKET="${PANTRYATLAS_R2_BUCKET:-pantryatlas-artifacts}"
SCRIPT_DIR="$(cd "$(dirname "$0")" && pwd)"
OUT="$(mktemp -d)"
trap 'rm -rf "$OUT"' EXIT

echo "[publish-db] stamping DB + building manifests..."
"$PYTHON" -m pantryatlas.ops.db_publish \
    --db "$DB" --version "$VERSION" --out-dir "$OUT"

put() {  # put <key> <file>
    if [ "${PUBLISH_DRY_RUN:-0}" = "1" ]; then
        echo "[dry-run] would upload $2 -> $BUCKET/$1"
    else
        npx -y wrangler r2 object put "$BUCKET/$1" --file "$2" --remote
    fi
}

put "db/recipes-$VERSION.db"   "$DB"
put "db/recipes-$VERSION.json" "$OUT/recipes-$VERSION.json"
put "db/recipes-latest.json"   "$OUT/recipes-latest.json"
put "db/ATTRIBUTION.txt"       "$SCRIPT_DIR/ATTRIBUTION.txt"

echo "[publish-db] done. Paste the RECIPES_DB_* pins above into ops/pi-bootstrap.sh and commit."
```

- [ ] **Step 4: Run test to verify it passes**

Run: `pytest tests/ops/test_publish_db.py -q`
Expected: PASS (1 passed).

- [ ] **Step 5: Commit**

```bash
git add ops/release/publish-db.sh ops/release/ATTRIBUTION.txt tests/ops/test_publish_db.py
git commit -m "feat(ops): operator publish-db.sh (stamp + manifests + R2 upload, dry-run)"
```

---

### Task 6: Live artifact integration test

**Files:**
- Create: `tests/integration/test_recipes_db_artifact.py`

- [ ] **Step 1: Write the test (network / pi_integration — skipped in CI)**

Create `tests/integration/test_recipes_db_artifact.py`:

```python
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
    urllib.request.urlretrieve(manifest["url"], db)

    assert db_publish.sha256_file(db) == manifest["sha256"]

    conn = sqlite3.connect(str(db))  # plain sqlite3 — recipes_meta is a normal table
    try:
        count = conn.execute("SELECT COUNT(*) FROM recipes_meta").fetchone()[0]
    finally:
        conn.close()
    assert count == manifest["recipe_count"]
```

- [ ] **Step 2: Verify it is collected but deselected in the default run**

Run: `pytest tests/integration/test_recipes_db_artifact.py -q -m "not pi_integration"`
Expected: `1 deselected` (no network hit in the normal suite).

- [ ] **Step 3: Commit**

```bash
git add tests/integration/test_recipes_db_artifact.py
git commit -m "test(integration): live recipes.db artifact check (pi_integration)"
```

---

### Task 7: Documentation

**Files:**
- Modify: `README.md`
- Modify: `docs/install-pi5.md`
- Create: `ops/release/README.md`

- [ ] **Step 1: README — note the DB is fetched automatically**

In `README.md`, under the "Quick Start" bootstrap block, add a line after the `bash ~/pantryatlas/ops/pi-bootstrap.sh` step:

```markdown
> Bootstrap now also downloads the prebuilt recipe database (~227 MB, sha256-verified)
> into `~/.pantryatlas/recipes.db` — no multi-hour local ingest required.
```

- [ ] **Step 2: install-pi5 — add the DB stage to the "script will" list**

In `docs/install-pi5.md`, in the numbered "The script will:" list under Step 3, add an item after the Gemma download:

```markdown
5. Download + sha256-verify the prebuilt recipe DB (~227 MB) to `~/.pantryatlas/recipes.db`
```

And in Step 4 verification, add:

```markdown
5. **Check the recipe DB**:
   ```bash
   python3 -c "import sqlite3; print(sqlite3.connect('$HOME/.pantryatlas/recipes.db').execute('SELECT COUNT(*) FROM recipes_meta').fetchone()[0], 'recipes')"
   ```
   Should print `49965 recipes` (matching the published manifest).
```

- [ ] **Step 3: Write the publish runbook `ops/release/README.md`**

```markdown
# Releasing the recipe DB artifact

The prebuilt recipe DB is published to Cloudflare R2 and fetched by
`ops/pi-bootstrap.sh`. CI does **not** rebuild the DB — it is built once on a Pi
(the ~5.2h ingest) and uploaded with this runbook.

## One-time setup

1. `npx -y wrangler r2 bucket create pantryatlas-artifacts`
2. Confirm write access (OAuth or an R2-scoped `CLOUDFLARE_API_TOKEN`):
   `echo hi > /tmp/hc.txt && npx -y wrangler r2 object put pantryatlas-artifacts/healthcheck.txt --file /tmp/hc.txt --remote`
   then `npx -y wrangler r2 object delete pantryatlas-artifacts/healthcheck.txt --remote`.
3. **Dashboard step (wrangler can't do this):** attach `dl.pantryatlas.org` to the
   bucket (R2 → bucket → Settings → Custom Domains). Until DNS is live, enable the
   managed `r2.dev` URL and use that in the bootstrap pins.

## Each release

From a machine with the venv active and the built DB present:

```bash
source ~/pantryatlas/venv/bin/activate   # so `python3 -m pantryatlas...` resolves
ops/release/publish-db.sh ~/.pantryatlas/recipes.db v0.2.0
```

This stamps the DB (`PRAGMA user_version` + `_pantryatlas_db_meta`), uploads the
`.db`, the per-version + `latest` manifests, and `ATTRIBUTION.txt`, then prints:

```
RECIPES_DB_URL="https://dl.pantryatlas.org/db/recipes-v0.2.0.db"
RECIPES_DB_SHA256="<sha>"
```

Paste those two lines into the pins in `ops/pi-bootstrap.sh` and commit. Dry-run
first with `PUBLISH_DRY_RUN=1 ops/release/publish-db.sh ...` to preview uploads.

Then verify live: `pytest tests/integration/test_recipes_db_artifact.py -m pi_integration -v`.
```

- [ ] **Step 4: Commit**

```bash
git add README.md docs/install-pi5.md ops/release/README.md
git commit -m "docs: document auto-fetched recipe DB + publish runbook"
```

---

## Final verification

- [ ] Run the full offline suite: `pytest -q -m "not pi_integration"` — expect all green (existing + new ops tests).
- [ ] Run `ruff check .` — expect clean (CI runs the repo-wide check, including `tests/`).
- [ ] Confirm `bash -n ops/pi-bootstrap.sh` and `bash -n ops/release/publish-db.sh` pass.

## Release & pin loop (operator, after merge)

1. On robot (venv active): `ops/release/publish-db.sh ~/.pantryatlas/recipes.db v0.2.0`.
2. Paste the printed `RECIPES_DB_URL` + `RECIPES_DB_SHA256` into `ops/pi-bootstrap.sh`; commit.
3. Attach `dl.pantryatlas.org` in the CF dashboard (or pin the `r2.dev` URL meanwhile).
4. `pytest tests/integration/test_recipes_db_artifact.py -m pi_integration -v` to confirm the live artifact.

---

## Self-review

**Spec coverage:**
- R2 layout (db/.db, per-version + latest manifest, ATTRIBUTION) → Task 5 (`put` calls) + Operator prereqs (bucket/domain).
- Manifest schema (schema_version + embedding_model pins) → Task 1 `build_manifest` + tests.
- DB stamping (user_version + `_pantryatlas_db_meta`) → Task 1 `stamp_db` + tests.
- Bootstrap fetch stage + `PANTRYATLAS_DATA_DIR` (no `PANTRYATLAS_HOME` collision) → Task 4.
- Shared `fetch_verified`, Gemma stage refactored to use it → Task 3 + Task 4 (Step 3c).
- Operator-run publish, no CI rebuild → Task 5 + `ops/release/README.md` (Task 7).
- Licensing/attribution travels with artifact → Task 5 (`ATTRIBUTION.txt`).
- Tests: stamper / manifest / fetch-mismatch / integration → Tasks 1, 2, 3, 6.
- Non-goals (no CLI fetch-db, no app-side schema enforcement) → respected; not implemented.

**Placeholder scan:** `REPLACE_AFTER_FIRST_PUBLISH` is intentional (filled by the operator post-publish; `stage_db_download` fails loud if left unset). No TODO/TBD steps; every code step has full code.

**Type/name consistency:** `recipes_meta`, `_pantryatlas_db_meta`, `DB_SCHEMA_VERSION`, `EMBEDDING_MODEL`, `sha256_file`, `stamp_db`, `recipe_count`, `build_manifest`, `fetch_verified`, `stage_db_download`, `07-db-download.done`, `RECIPES_DB_URL`/`RECIPES_DB_SHA256`, `PANTRYATLAS_DATA_DIR` used identically across spec, tasks, and tests.
