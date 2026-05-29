# Design — Lean PantryAtlas Dev/Staging Node on pi-nas

**Date:** 2026-05-28
**Status:** ✅ **Phase 1 EXECUTED & LIVE** 2026-05-28 — http://pi-nas.local:8090 (see execution record below). Spec + `ops/dev/` scripts awaiting operator review/commit.
**Scope:** Phase 1 only (config/ops, no code changes). Phase 2 (kitchen-mesh inference offload) is documented as explicit future work, not built here.

## Phase 1 execution record (2026-05-28)

Stood up and verified end-to-end:

- `pantrydev` user (uid 1002) created on pi-nas; robot's ed25519 key authorized for rsync.
- `pip install -e .` (runtime deps only — **not** `.[dev]`; the staging box runs the app, it doesn't need ruff/pytest) succeeded **first try** on a clean Py 3.13 venv (numpy 2.4.6, onnxruntime 1.26.0, pyarrow 24.0.0, fastapi, uvicorn…). No undeclared-dep surprises.
- `recipes.db` (227 MB) shipped to `~pantrydev/.pantryatlas/`.
- Hardened unit `pantryatlas-dev-navigator.service` on `0.0.0.0:8090`, enabled (survives reboot), `active (running)`.
- Verified: `/` → 200 real PWA (not placeholder), `/navigator/pantry` → 200, `/assets/*.js` → 200. Vision route → 503 as designed (no local Gemma; Phase 2 enables it).
- **Embed path verified end-to-end under the hardened unit:** `POST /navigator/pantry/resolve {"raw":"2 ripe roma tomatoes"}` → 200 `{"canonical_name":"tomato"}`. First call 73 s (one-time bge-m3 download, 559 MB now cached in `~/.cache/pantryatlas/bge-m3`); **warm embed ~0.14 s**. Confirms HF egress works under `RestrictAddressFamilies`, cache writes under `ProtectSystem=strict`+`ReadWritePaths`, onnxruntime runs, and the clean venv is complete. (Resolves open risk #1 for the warm case; not yet stressed concurrently with a Plex transcode.)
- `DEPLOYED_VERSION` stamps the git SHA under test.
- A matching **"PantryAtlas" QR card** + footer link were added to the pi-nas kiosk page (`/var/www/html/index.html`, backup `.bak.20260528-181829`); the QR encodes `http://pi-nas.local:8090/` and now resolves.

Deliverables: `ops/dev/{pantryatlas-dev-navigator.service, pa-bootstrap.sh, pa-deploy.sh, pa-teardown.sh, README.md}`. The full loop (`pa-deploy.sh`) was exercised twice and is one-command.

**Not done (deferred / blocked):** measuring bge-m3 `/refine` latency under concurrent Plex load (open risk #1); committing these files (a concurrent session is actively committing to `feat/sp-a-loop-foundation` — recommend a dedicated `feat/pinas-dev-node` branch to avoid mixing, done by the operator).

## Motivation

The operator wants to sideload pre-production PantryAtlas builds onto their always-on home server **`pi-nas`** (a Raspberry Pi 5, 8 GB RAM) and run them as a real user would — *without* reflashing the box or risking the services it already runs (Plex, Samba, NFS, local DNS). The official distribution paths today are flash-and-go (`ops/image/` SD image) or a from-source systemd stack (`ops/systemd/`) that assumes a *dedicated* PantryAtlas appliance — neither fits "add a disposable test instance next to an existing, precious workload."

The hard constraint, in the operator's words, is: **do not overwrite the existing image; the dev build must be fully sandboxed and trivially removable, with zero risk to the NAS services.**

### Key finding that shapes everything (verified by codebase recon, 2026-05-28)

PantryAtlas's **core product is light**. The instant `from-pantry` flow needs *no* inference at all; recipe ranking, `/refine`, and `/swaps` use a small **in-process ONNX embedder** (`bge-m3` int8, `pantryatlas/embeddings/__init__.py`). The **only heavy component** is the 4 B Gemma model (llama.cpp), and it is invoked by **exactly one route** — `POST /navigator/vision/parse-shelf` (shelf-photo parsing). See `pantryatlas/navigator/server.py:553-601`.

Therefore the NAS-safety goal is won simply by **not running Gemma on pi-nas**. The lean node is fully functional and Plex-safe *standalone*; the model is an optional add-on for one feature. This is materially simpler and safer than the original "run a model on the NAS" or even "borrow the robot's brain for everything" framings.

## Goals

1. A second, fully parallel PantryAtlas install on `pi-nas` that **cannot** touch Plex / Samba (445/139) / NFS (111) / DNS (53) / VNC (5900) or any future prod install.
2. **Trivially removable** — teardown is one `userdel -r` plus removing one unit file.
3. **No reflashing**, no Docker image build, no system-package churn beyond a Python venv.
4. A **one-command push-from-robot** deploy loop (`pa-deploy`) matching the operator's established rsync-to-target habit, with an optional live-reload mode.
5. **Version legibility** — always know exactly which pre-prod git SHA is under test.
6. **Zero code changes** to the PantryAtlas package (config + ops only).
7. **No model inference runs on pi-nas** — the 4 B Gemma never loads there.

## Non-Goals (explicit out-of-scope for Phase 1)

- **Vision / shelf-photo parsing.** Requires a gemma-multimodal `llama-server` somewhere on the tailnet; *neither robot nor pi-nas has one today* (no `llama-server` binary, no gemma GGUF, no `mmproj` on robot — only an unrelated `phi-3-mini` GGUF; robot's `:8080` is a FastAPI app, `:11434` ollama has no models). The route will return **HTTP 503 (`VisionUnavailable`)** on pi-nas — graceful; the rest of the app is unaffected.
- **Offloading embeddings to robot** ("borrows-a-LAN-brain"). The embeddings path is in-process ONNX with no HTTP seam; routing it remotely is a *code* feature (the SP-A kitchen-mesh work), deferred to Phase 2.
- **Promoting to a versioned RC channel / rollback slots.** The loop is "pi-nas runs whatever robot pushed"; we stamp the SHA but do not keep N versions. (Could be added later.)
- **A production install on pi-nas.** This is a disposable test node, not a service the operator depends on.
- **Re-ingesting recipes on pi-nas.** We ship the prebuilt `recipes.db`.

## Architecture

```
  ┌─ robot (16 GB Pi 5, dev/source box) ──────────┐        ┌─ pi-nas (8 GB Pi 5, NAS — UNTOUCHED) ───────────┐
  │  ~/pantryatlas (working tree, branch under     │        │  Plex · Samba · NFS · DNS · VNC   (as-is)        │
  │  test)                                         │        │                                                 │
  │                                                │ rsync  │  user: pantrydev   (NEW, fully isolated)        │
  │  $ pa-deploy [--reload] ───────────────────────┼───────▶│   /home/pantrydev/pantryatlas      (repo)       │
  │    rsync tree+web/dist → pip install -e →       │  ssh   │   /home/pantrydev/.pantryatlas/    (all data)   │
  │    stamp SHA → restart unit                     │        │     recipes.db · kitchen.db · pantry.json       │
  └────────────────────────────────────────────────┘        │   /home/pantrydev/.cache/pantryatlas/bge-m3     │
                                                             │                                                 │
                                                             │  systemd: pantryatlas-dev-navigator.service     │
   browser ── http://pi-nas.local:8090/ ─────────────────────▶   uvicorn :8090  (only externally-bound port)   │
                                                             │   ├─ in-process ONNX bge-m3  (light, local)     │
                                                             │   └─ Gemma/vision: NONE → /vision = 503         │
                                                             └─────────────────────────────────────────────────┘
```

### 1. Isolation primitive: a dedicated `pantrydev` unix user

This is the entire isolation story, and it is bulletproof for this app because **every runtime path derives from `Path.home()`** (verified: `pantryatlas/navigator/server.py:703-705`, `inference/config.py:10`, `gemma/runner.py:20`, `embeddings/__init__.py` `_CACHE_DIR`). Creating user `pantrydev` (home `/home/pantrydev`) auto-relocates **all** state:

| State | Path under `pantrydev` | Source |
|---|---|---|
| Recipe DB | `~/.pantryatlas/recipes.db` | `server.py:704` `_DEFAULT_DB_PATH` |
| Kitchen / pantry store | `~/.pantryatlas/kitchen.db`, `~/.pantryatlas/pantry.json` | `server.py:703,705` |
| Provider registry | `~/.pantryatlas/providers.json` | `inference/config.py:10` |
| Gemma flags (unused here) | `~/.pantryatlas/{baseline-tps.json,runner.blocked}` | `gemma/runner.py` |
| bge-m3 model cache | `~/.cache/pantryatlas/bge-m3` | `embeddings/__init__.py` |
| repo + venv | `~/pantryatlas`, `~/pantryatlas/.venv` | deploy target |

> **Footgun (documented):** `PANTRYATLAS_HOME`, `PANTRYATLAS_DATA_DIR`, `PANTRYATLAS_CACHE_DIR` are **decoys** — the package reads **none** of them at runtime (the systemd units set `PANTRYATLAS_HOME` but no code consumes it). Isolation MUST be via a distinct unix user / `$HOME`. Anyone "isolating" by editing those env vars silently writes into the *current* user's `~/.pantryatlas`.

Because `pantrydev` owns only its own home and one non-privileged service, it physically cannot read/write Plex/Samba data or bind their ports. Teardown: `sudo userdel -r pantrydev` + remove the unit file.

### 2. One hardened systemd service

`pantryatlas-dev-navigator.service` (system unit, `User=pantrydev`), running:

```
ExecStart=/home/pantrydev/pantryatlas/.venv/bin/uvicorn pantryatlas.navigator.server:app --host 0.0.0.0 --port 8090
```

- **Port `:8090`** — free on pi-nas (taken: 80, 8000, 8001; `:8090`/`:8089`/`:8099` are clear). The navigator is the *only* externally-bound listener. Port is set **only** via the uvicorn CLI here (there is no env/settings knob — `server.py` has no `uvicorn.run`/`__main__`).
- **Hardening:** `NoNewPrivileges=true`, `ProtectSystem=strict`, `ProtectHome=read-only` with `ReadWritePaths=/home/pantrydev`, `PrivateTmp=true`, `RestrictAddressFamilies=AF_INET AF_INET6 AF_UNIX`, `Restart=on-failure`. (Belt-and-suspenders on top of user isolation.)
- **Units we deliberately DROP** vs. the prod stack:
  - `pantryatlas-embeddings.service` — the `:8089` sidecar is **unused**; the navigator embeds **in-process** (`server.py` `_prod_embed` → `from pantryatlas.embeddings import embed`). Grep confirms zero in-repo HTTP consumers of `:8089`. (Also: launching it via `python -m pantryatlas.embeddings_server` would bind `0.0.0.0:8000` — a *taken* port. Don't.)
  - `pantryatlas-gemma.service` — its `ExecStart` runs `python -m pantryatlas.gemma.runner --serve`, but `runner.py` has **no `__main__`/argparse** → it imports-and-exits-0 (a verified no-op). We don't run a local Gemma at all.
  - `pantryatlas-mem-monitor.service` — only meaningful when a local llama.cpp model is loaded; not needed.
  - The SD-image **nftables `:80 → :8090` redirect** (`pantryatlas/ops/image_build.py:33`) — port 80 is a host singleton on pi-nas; we reach the navigator directly on `:8090`.

### 3. Inference posture (Phase 1)

- **Embeddings: local, in-process ONNX** (`bge-m3` int8). Small CPU/RAM footprint, fine alongside Plex on 8 GB. Model auto-downloads on first `/refine` from public HF (`Xenova/bge-m3`) into `~/.cache/pantryatlas/bge-m3` — **no API key, no auth**. The instant `from-pantry` path uses no embeddings at all.
- **Gemma: not present.** No GGUF, no `llama-server`, no `providers.json` LAN entry. With `providers.json` absent the registry seeds a default on-board local provider, but on first vision call its `GemmaRunner` tries to exec a `llama-server` binary that doesn't exist on pi-nas → fails → `VisionUnavailable` → **HTTP 503**. The navigator stays up; only `/vision/parse-shelf` is affected. This is the intended "vision deferred" behavior.

### 4. Data

`pa-deploy` ships the **prebuilt `recipes.db`** (227 MB, already present on robot at `~/.pantryatlas/recipes.db`) to `pantrydev@pi-nas:~/.pantryatlas/recipes.db`. No ingestion runs on pi-nas. (Optionally pull from `dl.pantryatlas.org/db/recipes-v0.2.0.db` instead — note CF Bot Fight Mode 403s the `Python-urllib`/`Python-requests` UA; use `curl`/rsync.)

### 5. Network / browser reach

The Preact PWA hardcodes **no API base** — every call is a **same-origin relative path** (`fetch('/navigator/...')`), and the service worker rejects cross-origin (`web/src/sw.ts:78-79`). The navigator *is* the PWA's origin (serves `index.html` at `/`, mounts `/assets`; no CORS middleware needed). So the browser hits `http://pi-nas.local:8090/` (or the Tailscale name) and all API calls resolve to that origin automatically. **No origin config is needed and none is possible** — a split CDN/API topology is unsupported without frontend changes (irrelevant here; the navigator brokers everything).

## Delivery: the `pa-deploy` script (lives on robot)

A small, idempotent bash script (`ops/dev/pa-deploy.sh` in the repo, invoked from robot). Two modes:

- **`pa-deploy`** (default): rsync → reinstall → restart the systemd unit. The persistent staging instance.
- **`pa-deploy --reload`**: run the navigator under `uvicorn --reload` (transient `systemd-run --user` or foreground) so subsequent rsyncs hot-reload without a restart — the tight live-edit loop.

Steps the default mode performs:

1. **Preflight on pi-nas:** confirm `:8090` is free (`ss -tlnp`), confirm `pantrydev` exists, confirm disk headroom.
2. **rsync the working tree** → `pantrydev@pi-nas:~/pantryatlas`, **including a freshly built `web/dist/`** (see freshness guard) and `pyproject.toml`. Exclude `.git`, `.venv`, `__pycache__`, `.pytest_cache`, `.hypothesis`, `node_modules`.
3. **`web/dist` freshness guard:** before rsync, ensure `web/dist/index.html` exists and is newer than `web/src` (run `npm --prefix web run build` if stale). **This is load-bearing:** the PWA is served from `Path(__file__).parent.parent.parent/'web'/'dist'` (`server.py:320`), `web/` ships in no wheel, and a missing/stale `web/dist` makes `serve_root()` silently return the JSON placeholder `{"status":"frontend not built"}` with no error. (This exact failure has bitten past builds.)
4. **Editable install in pantrydev's venv:** `~/pantryatlas/.venv/bin/pip install -e .[dev]`. **`-e` is required** — a non-editable wheel puts the package in site-packages where `../../../web/dist` doesn't exist → placeholder. **Clean-venv dep check:** install into pantrydev's *own* venv (never system Python) so undeclared deps surface (past bite: `python-multipart`, `Pillow` were masked by Pi-preinstalled packages and only failed on clean CI).
5. **Ship `recipes.db`** if absent or `--with-db`.
6. **Stamp the SHA (config-only, no code):** write `~/pantryatlas/DEPLOYED_VERSION` on pi-nas containing `git rev-parse HEAD`, dirty flag, branch, and UTC timestamp; echo it after deploy. (A `/version` HTTP endpoint is noted as a *tiny optional code add* but is out of Phase 1 scope.)
7. **Restart** `pantryatlas-dev-navigator.service` (`sudo systemctl restart`), then **smoke-check**: `curl -fsS http://pi-nas.local:8090/` and assert the body is the PWA (`<!doctype html`/`index.html`), **not** the `"frontend not built"` placeholder; assert `/navigator/pantry` (or equivalent read route) returns 200.

### Bootstrap (one-time, `ops/dev/pa-bootstrap.sh`, run against pi-nas)

1. `sudo useradd -m -s /bin/bash pantrydev`.
2. **Add robot's SSH public key** to `/home/pantrydev/.ssh/authorized_keys` (the operator currently auths to pi-nas as `merry`; `pa-deploy` rsyncs as `pantrydev`, so this is required or the deploy loop dead-ends on day one).
3. `python3 -m venv /home/pantrydev/pantryatlas/.venv` (pi-nas has Python 3.13.5 + venv).
4. Install the hardened unit file → `/etc/systemd/system/pantryatlas-dev-navigator.service`; `systemctl daemon-reload`; `enable --now`.
5. Grant `pantrydev` a narrow sudoers entry for *only* `systemctl {restart,status,start,stop} pantryatlas-dev-navigator.service` (so `pa-deploy` can restart without a password, without broad sudo).

### Teardown (`ops/dev/pa-teardown.sh`)

`systemctl disable --now pantryatlas-dev-navigator.service` → `rm /etc/systemd/system/pantryatlas-dev-navigator.service` → `daemon-reload` → `sudo userdel -r pantrydev` → remove the sudoers drop-in. Plex/Samba/NFS/DNS are untouched throughout.

## Validation

- **Isolation proof:** after teardown, `getent passwd pantrydev` is empty, `/home/pantrydev` is gone, and Plex/Samba/NFS/DNS report unchanged uptime/PIDs. Before teardown, confirm the only new listener is `:8090` and the only new files are under `/home/pantrydev`.
- **Functional proof:** `from-pantry` returns ranked recipes ~instantly (no embeddings); `/refine` returns 200 after the bge-m3 model has fetched; `/vision/parse-shelf` returns **503** (expected, vision deferred).
- **NAS-safety proof:** run a Plex transcode and a `/refine` batch concurrently; confirm pi-nas load and Plex playback stay acceptable (embeddings are CPU-light; no 4 B model is loaded). Record the observation — this is the one resource claim not yet measured.
- **Deploy-loop proof:** edit a string on robot → `pa-deploy` → see it on `http://pi-nas.local:8090/`; `cat ~pantrydev/pantryatlas/DEPLOYED_VERSION` matches robot's `git rev-parse HEAD`.
- **Placeholder guard proof:** deliberately delete `web/dist`, run `pa-deploy`, confirm it **rebuilds** rather than shipping the placeholder.

## Error handling / known footguns

| Risk | Mitigation |
|---|---|
| `web/dist` stale/missing → silent JSON placeholder | Freshness guard rebuilds; smoke-check asserts real PWA, not placeholder |
| Non-editable install → placeholder | `pip install -e .` enforced; smoke-check catches it |
| Undeclared deps masked by Pi-preinstalled packages | Install into pantrydev's clean venv only; never system Python |
| Isolating via `PANTRYATLAS_HOME` (decoy) → writes into wrong home | Isolation via unix user only; spec calls the decoy out explicitly |
| `:8090` taken / collision | Preflight `ss` check fails fast |
| `python -m pantryatlas.embeddings_server` binds taken `:8000` | We never run the sidecar; documented |
| Pulling DB via `Python-urllib` UA → CF 403 | Ship via rsync from robot, or `curl` |
| Vision called → 503 confuses tester | Documented expected behavior; Phase 2 enables it |

## Phase 2 (future, NOT built here) — kitchen-mesh inference offload

Documented so the boundary is explicit. To make pi-nas "borrow robot's brain":

- **Vision/Gemma (config + robot-side ops, no PantryAtlas code):** stand up llama.cpp `llama-server` on robot with the gemma-4-E4B GGUF **+ `--mmproj`**, bound to robot's tailnet interface; add a `kind:"lan"`, `multimodal:true`, `priority:10` provider to pi-nas's `~/.pantryatlas/providers.json` (or `POST /navigator/providers`) with `base_url=http://robot.<tailnet>:<port>`. Requires building llama.cpp + fetching ~3–4 GB of weights on robot (which has 16 GB + build tooling). Note: the registry's health probe is hardcoded to `GET {base_url}/health` and the model tag to `gemma-4-E4B-it` — llama.cpp satisfies both; **ollama does not** (no `/health`, validates the tag), so ollama is not a valid target without code changes.
- **Embeddings offload (PantryAtlas code — this IS the SP-A "borrows-a-LAN-brain" feature):** add an HTTP `embed_fn` (POST texts → robot's embeddings sidecar `/embed`, return `(N,1024)` ndarray), gate it behind a new `PANTRYATLAS_EMBED_URL` env var, and wire it into `_build_production_app` in place of `_prod_embed`. The DI seam already exists (`create_app(embed_fn=...)`, `rank_recipes(embed_fn=...)`, `Matcher(embed_fn=...)`). Robot's `embeddings_server.py` must bind a routable interface (its unit binds `127.0.0.1:8089`). Alternatively extend `Capability` with `"embed"` and route through the provider registry (larger, reuses `providers.json`).

## Components summary

| Component | Location | Phase 1 action |
|---|---|---|
| `pantrydev` unix user | pi-nas | create (bootstrap) |
| `pantryatlas-dev-navigator.service` | `ops/dev/` → `/etc/systemd/system/` | new hardened unit, `:8090`, `User=pantrydev` |
| `pa-bootstrap.sh` | `ops/dev/` | new — user, SSH key, venv, unit, narrow sudoers |
| `pa-deploy.sh` | `ops/dev/` | new — rsync + `-e` install + web/dist guard + SHA stamp + restart + smoke-check; `--reload` mode |
| `pa-teardown.sh` | `ops/dev/` | new — disable unit, `userdel -r`, remove sudoers |
| `recipes.db` | shipped to `~pantrydev/.pantryatlas/` | copy (no ingestion) |
| PantryAtlas package | — | **unchanged** (zero code in Phase 1) |

## Open questions / risks

1. **Unmeasured:** bge-m3 ONNX `/refine` latency and RAM on pi-nas *while Plex transcodes*. Expected fine (int8, CPU, only on refine/swaps) but should be observed during validation.
2. **`web/dist` build on pi-nas vs robot:** spec builds on robot and rsyncs the output (robot is the source box). pi-nas could build too (8 GB, vite is fine), but Pagefind-class native builds are not in this path.
3. **Commit destination** for this spec and the `ops/dev/` scripts — the working tree currently has unrelated in-progress SP-A changes; recommend a dedicated branch (e.g. `feat/pinas-dev-node`) rather than mixing into `feat/sp-a-loop-foundation`.
