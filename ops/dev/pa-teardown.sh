#!/usr/bin/env bash
# pa-teardown — completely remove the pi-nas dev/staging node. NAS services untouched.
# Run from robot. Requires passwordless-sudo ssh as the admin account (default: merry).
set -euo pipefail
ADMIN="${PA_ADMIN:-merry@pi-nas.local}"
ssh -o BatchMode=yes "$ADMIN" '
sudo systemctl disable --now pantryatlas-dev-navigator.service 2>/dev/null || true
sudo rm -f /etc/systemd/system/pantryatlas-dev-navigator.service /etc/sudoers.d/pantrydev-navigator
sudo systemctl daemon-reload
sudo userdel -r pantrydev 2>/dev/null || true
echo "removed: service unit, sudoers drop-in, pantrydev user + /home/pantrydev"
'
echo "teardown complete — Plex / Samba / NFS / DNS untouched"
echo "NOTE: the kiosk QR card still points at :8090; remove it from /var/www/html/index.html if desired (a .bak exists)."
