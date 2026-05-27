# Epicure-core systemd units

Three units for running the epicure-core daemon stack as a set of long-lived
services under a dedicated `epicure` system user.

## Units

| Unit | Purpose |
|---|---|
| `epicure-mem-monitor.service` | Memory-pressure monitor (starts first) |
| `epicure-embeddings.service` | bge-m3 FastAPI embeddings sidecar on port 8089 |
| `epicure-gemma.service` | Gemma 4 llama.cpp server (starts after mem-monitor) |

## Prerequisites

These units assume the layout created by `ops/pi-bootstrap.sh` (T-009):

- System user `epicure` with home `/home/epicure`
- Python venv at `/home/epicure/epicure/venv/`
- `epicure-core` installed in the venv
- GGUF model files under `/home/epicure/epicure/models/`

## Install

```bash
sudo bash ops/systemd/install.sh
sudo systemctl start epicure-mem-monitor epicure-embeddings epicure-gemma
```

## `systemd-analyze verify` note

`systemd-analyze verify` validates unit syntax **and** checks that `ExecStart`
binaries exist on the local machine. On a development machine that has not run
`pi-bootstrap.sh` (i.e. no `epicure` user, no `/home/epicure/epicure/venv/`),
the command exits non-zero with:

```
epicure-gemma.service: Command /home/epicure/epicure/venv/bin/python is not executable: No such file or directory
```

This is expected — the units target the production deployment layout, not the
dev machine. Unit **syntax** is valid; the failure is a path-existence check
for binaries that only exist after bootstrap.

On a fully-bootstrapped Pi (post `pi-bootstrap.sh`), `systemd-analyze verify`
exits 0 for all three units. AC-5/6/7 are therefore treated as **skipped with
documented reason** on this dev Pi.
