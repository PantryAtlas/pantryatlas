#!/usr/bin/env bash
# Publish a built SD image + manifests to Cloudflare R2.
#
#   ops/release/publish-image.sh <img.xz> <version> <manifest-dir>
#
# <manifest-dir> contains pantryatlas-<version>.json + pantryatlas-latest.json
# (produced by `python -m pantryatlas.ops.image_build` during the build).
#
# Env:
#   PUBLISH_DRY_RUN=1        skip wrangler uploads; print what would be uploaded
#   PANTRYATLAS_R2_BUCKET    bucket name (default: pantryatlas-artifacts)
set -euo pipefail

IMG="${1:?usage: publish-image.sh <img.xz> <version> <manifest-dir>}"
VERSION="${2:?usage: publish-image.sh <img.xz> <version> <manifest-dir>}"
MANIFEST_DIR="${3:?usage: publish-image.sh <img.xz> <version> <manifest-dir>}"
BUCKET="${PANTRYATLAS_R2_BUCKET:-pantryatlas-artifacts}"

put() {  # put <key> <file>
    if [ "${PUBLISH_DRY_RUN:-0}" = "1" ]; then
        echo "[dry-run] would upload $2 -> $BUCKET/$1"
    else
        npx -y wrangler r2 object put "$BUCKET/$1" --file "$2" --remote
    fi
}

put "img/pantryatlas-$VERSION.img.xz" "$IMG"
put "img/pantryatlas-$VERSION.json"   "$MANIFEST_DIR/pantryatlas-$VERSION.json"
put "img/pantryatlas-latest.json"     "$MANIFEST_DIR/pantryatlas-latest.json"

echo "[publish-image] done."
