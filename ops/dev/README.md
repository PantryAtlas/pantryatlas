# `ops/dev/` — pi-nas dev/staging node

A lean, sandboxed PantryAtlas **dev/staging** instance that runs alongside an existing
always-on box (here: `pi-nas`, which also runs Plex/Samba/NFS/DNS) **without** reflashing it
or risking those services. Design + rationale: `docs/superpowers/specs/2026-05-28-pinas-dev-node-design.md`.

## How it's isolated

- A dedicated **`pantrydev`** unix user. Every PantryAtlas data path derives from `$HOME`
  (`~/.pantryatlas/{recipes.db,kitchen.db,pantry.json,providers.json}`, `~/.cache/pantryatlas/bge-m3`),
  so one user relocates *all* state. (`PANTRYATLAS_HOME` is a decoy — never read by the code.)
- One hardened systemd unit on **`:8090`** (`pantryatlas-dev-navigator.service`). The only
  externally-bound port. 80/8000/8001 on pi-nas are taken by other services.
- **No local Gemma.** Inference is light: in-process ONNX `bge-m3` embeddings only. The 4 B Gemma
  never loads. The vision route (`/navigator/vision/parse-shelf`) returns 503 until a LAN provider
  is configured (Phase 2 — see the spec).

## Workflow (from robot)

```bash
ops/dev/pa-bootstrap.sh            # one-time: create user, ssh key, unit, sudoers
ops/dev/pa-deploy.sh --with-db     # first deploy (ships recipes.db too)
ops/dev/pa-deploy.sh               # every subsequent push: "pi-nas runs whatever robot has now"
ops/dev/pa-teardown.sh             # remove everything (userdel -r); NAS untouched
```

Reach it at **http://pi-nas.local:8090/** (also linked from the pi-nas kiosk page + its QR card).
`~pantrydev/pantryatlas/DEPLOYED_VERSION` records the exact git SHA under test.

## Gotchas (verified)

- `pip install -e .` (editable) is **required** — the PWA is served from a path relative to the
  package source (`web/dist`), which ships in no wheel. A non-editable install serves a JSON placeholder.
- `web/dist` must be built and current; `pa-deploy.sh` rebuilds it every run and the smoke-check
  fails loudly if the placeholder is served.
- Don't run `python -m pantryatlas.embeddings_server` here — its `__main__` binds `0.0.0.0:8000`,
  which collides with Paperless. The navigator embeds in-process; no sidecar needed.
