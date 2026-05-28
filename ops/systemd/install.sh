#!/usr/bin/env bash
# Install pantryatlas systemd units to /etc/systemd/system/ and enable them.
# Run as root (or with sudo).
set -euo pipefail

UNITS=(
    pantryatlas-mem-monitor.service
    pantryatlas-embeddings.service
    pantryatlas-gemma.service
    pantryatlas-navigator.service
)

UNIT_DIR="$(cd "$(dirname "$0")" && pwd)"
DEST=/etc/systemd/system

if [[ "$EUID" -ne 0 ]]; then
    echo "ERROR: must run as root (sudo)" >&2
    exit 1
fi

for unit in "${UNITS[@]}"; do
    install -m 644 "$UNIT_DIR/$unit" "$DEST/$unit"
    echo "installed: $DEST/$unit"
done

systemctl daemon-reload
for unit in "${UNITS[@]}"; do
    systemctl enable "$unit"
done

echo "INSTALL COMPLETE — run: sudo systemctl start pantryatlas-mem-monitor pantryatlas-embeddings pantryatlas-gemma pantryatlas-navigator"
