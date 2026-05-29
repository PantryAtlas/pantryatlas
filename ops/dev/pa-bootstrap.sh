#!/usr/bin/env bash
# pa-bootstrap — one-time setup of the pi-nas dev/staging node. Run from robot.
# Creates an isolated `pantrydev` unix user (relocates ALL data via $HOME), authorizes
# robot's SSH key, installs the hardened systemd unit + a narrow sudoers entry.
# Requires: passwordless-sudo ssh as the admin account on pi-nas (default: merry).
# See docs/superpowers/specs/2026-05-28-pinas-dev-node-design.md
set -euo pipefail
REPO="$(cd "$(dirname "${BASH_SOURCE[0]}")/../.." && pwd)"
ADMIN="${PA_ADMIN:-merry@pi-nas.local}"
PUBKEY="$(cat "${HOME}/.ssh/id_ed25519.pub")"

echo "==> creating pantrydev + ssh + data dirs on pi-nas (via $ADMIN)"
ssh -o BatchMode=yes "$ADMIN" "
set -e
sudo useradd -m -s /bin/bash pantrydev 2>/dev/null && echo 'created pantrydev' || echo 'pantrydev exists (ok)'
sudo install -d -m 700 -o pantrydev -g pantrydev /home/pantrydev/.ssh
echo '$PUBKEY' | sudo tee /home/pantrydev/.ssh/authorized_keys >/dev/null
sudo chown pantrydev:pantrydev /home/pantrydev/.ssh/authorized_keys
sudo chmod 600 /home/pantrydev/.ssh/authorized_keys
sudo install -d -m 755 -o pantrydev -g pantrydev /home/pantrydev/.pantryatlas /home/pantrydev/pantryatlas
"

echo "==> installing systemd unit + narrow sudoers"
scp -o BatchMode=yes "$REPO/ops/dev/pantryatlas-dev-navigator.service" "$ADMIN:/tmp/" >/dev/null
ssh -o BatchMode=yes "$ADMIN" '
set -e
sudo cp /tmp/pantryatlas-dev-navigator.service /etc/systemd/system/
sudo chmod 644 /etc/systemd/system/pantryatlas-dev-navigator.service
printf "pantrydev ALL=(root) NOPASSWD: /usr/bin/systemctl restart pantryatlas-dev-navigator.service, /usr/bin/systemctl start pantryatlas-dev-navigator.service, /usr/bin/systemctl stop pantryatlas-dev-navigator.service, /usr/bin/systemctl status pantryatlas-dev-navigator.service\n" | sudo tee /etc/sudoers.d/pantrydev-navigator >/dev/null
sudo chmod 440 /etc/sudoers.d/pantrydev-navigator
sudo visudo -cf /etc/sudoers.d/pantrydev-navigator
sudo systemctl daemon-reload
sudo systemctl enable pantryatlas-dev-navigator.service
'
echo "==> bootstrap complete. First deploy:  ops/dev/pa-deploy.sh --with-db"
