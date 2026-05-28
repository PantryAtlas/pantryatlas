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


def test_stage_db_download_errors_on_unset_sha(tmp_path):
    stamps = tmp_path / "stamps"
    stamps.mkdir()
    cmd = (
        f'export STAMPS_DIR="{stamps}"; '
        f'source "{SCRIPT}"; '
        f"stage_db_download"
    )
    r = subprocess.run(["bash", "-c", cmd], capture_output=True, text=True)
    assert r.returncode == 3
    assert "REPLACE_AFTER_FIRST_PUBLISH" in r.stderr
