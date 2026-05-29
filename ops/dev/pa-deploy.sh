#!/usr/bin/env bash
# pa-deploy — push the current robot working tree to the pi-nas dev/staging node.
# "pi-nas runs whatever robot has now." See docs/superpowers/specs/2026-05-28-pinas-dev-node-design.md
#
# Usage:  ops/dev/pa-deploy.sh [--with-db]
#   --with-db   also rsync ~/.pantryatlas/recipes.db (227M) — only needed first time or when the DB changes.
#
# Prereq: ops/dev/pa-bootstrap.sh has been run once (creates pantrydev + unit + sudoers).
set -euo pipefail
REPO="$(cd "$(dirname "${BASH_SOURCE[0]}")/../.." && pwd)"
TARGET="pantrydev@pi-nas.local"
PORT=8090
cd "$REPO"

WITH_DB=0
for a in "$@"; do case "$a" in --with-db) WITH_DB=1;; *) echo "unknown arg: $a"; exit 2;; esac; done

echo "==> [1/5] build web/dist (load-bearing: stale/missing dist => PWA placeholder)"
npm --prefix web run build >/dev/null
test -f web/dist/index.html || { echo "FATAL: web/dist/index.html missing after build"; exit 1; }

echo "==> [2/5] rsync working tree -> $TARGET"
rsync -az --delete \
  --exclude '.git' --exclude '.venv' --exclude 'node_modules' \
  --exclude '__pycache__' --exclude '*.pyc' --exclude '.pytest_cache' \
  --exclude '.hypothesis' --exclude '.ruff_cache' --exclude '/build' \
  --exclude '*.egg-info' --exclude '.wrangler' --exclude 'DEPLOYED_VERSION' \
  -e 'ssh -o BatchMode=yes -o ConnectTimeout=6' \
  "$REPO/" "$TARGET:/home/pantrydev/pantryatlas/"

if [ "$WITH_DB" = 1 ]; then
  echo "==> shipping recipes.db"
  rsync -az -e 'ssh -o BatchMode=yes' "$HOME/.pantryatlas/recipes.db" "$TARGET:/home/pantrydev/.pantryatlas/recipes.db"
fi

echo "==> [3/5] refresh editable install in pantrydev venv (clean-venv: surfaces undeclared deps)"
ssh -o BatchMode=yes "$TARGET" 'cd ~/pantryatlas && .venv/bin/pip install -q -e . && .venv/bin/python -c "from pantryatlas.navigator.server import app"'

echo "==> [4/5] stamp DEPLOYED_VERSION + restart"
SHA=$(git rev-parse HEAD); BR=$(git branch --show-current); DIRTY=$(git status --porcelain | wc -l); TS=$(date -u +%Y-%m-%dT%H:%M:%SZ)
printf 'sha=%s\nbranch=%s\ndirty_files=%s\ndeployed_utc=%s\nfrom=robot\n' "$SHA" "$BR" "$DIRTY" "$TS" \
  | ssh -o BatchMode=yes "$TARGET" 'cat > ~/pantryatlas/DEPLOYED_VERSION'
ssh -o BatchMode=yes "$TARGET" 'sudo systemctl restart pantryatlas-dev-navigator.service'

echo "==> [5/5] smoke-check"
sleep 3
body=$(curl -s -m8 "http://pi-nas.local:$PORT/" || true)
case "$body" in
  *"frontend not built"*) echo "FATAL: navigator served the PWA placeholder (web/dist missing/stale)"; exit 1;;
  *"<!doctype html"*|*"<!DOCTYPE html"*) echo "  OK: PWA served";;
  *) echo "  WARN: unexpected root body (first 80 chars): ${body:0:80}";;
esac
code=$(curl -s -o /dev/null -w '%{http_code}' -m8 "http://pi-nas.local:$PORT/navigator/pantry" || true)
echo "  navigator/pantry=$code   deployed=$SHA ($BR, dirty=$DIRTY)"
echo "==> live: http://pi-nas.local:$PORT/"
