#!/usr/bin/env bash
# Shared download helper, sourced by ops/pi-bootstrap.sh.
#
#   fetch_verified <url> <expected_sha256> <dest>
#
# Downloads to <dest>.tmp, verifies sha256, atomically moves into place.
# On mismatch or download failure: removes the partial and returns non-zero.

fetch_verified() {
    local url="$1" expected="$2" dest="$3"
    local tmp="$dest.tmp"
    if ! curl -fL --retry 3 -o "$tmp" "$url"; then
        echo "ERROR: download failed: $url" >&2
        rm -f "$tmp"
        return 1
    fi
    local actual
    actual="$(sha256sum "$tmp" | awk '{print $1}')"
    if [ "$actual" != "$expected" ]; then
        echo "ERROR: SHA256 mismatch for $url: expected $expected, got $actual" >&2
        rm -f "$tmp"
        return 1
    fi
    mv "$tmp" "$dest"
}
