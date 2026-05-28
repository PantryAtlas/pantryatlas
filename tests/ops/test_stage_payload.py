import os
import subprocess
from pathlib import Path

REPO = Path(__file__).resolve().parents[2]
SCRIPT = REPO / "ops" / "image" / "stage-payload.sh"


def test_aborts_when_db_missing(tmp_path):
    # point env at empty source dirs -> must abort non-zero, naming the path
    env = {
        **os.environ,
        "PANTRYATLAS_DATA_DIR": str(tmp_path / "nope-data"),
        "PANTRYATLAS_CACHE_DIR": str(tmp_path / "nope-cache"),
    }
    stage = tmp_path / "stage"
    r = subprocess.run(
        ["bash", str(SCRIPT), str(stage)],
        capture_output=True, text=True, env=env, cwd=str(REPO),
    )
    assert r.returncode != 0
    assert "recipes.db" in (r.stdout + r.stderr)


def test_stages_payload_when_present(tmp_path):
    data = tmp_path / "data"
    cache = tmp_path / "cache" / "bge-m3"
    data.mkdir(parents=True)
    (data / "recipes.db").write_bytes(b"db")
    cache.mkdir(parents=True)
    (cache / "model").write_bytes(b"m")
    env = {
        **os.environ,
        "PANTRYATLAS_DATA_DIR": str(data),
        "PANTRYATLAS_CACHE_DIR": str(tmp_path / "cache"),
    }
    stage = tmp_path / "stage"
    r = subprocess.run(
        ["bash", str(SCRIPT), str(stage)],
        capture_output=True, text=True, env=env, cwd=str(REPO),
    )
    assert r.returncode == 0, r.stderr
    assert (stage / "recipes.db").exists()
    assert (stage / "bge-m3" / "model").exists()
