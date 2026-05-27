#!/usr/bin/env bash
# Bootstrap a fresh Pi 5 (Bookworm) into "epicure-core smoke-test ready" state.
#
# Idempotent: safe to re-run; skips completed stages.
# Architecture-locked: refuses to run on anything but aarch64.
#
# Usage:
#   bash ops/pi-bootstrap.sh
#
# Env overrides:
#   EPICURE_HOME   — installation root (default: ~/epicure)
#   REPO_DIR       — path to the epicure-core checkout (default: ~/epicure-core)

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

EPICURE_HOME="${EPICURE_HOME:-$HOME/epicure}"
EPICURE_VENV="$EPICURE_HOME/venv"
LLAMA_CPP_DIR="$EPICURE_HOME/llama.cpp"
MODELS_DIR="$EPICURE_HOME/models"
STAMPS_DIR="$EPICURE_HOME/.bootstrap-stamps"
REPO_DIR="${REPO_DIR:-$HOME/epicure-core}"

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
    log "venv: creating Python venv at $EPICURE_VENV..."
    python3 -m venv "$EPICURE_VENV"
    "$EPICURE_VENV/bin/pip" install --upgrade pip setuptools wheel
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
    curl -fL --retry 3 -o "$gguf.tmp" "$GEMMA4_GGUF_URL"
    log "gemma download: verifying SHA256..."
    local actual
    actual="$(sha256sum "$gguf.tmp" | awk '{print $1}')"
    if [ "$actual" != "$GEMMA4_GGUF_SHA256" ]; then
        echo "ERROR: SHA256 mismatch: expected $GEMMA4_GGUF_SHA256, got $actual" >&2
        rm -f "$gguf.tmp"
        exit 2
    fi
    mv "$gguf.tmp" "$gguf"
    touch "$stamp"
    log "gemma download: done (verified)"
}

stage_pip_install() {
    local stamp="$STAMPS_DIR/05-pip-install.done"
    if [ -f "$stamp" ]; then
        log "pip install: already done"
        return 0
    fi
    log "pip install: installing epicure-core in editable mode..."
    "$EPICURE_VENV/bin/pip" install -e "${REPO_DIR}[dev]"
    touch "$stamp"
    log "pip install: done"
}

stage_smoke_test() {
    log "smoke test: verifying imports..."
    "$EPICURE_VENV/bin/python" -c '
import epicure_core
import epicure_core.embeddings
import epicure_core.store.ingredients
import epicure_core.geometry.slerp
import epicure_core.pantry
print("epicure-core " + epicure_core.__version__ + " imports OK")
'
    log "smoke test: done"
}

# ============================================================
# Main
# ============================================================
main() {
    require_arm64
    mkdir -p "$EPICURE_HOME" "$STAMPS_DIR"

    stage_apt_install
    stage_venv
    stage_llama_cpp
    stage_gemma_download
    stage_pip_install
    stage_smoke_test

    log "Venv:           $EPICURE_VENV"
    log "Gemma 4 GGUF:   $MODELS_DIR/gemma-4-E4B-it-Q4_K_M.gguf"
    log "llama.cpp:      $LLAMA_CPP_DIR/build"
    log "Next:           T-010 will use these via GemmaRunner"
    log "BOOTSTRAP COMPLETE"
}

main "$@"
