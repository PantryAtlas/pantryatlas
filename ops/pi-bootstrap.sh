#!/usr/bin/env bash
# Bootstrap a fresh Pi 5 (Bookworm) into "pantryatlas smoke-test ready" state.
#
# Idempotent: safe to re-run; skips completed stages.
# Architecture-locked: refuses to run on anything but aarch64.
#
# Usage:
#   bash ops/pi-bootstrap.sh
#
# Env overrides:
#   PANTRYATLAS_HOME   — installation root (default: ~/pantryatlas)
#   REPO_DIR           — path to the pantryatlas checkout (default: ~/pantryatlas)

set -euo pipefail

# ============================================================
# Configuration (pinned versions — update in sync with PRD T-001)
# ============================================================
LLAMA_CPP_REPO="https://github.com/ggerganov/llama.cpp.git"
# Commit: "model : Gemma4 model type detection (#22027)" — Apr 17 2026
# Includes full Gemma 4 inference support after the initial bug-fix wave.
LLAMA_CPP_COMMIT="fcc7508759c7a3fe5a0f4500592657900be8aca5"

# Values from T-001 (docs/gemma4-verified-specs.md) — do NOT change without re-verifying SHA.
GEMMA4_GGUF_URL="https://huggingface.co/unsloth/gemma-4-E4B-it-GGUF/resolve/main/gemma-4-E4B-it-Q4_K_M.gguf"
GEMMA4_GGUF_SHA256="519b9793ed6ce0ff530f1b7c96e848e08e49e7af4d57bb97f76215963a54146d"

PANTRYATLAS_HOME="${PANTRYATLAS_HOME:-$HOME/pantryatlas}"
PANTRYATLAS_VENV="$PANTRYATLAS_HOME/venv"
LLAMA_CPP_DIR="$PANTRYATLAS_HOME/llama.cpp"
MODELS_DIR="$PANTRYATLAS_HOME/models"
STAMPS_DIR="${STAMPS_DIR:-$PANTRYATLAS_HOME/.bootstrap-stamps}"
REPO_DIR="${REPO_DIR:-$HOME/pantryatlas}"

# Runtime data dir (where the app + systemd unit read recipes.db). Distinct from
# PANTRYATLAS_HOME above, which is the install root.
PANTRYATLAS_DATA_DIR="${PANTRYATLAS_DATA_DIR:-$HOME/.pantryatlas}"

# Prebuilt recipe DB artifact — update these pins after each
# `ops/release/publish-db.sh` run (use the r2.dev URL until dl.pantryatlas.org
# is attached in the Cloudflare dashboard).
RECIPES_DB_URL="https://dl.pantryatlas.org/db/recipes-v0.2.0.db"
RECIPES_DB_SHA256="REPLACE_AFTER_FIRST_PUBLISH"

SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
# shellcheck source=ops/lib/fetch.sh
source "$SCRIPT_DIR/lib/fetch.sh"

# ============================================================
# Stage helpers
# ============================================================
log() { echo "[bootstrap] $*"; }

require_arm64() {
    local arch
    arch="$(uname -m)"
    if [ "$arch" != "aarch64" ] && [ "$arch" != "arm64" ]; then
        echo "ERROR: ARM64 required (this script targets Raspberry Pi 5)" >&2
        echo "Detected architecture: $arch" >&2
        exit 1
    fi
    log "Architecture check: $arch OK"
}

stage_apt_install() {
    local stamp="$STAMPS_DIR/01-apt-install.done"
    if [ -f "$stamp" ]; then
        log "apt-install: already done (remove $stamp to re-run)"
        return 0
    fi
    log "apt-install: installing build deps..."
    sudo apt-get update -y
    sudo apt-get install -y --no-install-recommends \
        build-essential \
        cmake \
        git \
        python3-venv \
        python3-dev \
        sqlite3 \
        libsqlite3-dev \
        curl \
        ca-certificates
    touch "$stamp"
    log "apt-install: done"
}

stage_venv() {
    local stamp="$STAMPS_DIR/02-venv.done"
    if [ -f "$stamp" ]; then
        log "venv: already done"
        return 0
    fi
    log "venv: creating Python venv at $PANTRYATLAS_VENV..."
    python3 -m venv "$PANTRYATLAS_VENV"
    "$PANTRYATLAS_VENV/bin/pip" install --upgrade pip setuptools wheel
    touch "$stamp"
    log "venv: done"
}

stage_llama_cpp() {
    local stamp="$STAMPS_DIR/03-llama-cpp-build.done"
    if [ -f "$stamp" ]; then
        log "llama.cpp build: already done"
        return 0
    fi
    log "llama.cpp build: cloning + building (this takes ~5-10 min on Pi 5)..."
    mkdir -p "$LLAMA_CPP_DIR"
    if [ ! -d "$LLAMA_CPP_DIR/.git" ]; then
        git clone "$LLAMA_CPP_REPO" "$LLAMA_CPP_DIR"
    fi
    git -C "$LLAMA_CPP_DIR" fetch origin
    git -C "$LLAMA_CPP_DIR" checkout "$LLAMA_CPP_COMMIT"
    cmake -B "$LLAMA_CPP_DIR/build" "$LLAMA_CPP_DIR" \
        -DLLAMA_NATIVE=ON \
        -DGGML_LLAMAFILE=ON
    cmake --build "$LLAMA_CPP_DIR/build" -j"$(nproc)" --target llama-server llama-cli
    touch "$stamp"
    log "llama.cpp build: done"
}

stage_gemma_download() {
    local stamp="$STAMPS_DIR/04-gemma-download.done"
    local gguf="$MODELS_DIR/gemma-4-E4B-it-Q4_K_M.gguf"
    if [ -f "$stamp" ]; then
        log "gemma download: already done"
        return 0
    fi
    mkdir -p "$MODELS_DIR"
    log "gemma download: fetching ~5 GB GGUF..."
    fetch_verified "$GEMMA4_GGUF_URL" "$GEMMA4_GGUF_SHA256" "$gguf"
    touch "$stamp"
    log "gemma download: done (verified)"
}

stage_db_download() {
    local stamp="$STAMPS_DIR/07-db-download.done"
    if [ -f "$stamp" ]; then
        log "db download: already done"
        return 0
    fi
    if [ "$RECIPES_DB_SHA256" = "REPLACE_AFTER_FIRST_PUBLISH" ]; then
        echo "ERROR: RECIPES_DB_SHA256 is still REPLACE_AFTER_FIRST_PUBLISH — run ops/release/publish-db.sh and update the pins" >&2
        return 3
    fi
    mkdir -p "$PANTRYATLAS_DATA_DIR"
    log "db download: fetching prebuilt recipes.db..."
    fetch_verified "$RECIPES_DB_URL" "$RECIPES_DB_SHA256" \
        "$PANTRYATLAS_DATA_DIR/recipes.db"
    touch "$stamp"
    log "db download: done (verified)"
}

stage_pip_install() {
    local stamp="$STAMPS_DIR/05-pip-install.done"
    if [ -f "$stamp" ]; then
        log "pip install: already done"
        return 0
    fi
    log "pip install: installing pantryatlas in editable mode..."
    "$PANTRYATLAS_VENV/bin/pip" install -e "${REPO_DIR}[dev]"
    touch "$stamp"
    log "pip install: done"
}

stage_web_build() {
    local stamp="$STAMPS_DIR/06-web-build.done"
    if [ -f "$stamp" ]; then
        log "web build: already done"
        return 0
    fi
    log "web build: installing Node deps and building frontend..."
    cd "${REPO_DIR}/web" && npm install && npm run build
    touch "$stamp"
    log "web build: done"
}

stage_smoke_test() {
    log "smoke test: verifying imports..."
    "$PANTRYATLAS_VENV/bin/python" -c '
import pantryatlas
import pantryatlas.embeddings
import pantryatlas.store.ingredients
import pantryatlas.geometry.slerp
import pantryatlas.pantry
print("pantryatlas " + pantryatlas.__version__ + " imports OK")
'
    log "smoke test: done"
}

# ============================================================
# Main
# ============================================================
main() {
    require_arm64
    mkdir -p "$PANTRYATLAS_HOME" "$STAMPS_DIR"

    stage_apt_install
    stage_venv
    stage_llama_cpp
    stage_gemma_download
    stage_db_download
    stage_pip_install
    stage_web_build
    stage_smoke_test

    log "Venv:           $PANTRYATLAS_VENV"
    log "Gemma 4 GGUF:   $MODELS_DIR/gemma-4-E4B-it-Q4_K_M.gguf"
    log "Recipes DB:     $PANTRYATLAS_DATA_DIR/recipes.db"
    log "llama.cpp:      $LLAMA_CPP_DIR/build"
    log "Next:           T-010 will use these via GemmaRunner"
    log "BOOTSTRAP COMPLETE"
}

if [[ "${BASH_SOURCE[0]}" == "${0}" ]]; then
    main "$@"
fi
