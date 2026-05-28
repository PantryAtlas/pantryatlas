# Design — Hosted Recipe DB

- **Date:** 2026-05-28
- **Status:** Approved (brainstorming) — ready for implementation planning
- **Scope of this document:** Sub-project A of the "distribute PantryAtlas to a wide audience" effort
- **Branch context:** authored on `feat/hosted-recipe-db` (off `main` @ `ad7d439`)

## Motivation

Every PantryAtlas install today needs the prebuilt recipe vector DB
(`~/.pantryatlas/recipes.db`, 49,965 recipes, ~227 MB, sqlite-vec). Building it
is a **~5.2-hour CPU-bound ingest on a Pi 5** (embedding 49,965 title+ingredient
strings at the measured ~16 strings/sec floor). The current `pi-bootstrap.sh`
does **not** fetch or build this DB at all — it is a separate, undocumented,
multi-hour manual step. That is the single biggest barrier to onboarding anyone
who is not the original builder.

This sub-project distributes the **already-built** DB as a **versioned,
checksum-pinned artifact on Cloudflare R2**, and adds a bootstrap stage that
downloads + verifies it in seconds. It is also a hard dependency of sub-project B
(the pre-baked SD image), which bakes this same artifact in at image-build time.

### Why this and not a CI rebuild

The DB cannot be rebuilt in CI: a 5.2 h Pi-CPU ingest does not fit an Actions
runner, and the raw RecipeNLG corpus + embedding model would have to be staged
there. The artifact is therefore **built once on the operator's Pi (it already
exists) and uploaded by the operator**. CI rebuild is explicitly out of scope
(see Non-Goals).

## Decomposition of the overall effort

| # | Sub-project | Depends on | This doc? |
|---|---|---|---|
| **A** | **Hosted recipe DB (R2 artifact + bootstrap fetch + publish flow)** | — | **yes** |
| B | Pre-baked lean SD image (chroot pipeline → `.img.xz` → R2) | A | no — next up, separate spec |

## Goals

- Publish the prebuilt `recipes.db` as an immutable, versioned, sha256-pinned
  object on R2, reachable at a stable URL.
- Stamp the DB so the artifact self-describes its schema version and the
  embedding model its vectors are bound to.
- Ship a manifest (JSON) describing each release, plus a `latest` pointer.
- Add an idempotent `pi-bootstrap.sh` stage that downloads + sha256-verifies the
  DB into the runtime data dir, reusing a shared verified-fetch helper.
- Provide an operator-run publish script that stamps → uploads → writes manifests
  → emits the pins to paste into the bootstrap script.
- Keep the artifact license-compliant: RecipeNLG attribution travels with it.

## Non-Goals (explicit out-of-scope)

- **CI rebuild of the DB.** Operator uploads the prebuilt artifact. A future
  tag-triggered Action may *validate* (sha/manifest) but never *build*.
- **A `pantryatlas fetch-db` standalone CLI.** The idempotent bootstrap stage
  covers the documented install path; a CLI is deferred (YAGNI).
- **App-side schema_version enforcement** (fail-loud on mismatch when the store
  opens a DB). Noted as a follow-up; the stamp is written now so the check can be
  added later without re-publishing.
- **R2 custom-domain attachment automation.** Attaching `dl.pantryatlas.org` to
  the bucket is a Cloudflare-dashboard step (wrangler cannot do it — same
  limitation hit attaching Pages custom domains). It is an operator task; the
  tooling falls back to the raw `*.r2.dev` URL until the domain is live.

## Architecture

Three cooperating pieces, each independently testable:

1. **DB stamper** — a pure, idempotent function that writes version/model
   metadata into a copy of the DB. Input: a `recipes.db` path + release metadata.
   Output: the same DB with `PRAGMA user_version` set and a
   `_pantryatlas_db_meta(key, value)` table populated. No network.

2. **Publish script** (`ops/release/publish-db.sh`) — operator-run. Orchestrates:
   stamp → sha256 → upload `.db` to R2 → generate + upload per-version and
   `latest` manifests → upload `ATTRIBUTION.txt` → print the `RECIPES_DB_URL` +
   `RECIPES_DB_SHA256` pins for the bootstrap script. Depends on `wrangler` +
   the DB stamper + the manifest generator.

3. **Bootstrap fetch stage** (`stage_db_download` in `pi-bootstrap.sh`) — runs on
   the target machine at install time. Downloads the pinned URL, sha256-verifies,
   atomically installs to the runtime data dir. Depends only on `curl` + the
   shared `fetch_verified` helper. No knowledge of R2.

### R2 layout & access

```
bucket: pantryatlas-artifacts        →  dl.pantryatlas.org (public read; raw *.r2.dev until attached)
  db/recipes-v0.2.0.db               ←  the artifact (~227 MB), immutable per version
  db/recipes-v0.2.0.json             ←  per-version manifest, immutable
  db/recipes-latest.json             ←  pointer manifest, overwritten each release
  db/ATTRIBUTION.txt                 ←  RecipeNLG CC-BY-NC-4.0 notice, travels with the artifact
```

R2 is already enabled on the account (existing `platatlas-*` buckets). The
`pantryatlas-artifacts` bucket is created once (script or dashboard). Public read
access is appropriate for a free, open, non-commercial distribution.

### Manifest schema

Per-version manifest (`recipes-v0.2.0.json`) and `latest` pointer
(`recipes-latest.json`) share one schema:

```json
{
  "db_version": "v0.2.0",
  "schema_version": 1,
  "embedding_model": "bge-m3-int8-onnx",
  "recipe_count": 49965,
  "source": "RecipeNLG",
  "license": "CC-BY-NC-4.0",
  "url": "https://dl.pantryatlas.org/db/recipes-v0.2.0.db",
  "sha256": "<computed at publish>",
  "bytes": 238059520,
  "built_at": "2026-05-28T03:18:00Z"
}
```

`schema_version` and `embedding_model` are both load-bearing: the prebuilt
vectors are bound to the exact embedding model, so swapping the model invalidates
the artifact even when the table schema is unchanged. Pinning both lets a future
consumer detect either kind of drift.

### DB stamping

The DB currently has `PRAGMA user_version = 0` and **no** metadata table
(`recipes_meta` holds recipe *content*, not metadata). The stamper, run by the
publish script before upload (idempotent — safe to re-run):

- sets `PRAGMA user_version = <schema_version>` (currently `1`);
- creates `_pantryatlas_db_meta(key TEXT PRIMARY KEY, value TEXT)` if absent and
  upserts: `db_version`, `embedding_model`, `recipe_count`, `source`,
  `license`, `built_at`.

An extra table + a PRAGMA do not affect the store's existing queries (it reads
`recipes_meta` + `recipes_vec*`), so stamping is non-breaking.

### Bootstrap fetch stage

```bash
# new pinned config (update in sync with each DB release)
RECIPES_DB_URL="https://dl.pantryatlas.org/db/recipes-v0.2.0.db"
RECIPES_DB_SHA256="<sha256>"

# distinct from the script's PANTRYATLAS_HOME (install root); this is the runtime
# data dir the systemd unit also points at via its own PANTRYATLAS_HOME env.
PANTRYATLAS_DATA_DIR="${PANTRYATLAS_DATA_DIR:-$HOME/.pantryatlas}"

stage_db_download() {
    local stamp="$STAMPS_DIR/07-db-download.done"
    [ -f "$stamp" ] && { log "db download: already done"; return 0; }
    mkdir -p "$PANTRYATLAS_DATA_DIR"
    fetch_verified "$RECIPES_DB_URL" "$RECIPES_DB_SHA256" \
        "$PANTRYATLAS_DATA_DIR/recipes.db"
    touch "$stamp"
}
```

**Naming-collision note:** `pi-bootstrap.sh` already defines `PANTRYATLAS_HOME`
as the *install root* (`~/pantryatlas`), while the systemd units define
`PANTRYATLAS_HOME` as an env var for the *data dir* (`~/.pantryatlas`). The new
stage must target the data dir; it uses a separate `PANTRYATLAS_DATA_DIR` var to
avoid overloading the name further.

### Shared `fetch_verified` helper

Extract the existing Gemma stage's `.tmp` → `sha256sum` → compare → atomic `mv`
dance into one helper both stages call:

```bash
# fetch_verified <url> <expected_sha256> <dest>
# downloads to <dest>.tmp, verifies sha256, atomically moves into place;
# aborts (non-zero) and removes the partial on mismatch or download failure.
fetch_verified() { ...; }
```

`stage_gemma_download` is refactored to call it, removing the duplicated logic.

## Publish flow

`ops/release/publish-db.sh <db-path> <version>` (operator-run):

1. **stamp** the DB (idempotent) via the stamper.
2. compute **sha256** + byte size.
3. `wrangler r2 object put pantryatlas-artifacts/db/recipes-<version>.db --file <db>`.
4. **generate** the per-version manifest + overwrite `recipes-latest.json`; upload both.
5. upload `db/ATTRIBUTION.txt`.
6. **print** the `RECIPES_DB_URL` + `RECIPES_DB_SHA256` lines to paste into
   `pi-bootstrap.sh`, and a reminder to bump the pins + commit.

Auth: `wrangler` runs via the operator's existing Cloudflare credentials (the
same path used for the marketing-site/PlatAtlas R2 work). If OAuth scope lacks R2
write, the operator supplies an R2-scoped API token — called out in the plan as a
prerequisite check (`wrangler r2 object put` dry attempt).

## Error handling

- **sha256 mismatch / download failure** in `fetch_verified` → abort non-zero,
  remove the partial `.tmp`, surface the expected-vs-actual hash. Never leave a
  corrupt `recipes.db` in place.
- **Re-run idempotency** — the `07-db-download.done` stamp short-circuits; deleting
  the stamp forces a re-fetch (matches every other bootstrap stage).
- **Offline** — `curl -fL --retry 3` then a clear error; bootstrap stops at this
  stage and can be resumed.
- **Missing wrangler / R2 auth** in publish → fail fast with the remediation
  (login or token), before touching the artifact.

## Licensing

The DB is derived from **RecipeNLG (CC-BY-NC-4.0)** — non-commercial, attribution
required. Because the artifact is downloadable independently of the app, the
attribution must travel with it: `db/ATTRIBUTION.txt` is uploaded alongside every
release. (The in-app `RECIPE_SOURCE_ATTRIBUTION` string already covers the
running app; this covers the standalone artifact.)

## Testing

- **Unit — stamper:** stamping a temp DB sets `user_version` and populates
  `_pantryatlas_db_meta`; re-stamping is idempotent; existing `recipes_meta` /
  `recipes_vec` queries still succeed afterward.
- **Unit — manifest generator:** emits valid JSON containing all required keys
  with correct types; `latest` mirrors the per-version manifest.
- **Unit — `fetch_verified`:** a sha256 mismatch aborts non-zero and leaves no
  file at the destination (drive with a tiny local fixture + a deliberately wrong
  hash; no network).
- **Integration (`pi_integration` / network-marked):** fetch
  `recipes-latest.json`, download the DB, sha256-verify against the manifest,
  open it, and assert `SELECT count(*) FROM recipes_meta == manifest.recipe_count`.

## Components summary

| Unit | Does what | Used how | Depends on |
|---|---|---|---|
| DB stamper | writes version/model metadata into a DB (idempotent) | called by publish script | sqlite3 (stdlib) |
| manifest generator | builds per-version + latest manifest JSON | called by publish script | stamper output, sha256, file size |
| `fetch_verified` (sh) | download + sha256-verify + atomic install | bootstrap stages | curl, sha256sum |
| `stage_db_download` (sh) | bootstrap stage that installs the DB | `pi-bootstrap.sh` main flow | `fetch_verified`, pinned URL+sha |
| `publish-db.sh` | operator-run release of a new DB to R2 | run by operator on release | stamper, manifest gen, wrangler |
