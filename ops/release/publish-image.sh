#!/usr/bin/env bash
# Publish a built SD image + manifests to Cloudflare R2.
#
#   ops/release/publish-image.sh <img.xz> <version> <manifest-dir>
#
# <manifest-dir> contains pantryatlas-<version>.json + pantryatlas-latest.json
# (produced by `python -m pantryatlas.ops.image_build` during the build).
#
# Uploads via rclone (NOT wrangler): `wrangler r2 object put` caps single uploads
# at 300 MiB, but the image is ~2 GB — rclone does S3 multipart automatically.
# Configure the remote once (interactive, secret stays in your terminal):
#   rclone config   # type=s3, provider=Cloudflare, endpoint=https://<acct>.r2.cloudflarestorage.com
# Default remote name is 'r2' (override with PANTRYATLAS_R2_REMOTE).
#
# Env:
#   PUBLISH_DRY_RUN=1        skip uploads; print what would be uploaded
#   PANTRYATLAS_R2_BUCKET    bucket name   (default: pantryatlas-artifacts)
#   PANTRYATLAS_R2_REMOTE    rclone remote (default: r2)
set -euo pipefail

IMG="${1:?usage: publish-image.sh <img.xz> <version> <manifest-dir>}"
VERSION="${2:?usage: publish-image.sh <img.xz> <version> <manifest-dir>}"
MANIFEST_DIR="${3:?usage: publish-image.sh <img.xz> <version> <manifest-dir>}"
BUCKET="${PANTRYATLAS_R2_BUCKET:-pantryatlas-artifacts}"
REMOTE="${PANTRYATLAS_R2_REMOTE:-r2}"

# Preflight (skipped in dry-run): rclone present + the remote is configured.
if [ "${PUBLISH_DRY_RUN:-0}" != "1" ]; then
    command -v rclone >/dev/null 2>&1 || {
        echo "ERROR: rclone not found. Install it and run 'rclone config' to add an R2 remote." >&2
        exit 1
    }
    if ! rclone listremotes 2>/dev/null | grep -qx "${REMOTE}:"; then
        echo "ERROR: rclone remote '${REMOTE}:' not configured. Run 'rclone config' (type=s3, provider=Cloudflare)." >&2
        echo "       Or set PANTRYATLAS_R2_REMOTE to your remote name." >&2
        exit 1
    fi
fi

put() {  # put <key> <file>
    if [ "${PUBLISH_DRY_RUN:-0}" = "1" ]; then
        echo "[dry-run] would upload $2 -> $BUCKET/$1"
    else
        # --s3-chunk-size 64M keeps multipart part-count sane for a ~2 GB image.
        rclone copyto "$2" "${REMOTE}:${BUCKET}/$1" --s3-chunk-size 64M
    fi
}

# Image first, so the manifests never advertise a not-yet-uploaded artifact.
put "img/pantryatlas-$VERSION.img.xz" "$IMG"
put "img/pantryatlas-$VERSION.json"   "$MANIFEST_DIR/pantryatlas-$VERSION.json"
put "img/pantryatlas-latest.json"     "$MANIFEST_DIR/pantryatlas-latest.json"

echo "[publish-image] done."
