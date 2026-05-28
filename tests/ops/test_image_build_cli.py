import json
import subprocess
import sys


def test_cli_writes_image_manifests(tmp_path):
    img = tmp_path / "pantryatlas-v9.9.9.img.xz"
    img.write_bytes(b"fake-image-bytes")
    out = tmp_path / "out"
    r = subprocess.run(
        [
            sys.executable, "-m", "pantryatlas.ops.image_build",
            "--image", str(img),
            "--version", "v9.9.9",
            "--base-image", "raspios-lite-arm64-test",
            "--base-image-sha256", "b" * 64,
            "--recipes-db-sha256", "d" * 64,
            "--bge-m3-sha256", "e" * 64,
            "--pantryatlas-commit", "c" * 40,
            "--built-at", "2026-05-28T00:00:00Z",
            "--out-dir", str(out),
        ],
        capture_output=True, text=True,
    )
    assert r.returncode == 0, r.stderr
    per_version = out / "pantryatlas-v9.9.9.json"
    latest = out / "pantryatlas-latest.json"
    assert per_version.exists() and latest.exists()
    m = json.loads(per_version.read_text())
    assert m["image_version"] == "v9.9.9"
    assert m["base_image"] == "raspios-lite-arm64-test"
    from pantryatlas.ops import image_build
    assert m["sha256"] == image_build.sha256_file(img)
    assert m["bytes"] == img.stat().st_size
    assert 'IMAGE_URL="' in r.stdout
