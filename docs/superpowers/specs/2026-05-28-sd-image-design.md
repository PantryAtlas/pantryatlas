# Design — Lean Pre-Baked SD Image

- **Date:** 2026-05-28
- **Status:** Approved (brainstorming) — ready for implementation planning
- **Scope of this document:** Sub-project B of the "distribute PantryAtlas to a wide audience" effort
- **Branch context:** authored on `feat/sd-image`, **stacked on `feat/hosted-recipe-db`** (sub-project A) because it reuses A's `ops/lib/fetch.sh` (`fetch_verified`) and mirrors A's manifest/publish pattern.

## Motivation

Sub-project A made the recipe DB a hosted artifact so installs are fast. But the
onboarding still assumes a developer: flash RPi OS, SSH in, run a bootstrap. The
stated mission ("kitchens everywhere", including non-technical buyers) needs a
**flash-and-go appliance**: the buyer flashes one image, boots a Pi 5, opens
`http://pantryatlas.local`, and the core flow works offline — no shell, no
bootstrap, no waiting.

This sub-project produces that image: a **lean, pre-baked `pantryatlas-vX.img.xz`**
built **non-destructively on robot** (it writes an image *file*; it never flashes
or modifies any dev machine) and published to R2.

### Lean, not full

Per the brainstorming decision: bake the **core** (bge-m3 embeddings + recipes.db
+ web PWA + services), so the type-pantry → ranked-recipes flow works on boot. The
**LLM/Gemma is deliberately excluded** — the photograph-the-shelf path shows the
already-implemented 503-graceful "vision unavailable" state until the operator
enables an LLM (on-device install or a LAN helper via the inference-provider
registry, PR #4). This keeps the image ~1–1.3 GB compressed and the build fast.

A complementary non-flashing "side-by-side install" (Docker / install script) is
explicitly deferred to issue #8.

## Decomposition of the overall effort

| # | Sub-project | Depends on | This doc? |
|---|---|---|---|
| A | Hosted recipe DB (R2 artifact + bootstrap fetch) | — | no — done (PR #7) |
| **B** | **Lean pre-baked SD image (sdm build → `.img.xz` → R2)** | A's `fetch_verified`; bakes local DB/model at build time | **yes** |

## Goals

- A repeatable, non-destructive build script on robot that emits
  `pantryatlas-vX.img.xz` (a file — never flashing hardware).
- The image boots a Pi 5 headless and serves the PWA at `http://pantryatlas.local`
  (port 80) with the core type→recipes flow working **fully offline**.
- Bake the validated local artifacts (recipes.db, bge-m3 model, web build) so no
  network is needed at first boot.
- A manifest pinning every input sha (base image, DB, model, pantryatlas commit)
  for auditability/reproducibility, plus an operator publish script to R2.
- A no-hardware validation (chroot smoke-test) that proves provisioning + that the
  app serves.

## Non-Goals (explicit out-of-scope)

- **Baking Gemma / any LLM.** Vision stays opt-in (503-graceful). The image
  installs no llama.cpp, no GGUF.
- **Flashing any machine.** The build only writes a file. Real-hardware
  confirmation is a one-time operator flash of a spare card (see Validation).
- **Hand-rolling RPi-image plumbing.** `sdm` owns rootfs resize/shrink, Bookworm
  first-boot suppression, service-enable, hostname/locale. We own only the
  PantryAtlas-specific provisioning.
- **A side-by-side / Docker install** (issue #8, deferred).
- **CI image builds.** Like A's DB, the image is built operator-side on a Pi
  (needs sudo + loop devices + the local artifacts); CI cannot build it. Pure
  helpers are unit-tested in CI; the full build + smoke-test is operator-run.
- **QEMU boot testing** (can be added later on top of the chroot smoke-test).

## Architecture

Four pieces; the testable logic is isolated in Python, the rest is thin bash
around `sdm`.

### Build engine: sdm + a PantryAtlas plugin

[`sdm`](https://github.com/gitbls/sdm) is a single-file bash tool purpose-built to
customize Raspberry Pi OS images **on a Pi**. It owns the fragile machinery:
growing the image (`--extend`), running customization in a chroot, suppressing the
Bookworm first-boot user wizard, enabling services, setting hostname/locale, and
shrinking the image (`--shrink`). We provide:

1. **`ops/image/build-image.sh`** (operator-run, sudo) — thin orchestration:
   - `df` guard: abort if robot has < 10 GB free.
   - Download + sha256-verify the pinned RPi OS Lite arm64 (Bookworm) base via the
     existing `fetch_verified` (from sub-project A).
   - `sdm --extend` the image to make room (~4 GB).
   - `sdm --customize ... --plugin @<repo>/ops/image/sdm-plugin-pantryatlas ...
     --hostname pantryatlas --batch --restart` — sdm runs our plugin in-chroot.
   - `sdm --shrink` then `xz` → `pantryatlas-vX.img.xz`.
   - Print the resulting path + sha for the manifest/publish step.

2. **`ops/image/sdm-plugin-pantryatlas`** (the only PantryAtlas-specific logic) —
   an sdm plugin (bash, sdm plugin API) that, inside the image chroot:
   - Creates the `pantryatlas` user + group (home `/home/pantryatlas`).
   - Places the repo at `/home/pantryatlas/pantryatlas` (pinned commit) and creates
     the runtime venv (`pip install .` — runtime extras only; **no dev, no
     llama.cpp/Gemma**).
   - Copies the **baked payload** staged by the host (see below) into place and
     `chown`s it to `pantryatlas`.
   - Installs + enables the **3 systemd units** (`pantryatlas-mem-monitor`,
     `pantryatlas-embeddings`, `pantryatlas-navigator`) via `systemctl --root` —
     **not** `pantryatlas-gemma`.
   - Writes the nftables port-80 redirect + enables `nftables`.
   - Sets `/etc/hostname` = `pantryatlas`, the matching `/etc/hosts` entry, and
     enables `avahi-daemon`.
   - Installs apt runtime deps only (python3-venv, sqlite3, libsqlite3-0,
     avahi-daemon, nftables) — no build-essential/cmake.

### The baked payload (staged on the host, copied in by the plugin)

Lean — everything needed for the core flow, nothing for the LLM:

| Item | Source on robot | Destination in image | Size |
|---|---|---|---|
| recipe DB | `~/.pantryatlas/recipes.db` | `/home/pantryatlas/.pantryatlas/recipes.db` | 227 MB |
| bge-m3 model | `~/.cache/pantryatlas/bge-m3/` | `/home/pantryatlas/.cache/pantryatlas/bge-m3/` | 559 MB |
| web PWA | `web/dist/` (built on host) | served by navigator from the repo's `web/dist` | small |

Building the web on the host (not in the image) keeps node out of the appliance.
Baking from robot's local files (not R2) means B does **not** wait on A being
published.

### Port 80 and mDNS

- **Port 80:** an `nftables` prerouting `redirect tcp dport 80 → :8090` so the
  navigator (unchanged, on `:8090`) is reachable at `http://pantryatlas.local`.
  Chosen over `setcap` on the venv python, which breaks on python/pip upgrades.
- **mDNS:** `/etc/hostname` = `pantryatlas` **and** an `/etc/hosts` `127.0.1.1
  pantryatlas` entry **and** `avahi-daemon` enabled — all three are required for
  `pantryatlas.local` to resolve.

### Manifest + publish (mirrors sub-project A)

`ops/release/publish-image.sh <img.xz> <version>` (operator-run, dry-run capable
like `publish-db.sh`) uploads to R2:

```
img/pantryatlas-v0.2.0.img.xz       ← the image
img/pantryatlas-v0.2.0.json         ← per-version manifest
img/pantryatlas-latest.json         ← pointer
```

Manifest pins every input for reproducibility:

```json
{
  "image_version": "v0.2.0",
  "base_image": "raspios-lite-arm64-2026-xx-xx",
  "base_image_sha256": "<...>",
  "recipes_db_sha256": "<...>",
  "bge_m3_sha256": "<...>",
  "pantryatlas_commit": "<git sha>",
  "url": "https://dl.pantryatlas.org/img/pantryatlas-v0.2.0.img.xz",
  "sha256": "<of the .img.xz>",
  "bytes": 0,
  "built_at": "..."
}
```

## Validation

**`tests/ops/test_image_smoke.py`** (`pi_integration` — needs sudo + loop, so
gated like A's live test): given a built image, loop-mount it, `chroot` (native
arm64 on robot), and assert:

- `recipes.db`, the bge-m3 model, and `web/dist` are present and owned by
  `pantryatlas`.
- the 3 units are enabled (symlinks in `multi-user.target.wants/`) and **gemma is
  not**.
- **`userconfig.service` is masked/absent** (Bookworm first-boot wizard
  suppressed — otherwise the appliance hangs at first boot).
- `pantryatlas` user exists; `/etc/hostname` = `pantryatlas`; `/etc/hosts` entry
  present; `avahi-daemon` enabled; the nftables redirect rule is present.
- start `uvicorn` for the navigator inside the chroot and `curl :8090` → 200
  (proves the baked app + DB + model actually serve).

**Honest validation gap:** the chroot smoke-test proves *provisioning* and that the
app serves when invoked — it does **not** prove boot-time success (systemd
ordering, kernel/firmware, mDNS on a real network, first-boot interception). The
truthful acceptance chain is **chroot smoke-test (no hardware) + one operator
flash of a spare SD card** to confirm real hardware. That single flash — on the
operator's schedule, on a spare card, never a dev machine — is the gate before
declaring v1 functional. The spec does not pretend the image is proven without it.

## Code layout + TDD (mirrors A's testable-core pattern)

| File | New/Mod | Responsibility | Tested by |
|---|---|---|---|
| `pantryatlas/ops/image_build.py` | new | pure helpers: image-manifest builder, nftables-ruleset text, units-to-enable list, base-image pin verifier | `tests/ops/test_image_build.py` (unit, CI) |
| `ops/image/build-image.sh` | new | orchestration: df guard, fetch base, sdm extend/customize/shrink, xz | `bash -n` + smoke-test |
| `ops/image/sdm-plugin-pantryatlas` | new | sdm plugin: user, venv, bake payload, enable 3 units, nft, hostname/avahi | smoke-test |
| `ops/image/stage-payload.sh` | new | stage recipes.db + bge-m3 + web/dist from robot into a build dir | `bash -n` + smoke-test |
| `ops/release/publish-image.sh` | new | operator publish of `.img.xz` + manifests to R2 (dry-run capable) | `tests/ops/test_publish_image.py` (dry-run) |
| `tests/ops/test_image_smoke.py` | new | `pi_integration` chroot smoke-test (sudo+loop) | operator-run |
| `ops/image/README.md` | new | build + flash + validate runbook | — |

Pure helpers in `image_build.py` are unit-tested in CI exactly like
`db_publish.py`. The bash + sdm plugin are thin and covered by the chroot
smoke-test. `python3 -m ruff` / `PYTHONPATH=. python3 -m pytest` are the local
commands (the dev venv has no pytest; system python3 does).

## Error handling

- **Insufficient disk** → `build-image.sh` aborts at the top with a clear message.
- **Missing local artifacts** (recipes.db / bge-m3) → `stage-payload.sh` aborts
  with the path it expected (operator must have run the DB ingest + embeddings once).
- **sdm not installed** → `build-image.sh` checks and points to the install.
- **Base-image sha mismatch** → `fetch_verified` aborts (reused from A).
- **Publish** → fail fast on missing wrangler/R2 auth before uploading the
  multi-GB artifact; `PUBLISH_DRY_RUN=1` previews.

## Components summary

| Unit | Does what | Depends on |
|---|---|---|
| `image_build.py` helpers | manifest, nft ruleset, unit list, pin verify (pure) | stdlib |
| `stage-payload.sh` | gather DB+model+web into a build dir | local artifacts |
| `sdm-plugin-pantryatlas` | PantryAtlas provisioning inside the image | sdm plugin API |
| `build-image.sh` | orchestrate sdm build → `.img.xz` | sdm, fetch_verified |
| `publish-image.sh` | upload image + manifests to R2 | wrangler, image_build.py |
| `test_image_smoke.py` | chroot acceptance gate | a built image, sudo+loop |
