#!/usr/bin/env bash
# Stage the baked payload (recipe DB, embedding model, built web UI) into a dir
# the sdm plugin copies into the image.
#
#   ops/image/stage-payload.sh <stage-dir>
#
# Env:
#   PANTRYATLAS_DATA_DIR   (default ~/.pantryatlas)        — holds recipes.db
#   PANTRYATLAS_CACHE_DIR  (default ~/.cache/pantryatlas)  — holds bge-m3/
set -euo pipefail

STAGE="${1:?usage: stage-payload.sh <stage-dir>}"
DATA_DIR="${PANTRYATLAS_DATA_DIR:-$HOME/.pantryatlas}"
CACHE_DIR="${PANTRYATLAS_CACHE_DIR:-$HOME/.cache/pantryatlas}"
REPO_ROOT="$(cd "$(dirname "$0")/../.." && pwd)"

DB="$DATA_DIR/recipes.db"
MODEL="$CACHE_DIR/bge-m3"
WEB_DIST="$REPO_ROOT/web/dist"

[ -f "$DB" ] || { echo "ERROR: missing recipes.db at $DB (run the ingest first)" >&2; exit 1; }
[ -d "$MODEL" ] || { echo "ERROR: missing bge-m3 model at $MODEL (run embeddings once)" >&2; exit 1; }

mkdir -p "$STAGE"
cp -a "$DB" "$STAGE/recipes.db"
cp -a "$MODEL" "$STAGE/bge-m3"
if [ -d "$WEB_DIST" ] && [ -n "$(ls -A "$WEB_DIST" 2>/dev/null)" ]; then
    cp -a "$WEB_DIST" "$STAGE/web-dist"
else
    echo "WARN: $WEB_DIST empty — run 'npm --prefix web run build' before the real image build" >&2
fi
echo "[stage-payload] staged into $STAGE"
