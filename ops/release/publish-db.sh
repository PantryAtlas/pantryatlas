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
