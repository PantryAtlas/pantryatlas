#!/usr/bin/env bash
# build-image.sh — build the lean PantryAtlas Raspberry Pi OS SD image.
#
# OPERATOR-RUN, requires sudo (sdm mounts/loop-attaches the image and runs an
# nspawn container). NOT runnable in CI / on the Pi without sdm + root + ~10 GB free.
#
#   sudo ./ops/image/build-image.sh <version>      # e.g. v0.2.0
#
# ---------------------------------------------------------------------------
# sdm version pinned: V15.5 (commit 5072c97dead784a4f5af4bba6dba2bdab8584d12)
#   https://github.com/gitbls/sdm/releases/tag/V15.5
# Install sdm:  curl -L https://github.com/gitbls/sdm/raw/V15.5/EZsdmInstaller | bash
#
# Invocation rationale (per sdm Docs/Command-Details.md + Docs/Plugins.md):
#   1. `sdm --extend --xmb 4096 IMG`  grows the image so apt + venv + the baked
#      recipe DB / model fit before customization (RPi OS Lite is tight).
#   2. `sdm --customize --batch --restart --hostname pantryatlas \
#         --plugin disables:"piwiz" \
#         --plugin /abs/sdm-plugin-pantryatlas:"stagedir=..|commit=.." IMG`
#      runs our custom plugin's phase 0 (host copy-in) + phase 1 (in-nspawn
#      apt/user/git/pip/systemctl). `--batch` suppresses the post-customize
#      interactive shell. `disables:piwiz` suppresses the Bookworm first-boot
#      user wizard (the plugin also masks userconfig.service as belt-and-braces).
#      NOTE: a custom plugin script is passed WITHOUT a leading '@' — '@' is
#      reserved for plugin-LIST files (Docs/Plugins.md line 27).
#   3. `sdm --shrink IMG`  shrinks the partition back down before xz compression.
#
# Network: the nspawn container in phase 1 needs working OUTBOUND network for
# apt-get, `git clone github.com`, and `pip install`. If the build host blocks
# egress the build will fail late in customization.
# ---------------------------------------------------------------------------
set -euo pipefail

VERSION="${1:?usage: build-image.sh <version>   e.g. v0.2.0}"

REPO_ROOT="$(cd "$(dirname "${BASH_SOURCE[0]}")/../.." && pwd)"
cd "$REPO_ROOT"

# --- Pinned base image: last Raspberry Pi OS Lite arm64 BOOKWORM release -----
# (RPi OS moved to Trixie after 2025-10; this task targets Bookworm. See concerns.)
BASE_NAME="2025-05-13-raspios-bookworm-arm64-lite.img.xz"
BASE_URL="https://downloads.raspberrypi.com/raspios_lite_arm64/images/raspios_lite_arm64-2025-05-13/${BASE_NAME}"
# sha256 confirmed from the official .sha256 alongside the image (2026-05-28).
BASE_SHA256="62d025b9bc7ca0e1facfec74ae56ac13978b6745c58177f081d39fbb8041ed45"

PLUGIN="$REPO_ROOT/ops/image/sdm-plugin-pantryatlas"
COMMIT="$(git rev-parse HEAD)"
BUILT_AT="$(date -u +%Y-%m-%dT%H:%M:%SZ)"
# Public remote the plugin clones from inside the image; must contain $COMMIT.
PA_REMOTE="https://github.com/PantryAtlas/pantryatlas.git"

# --- 2. df guard: need >= 10 GB free on / ------------------------------------
FREE_KB="$(df --output=avail -k / | tail -1 | tr -d ' ')"
if [ "$FREE_KB" -lt $((10 * 1024 * 1024)) ]; then
    echo "ERROR: < 10 GB free on / ($((FREE_KB / 1024 / 1024)) GB) — aborting." >&2
    exit 1
fi

# --- 3. tool checks ----------------------------------------------------------
if ! command -v sdm >/dev/null 2>&1; then
    echo "ERROR: sdm not found. Install V15.5:" >&2
    echo "  curl -L https://github.com/gitbls/sdm/raw/V15.5/EZsdmInstaller | bash" >&2
    exit 1
fi
for t in nft losetup xz python3 git npm curl sha256sum; do
    if ! command -v "$t" >/dev/null 2>&1; then
        echo "ERROR: required tool '$t' not found on PATH" >&2
        exit 1
    fi
done

# The plugin clones github.com/PantryAtlas/pantryatlas and checks out $COMMIT
# inside the nspawn container. Fail fast on the HOST if the pinned commit is not
# yet reachable on the remote — otherwise the build dies deep in phase 1 (after
# apt + venv + pip have already run, ~20 min wasted).
if ! git ls-remote --exit-code "$PA_REMOTE" "$COMMIT" >/dev/null 2>&1 \
   && ! git fetch -q "$PA_REMOTE" "$COMMIT" 2>/dev/null; then
    echo "ERROR: commit $COMMIT is not reachable on $PA_REMOTE." >&2
    echo "       Push branch feat/sd-image (or merge to main) before building." >&2
    exit 1
fi

# Working dir for the image + intermediate artifacts.
WORK="$(mktemp -d /tmp/pa-image.XXXXXX)"
STAGE="$(mktemp -d "${WORK}/stage.XXXXXX")"
MANIFEST_DIR="${WORK}/manifest"
mkdir -p "$MANIFEST_DIR"
echo "[build-image] work dir: $WORK"

# --- 4. build the web UI so web/dist exists for staging ----------------------
echo "[build-image] building web UI"
npm --prefix web ci
npm --prefix web run build

# --- 5. stage the baked payload ---------------------------------------------
echo "[build-image] staging payload"
bash "$REPO_ROOT/ops/image/stage-payload.sh" "$STAGE"

# --- 6. generate nftables.conf into the stage dir (single source of truth) ---
echo "[build-image] generating nftables.conf"
PYTHONPATH="$REPO_ROOT" python3 -c \
    "from pantryatlas.ops.image_build import nftables_ruleset; print(nftables_ruleset())" \
    > "$STAGE/nftables.conf"

# --- 7. download + verify + decompress the base image ------------------------
echo "[build-image] fetching base image"
# shellcheck source=../lib/fetch.sh
source "$REPO_ROOT/ops/lib/fetch.sh"
BASE_XZ="$WORK/$BASE_NAME"
fetch_verified "$BASE_URL" "$BASE_SHA256" "$BASE_XZ"

IMG="$WORK/pantryatlas-${VERSION}.img"
echo "[build-image] decompressing to $IMG"
xz -dc "$BASE_XZ" > "$IMG"

# --- 8. sdm: extend, then customize via the plugin ---------------------------
echo "[build-image] sdm --extend"
sdm --extend --xmb 4096 "$IMG"

echo "[build-image] sdm --customize (runs the pantryatlas plugin)"
sdm --customize --batch --restart --hostname pantryatlas \
    --plugin disables:"piwiz" \
    --plugin "${PLUGIN}":"stagedir=${STAGE}|commit=${COMMIT}" \
    "$IMG"

# --- 9. shrink + compress ----------------------------------------------------
echo "[build-image] sdm --shrink"
sdm --shrink "$IMG"

echo "[build-image] compressing (xz -T0)"
xz -T0 -v "$IMG"
IMG_XZ="${IMG}.xz"

# --- 10. compute input shas + write release manifest -------------------------
echo "[build-image] computing input shas + manifest"
RECIPES_DB_SHA="$(PYTHONPATH="$REPO_ROOT" python3 -c \
    "from pantryatlas.ops.db_publish import sha256_file; print(sha256_file('$STAGE/recipes.db'))")"
# bge-m3 int8 ONNX lands at bge-m3/onnx/model_int8.onnx (pantryatlas/embeddings/__init__.py).
BGE_M3_SHA="$(PYTHONPATH="$REPO_ROOT" python3 -c \
    "from pantryatlas.ops.db_publish import sha256_file; print(sha256_file('$STAGE/bge-m3/onnx/model_int8.onnx'))")"

PYTHONPATH="$REPO_ROOT" python3 -m pantryatlas.ops.image_build \
    --image "$IMG_XZ" \
    --version "$VERSION" \
    --base-image "$BASE_NAME" \
    --base-image-sha256 "$BASE_SHA256" \
    --recipes-db-sha256 "$RECIPES_DB_SHA" \
    --bge-m3-sha256 "$BGE_M3_SHA" \
    --pantryatlas-commit "$COMMIT" \
    --built-at "$BUILT_AT" \
    --out-dir "$MANIFEST_DIR"

# --- 11. report next step ----------------------------------------------------
echo
echo "[build-image] DONE"
echo "  image:        $IMG_XZ"
echo "  manifest dir: $MANIFEST_DIR"
echo
echo "Next — publish to R2:"
echo "  ops/release/publish-image.sh \"$IMG_XZ\" \"$VERSION\" \"$MANIFEST_DIR\""
