# PantryAtlas SD Image — Build & Validate Runbook

Produce a lean, headless Raspberry Pi OS (Bookworm arm64) image with PantryAtlas
pre-installed and ready to serve `http://pantryatlas.local` after first boot.

---

## 1. Prerequisites

### sdm (image customisation tool)

Pin version **V15.5** (the version `build-image.sh` expects):

```bash
curl -L https://github.com/gitbls/sdm/raw/V15.5/EZsdmInstaller | bash
```

Verify: `sdm --version`

### Required tools on the build host

`nft losetup xz python3 git npm curl sha256sum`

All must be on `PATH`; `build-image.sh` exits early if any are missing.

### Local baked-payload artifacts (on the robot / build host)

`build-image.sh` calls `stage-payload.sh`, which copies these into the image.
They must exist at the standard PantryAtlas paths before running the build:

| Artifact | Default path |
|---|---|
| Recipe database | `~/.pantryatlas/recipes.db` |
| BGE-M3 int8 ONNX model | `~/.cache/pantryatlas/bge-m3/onnx/model_int8.onnx` |

Ingest the DB if it is missing:

```bash
python -m pantryatlas.navigator.ingest   # builds ~/.pantryatlas/recipes.db
```

The bge-m3 model lazy-downloads on first embed call; on the robot it should
already be present at `~/.cache/pantryatlas/bge-m3/onnx/model_int8.onnx`.

### Push `feat/sd-image` to origin FIRST

The `sdm-plugin-pantryatlas` plugin runs **inside the nspawn container** (no
access to your local working tree) and clones
`https://github.com/PantryAtlas/pantryatlas.git` at the exact commit that was
`HEAD` when you ran the build.

`build-image.sh` checks this for you — it `git fetch`es the commit from the
public remote and fails fast if it is not yet reachable.  But the check only
passes once the commit is pushed.

```bash
git push origin feat/sd-image
```

---

## 2. Build

Run from the repo root (needs `sudo` for sdm + loop devices):

```bash
sudo bash ops/image/build-image.sh v0.2.0
```

The script needs ≥ 10 GB free on `/` and network egress (apt, GitHub, pip).
Expect 20–40 minutes on a Pi 5.

### Output artifacts

After a successful build, `build-image.sh` moves the final artifacts to `dist/`:

| Artifact | Path |
|---|---|
| Compressed image | `dist/pantryatlas-v0.2.0.img.xz` |
| Release manifest dir | `dist/manifest-v0.2.0/` |
| Version manifest | `dist/manifest-v0.2.0/pantryatlas-v0.2.0.json` |
| Latest pointer | `dist/manifest-v0.2.0/pantryatlas-latest.json` |

`dist/` is gitignored; it is the source of truth for publish.

---

## 3. Validate (no hardware required)

Decompress the image first (the smoke-test needs an uncompressed `.img`):

```bash
xz -dk dist/pantryatlas-v0.2.0.img.xz
# produces dist/pantryatlas-v0.2.0.img  (keep the .xz for publishing)
```

Run the chroot smoke-test (needs `sudo`, `losetup`, `mount`):

```bash
PANTRYATLAS_PI_INTEGRATION=1 \
PANTRYATLAS_IMAGE=dist/pantryatlas-v0.2.0.img \
  python3 -m pytest tests/ops/test_image_smoke.py -m pi_integration -v
```

This mounts partition 2 of the image, asserts every provisioning invariant
(files, systemd symlinks, user, hostname, nftables rules, avahi), attempts a
best-effort uvicorn start inside the chroot, then tears down cleanly.

**What the smoke-test proves:** the image was provisioned correctly — all
expected files, users, and service symlinks are present.

**What it does NOT prove:** boot-time success (kernel, initrd, fstab, SD card
hardware).  See Step 5.

---

## 4. Publish to R2

The image is ~2 GB, and `wrangler r2 object put` caps single uploads at 300 MiB,
so `publish-image.sh` uploads via **rclone** (S3 multipart). Configure the remote
once — interactively, so the secret stays in your terminal, never in a script or
shell history:

```bash
rclone config
#   name: r2
#   Storage: s3        Provider: Cloudflare
#   access_key_id / secret_access_key: from an R2 API token
#     (Cloudflare dash → R2 → Manage R2 API Tokens → Object Read & Write)
#   region: auto
#   endpoint: https://<ACCOUNT_ID>.r2.cloudflarestorage.com
```

Verify the remote (lists buckets, no secrets): `rclone lsd r2:`

Dry-run first to confirm the upload targets:

```bash
PUBLISH_DRY_RUN=1 ops/release/publish-image.sh \
    dist/pantryatlas-v0.2.0.img.xz \
    v0.2.0 \
    dist/manifest-v0.2.0
```

Then publish for real:

```bash
ops/release/publish-image.sh \
    dist/pantryatlas-v0.2.0.img.xz \
    v0.2.0 \
    dist/manifest-v0.2.0
```

Bucket defaults to `pantryatlas-artifacts` (`PANTRYATLAS_R2_BUCKET` to override);
rclone remote defaults to `r2` (`PANTRYATLAS_R2_REMOTE` to override). rclone may
log a `501 Not Implemented` on its first attempt then succeed on retry — that is
a benign R2/rclone quirk; the upload completes. Verify the published image:

```bash
curl -fsS -A Mozilla/5.0 https://dl.pantryatlas.org/img/pantryatlas-v0.2.0.img.xz | sha256sum
# compare to "sha256" in dist/manifest-v0.2.0/pantryatlas-v0.2.0.json
```

---

## 5. Acceptance gate — one real hardware flash

The chroot smoke-test is a provisioning check, not a boot test.  Before
declaring v1 functional, flash a **spare SD card** (do not use your primary
robot card) and boot a Pi 5:

1. Flash with [Raspberry Pi Imager](https://www.raspberrypi.com/software/) →
   *Use custom image* → select `dist/pantryatlas-v0.2.0.img.xz`.
2. Insert into a Pi 5, power on, wait ~60 s.
3. Open `http://pantryatlas.local` — you should see the PantryAtlas web UI (HTML),
   NOT a `{"status":"frontend not built"}` JSON placeholder.
   From a shell:
   ```
   curl -fs http://pantryatlas.local/ | grep -qi '<html'
   ```
   A successful `grep` (exit 0) is the gate.

**No interactive login by default.** The appliance is web-UI only; no desktop
user is created.  If you need SSH access (e.g. for debugging), add a user via
sdm's `user` plugin before building:

```bash
# in build-image.sh sdm --customize invocation, add:
#   --plugin user:"username=craig|password=..."
```

or enable SSH key-based login in the sdm plugin directly.

---

## Notes

- `dist/` is gitignored.  Keep `.img` and `.img.xz` files off the repo.
- `~/.robot-md/keys/*` must never be committed (API keys live outside the project).
- Re-run the build from scratch if you bump the version — the manifest pins
  `pantryatlas-commit` and `built-at`, so partial rebuilds produce inconsistent
  manifests.
