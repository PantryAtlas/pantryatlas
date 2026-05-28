"""Pure helpers for building the PantryAtlas SD image artifact.

Testable building blocks used by ops/image/build-image.sh and
ops/release/publish-image.sh:
- UNITS_TO_ENABLE   : the lean service set (no Gemma)
- nftables_ruleset  : the port-80 -> navigator redirect config
- build_image_manifest : assemble the release manifest dict

CLI (python -m pantryatlas.ops.image_build) writes per-version + latest image
manifests given the input shas. Mirrors pantryatlas.ops.db_publish.
"""

from __future__ import annotations

from typing import Any

DEFAULT_IMG_BASE_URL = "https://dl.pantryatlas.org/img"

# Lean image: core services only. The LLM (pantryatlas-gemma) is intentionally
# excluded — vision stays opt-in (503-graceful).
UNITS_TO_ENABLE = [
    "pantryatlas-mem-monitor",
    "pantryatlas-embeddings",
    "pantryatlas-navigator",
]


def nftables_ruleset(*, dport: int = 80, to_port: int = 8090) -> str:
    """nftables config redirecting <dport> to the navigator on <to_port>.

    Covers both external clients (prerouting) and on-device localhost (output).
    """
    return f"""#!/usr/sbin/nft -f
flush ruleset
table ip pantryatlas_nat {{
    chain prerouting {{
        type nat hook prerouting priority dstnat; policy accept;
        tcp dport {dport} redirect to :{to_port}
    }}
    chain output {{
        type nat hook output priority -100; policy accept;
        ip daddr 127.0.0.0/8 tcp dport {dport} redirect to :{to_port}
    }}
}}
"""


def build_image_manifest(
    *,
    image_version: str,
    base_image: str,
    base_image_sha256: str,
    recipes_db_sha256: str,
    bge_m3_sha256: str,
    pantryatlas_commit: str,
    sha256: str,
    bytes_: int,
    built_at: str,
    base_url: str = DEFAULT_IMG_BASE_URL,
) -> dict[str, Any]:
    return {
        "image_version": image_version,
        "base_image": base_image,
        "base_image_sha256": base_image_sha256,
        "recipes_db_sha256": recipes_db_sha256,
        "bge_m3_sha256": bge_m3_sha256,
        "pantryatlas_commit": pantryatlas_commit,
        "url": f"{base_url}/pantryatlas-{image_version}.img.xz",
        "sha256": sha256,
        "bytes": bytes_,
        "built_at": built_at,
    }
