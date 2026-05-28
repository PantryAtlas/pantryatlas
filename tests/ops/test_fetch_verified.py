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
