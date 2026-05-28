import os
import subprocess
from pathlib import Path

REPO = Path(__file__).resolve().parents[2]
SCRIPT = REPO / "ops" / "release" / "publish-image.sh"


def test_publish_image_dry_run_lists_uploads(tmp_path):
    img = tmp_path / "pantryatlas-v9.9.9.img.xz"
    img.write_bytes(b"fake")
    manifest_dir = tmp_path / "m"
    manifest_dir.mkdir()
    (manifest_dir / "pantryatlas-v9.9.9.json").write_text("{}")
    (manifest_dir / "pantryatlas-latest.json").write_text("{}")
    env = {**os.environ, "PUBLISH_DRY_RUN": "1"}
    r = subprocess.run(
        ["bash", str(SCRIPT), str(img), "v9.9.9", str(manifest_dir)],
        capture_output=True, text=True, env=env, cwd=str(REPO),
    )
    assert r.returncode == 0, r.stderr
    for key in (
        "img/pantryatlas-v9.9.9.img.xz",
        "img/pantryatlas-v9.9.9.json",
        "img/pantryatlas-latest.json",
    ):
        assert key in r.stdout, f"missing upload for {key}\n{r.stdout}"
