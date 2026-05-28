"""Chroot smoke-test of a built SD image — no boot, no flashing.

Operator-run after building (needs sudo + loop devices + a built image):
    PANTRYATLAS_PI_INTEGRATION=1 PANTRYATLAS_IMAGE=/path/to/pantryatlas-vX.img \\
        pytest tests/ops/test_image_smoke.py -m pi_integration -v

Point PANTRYATLAS_IMAGE at the UNCOMPRESSED .img (decompress the .img.xz first).
"""

import os
import subprocess

import pytest

pytestmark = pytest.mark.pi_integration

IMAGE = os.environ.get("PANTRYATLAS_IMAGE")


@pytest.mark.skipif(not IMAGE, reason="set PANTRYATLAS_IMAGE to a built .img")
def test_image_provisioning():
    r = subprocess.run(
        ["sudo", "bash", "ops/image/verify-image.sh", IMAGE],
        capture_output=True, text=True,
    )
    assert r.returncode == 0, r.stdout + r.stderr
