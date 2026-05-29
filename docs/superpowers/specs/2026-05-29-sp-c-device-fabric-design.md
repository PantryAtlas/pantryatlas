# Design — SP-C (slice 1): Device-Trust Fabric (enroll → approve → bearer token)

- **Date:** 2026-05-29
- **Status:** Approved (brainstorming) — ready for implementation planning
- **Parent vision:** [`2026-05-28-kitchen-mesh-vision-design.md`](./2026-05-28-kitchen-mesh-vision-design.md) (SP-C = "Mesh fabric")
- **Builds on:** SP-A (`KitchenStore`, lazy `_get_kitchen`) + SP-B — both merged to `main`.
- **Scope:** The device-trust **fabric only**, over HTTP. The machinery that future spokes (SP-D sensor nodes, SP-E Coral) enroll into and authenticate with.

## Goal

Let a device on the LAN **request to join** the PantryAtlas mesh, let the operator **approve or reject** it from the PWA, and on approval issue a **bearer token** the device uses to authenticate. This is the trust spine of the whole mesh: discovery is convenience, but **authorization comes only from operator approval → token** (mDNS claims grant nothing).

## What's in this slice vs deferred (and why)

The fabric's trust + registry works entirely over **HTTP enrollment**, so it is fully `TestClient`-verifiable on the Pi today — independent of mDNS *and* of HTTPS.

**In scope:** device registry (`devices` table) · `POST /navigator/devices/enroll` (→ pending) · `GET /navigator/devices` · approve (mints token) / reject / delete · `GET /navigator/devices/me` (a device verifies its own token) · a token mint/hash/verify helper · a minimal "Devices" approval panel in the PWA · an avahi `.service` file so the hub advertises `_pantryatlas._tcp` (dep-free; avahi already runs as `robot.local`).

**Deferred (with reason):**
- **Peer *discovery*-browsing** (`python-zeroconf` browsing `_pantryatlas._tcp`) → **SP-D** — there are no spokes to discover until sensor nodes exist; building it now shows no value and adds a dep + avahi-coexistence handling.
- **Token *enforcement* on real spoke traffic** → **SP-D** — define `verify_device_token` now (exercised via `/devices/me`), enforce it on the ingest/proxy routes when spokes land.
- **Offline/installable PWA over HTTPS** → its own later slice — hub-and-spoke has the PWA talk only to the Pi, and slice 1 has no spokes for it to reach, so HTTPS does **not** gate this fabric. (The deferred vision decision can wait for the service-worker slice.)
- **Unifying the existing inference-provider registry (PR #4, `/navigator/providers`) under this fabric** → a later refactor; keep them separate for now (no collision: `/navigator/devices` vs `/navigator/providers`).

**Honest limit:** a *real second device* joining can't be exercised in CI. The full **enroll → approve → token → authenticated `/devices/me`** round-trip IS verifiable via `TestClient` (a "virtual device" = a request presenting the issued token). mDNS self-advertise is config, validated by parsing the `.service` XML; a live `avahi-browse` smoke is operator-side (reloading system avahi in tests is too intrusive).

## Decisions locked

| Decision | Choice |
|---|---|
| Trust | Operator **approve → bearer token**; mDNS TXT = unauthenticated hints only |
| Token storage | Mint `secrets.token_urlsafe(32)`; store only **`sha256` hash** in `devices`; return raw **once** on approve (API-key pattern); verify by hashing the presented bearer |
| Registry store | New `devices` table in `kitchen.db` (KitchenStore — concurrent-safe, established mutable-state home) |
| Advertise | avahi `.service` file (`_pantryatlas._tcp`, :8090) — dep-free; avahi already running |
| Transport | HTTP (status quo); HTTPS/offline deferred — does not gate this slice |
| Discovery-browse / token-enforcement | Deferred to SP-D |

## Data flow

```
device → POST /navigator/devices/enroll {name, role, kind?, caps?}   → 201 {device_id, status:"pending"}
operator (PWA Devices panel) → GET /navigator/devices                → sees the pending device
operator → POST /navigator/devices/{id}/approve                      → 200 {device_id, status:"paired", token:"<RAW, shown ONCE>"}
   (server mints raw token, stores sha256(token) as token_hash, never the raw)
device stores the raw token; later authenticates:
device → GET /navigator/devices/me   (Authorization: Bearer <token>) → 200 {device...}  | 401 if unknown
operator → POST .../{id}/reject  → status:"rejected"   ·   DELETE .../{id} → revoke
```

## Components (small, focused units)

- **`pantryatlas/navigator/device_auth.py`** — pure token helpers: `mint_token() -> str` (`secrets.token_urlsafe(32)`), `hash_token(raw: str) -> str` (`hashlib.sha256` hexdigest). No I/O.
- **`KitchenStore`** (`pantryatlas/store/kitchen.py`) — add a `devices` table + methods (lock-guarded writes, lock-free reads, matching the existing split):
  - `enroll_device(name, role, kind=None, caps=None) -> dict` — insert `status="pending"` with a generated `device_id` (`secrets.token_hex(8)`), `enrolled_at`; returns the device dict (no token).
  - `list_devices() -> list[dict]` — all devices, **never** exposing `token_hash`.
  - `get_device(device_id) -> dict | None`.
  - `approve_device(device_id, token_hash) -> dict | None` — set `status="paired"`, `token_hash`, `paired_at`; return device or None if unknown.
  - `reject_device(device_id) -> dict | None`; `remove_device(device_id) -> bool`.
  - `device_by_token_hash(token_hash) -> dict | None` — paired device whose hash matches (the verify lookup); also bumps `last_seen`.
  - Table: `device_id PK, name, role, kind, caps_json, status, token_hash, enrolled_at, paired_at, last_seen`. (`role` constrained in the route to `compute|sensor`.)
- **`pantryatlas/navigator/server.py`** — Pydantic `DeviceEnrollIn{name: str, role: str, kind: str | None = None, caps: list[str] | None = None}` + routes:
  - `POST /navigator/devices/enroll` (201) — validate `role in {compute, sensor}` (422 else) → `enroll_device` → `{device_id, status}`.
  - `GET /navigator/devices` → `list_devices()` (token_hash stripped).
  - `POST /navigator/devices/{device_id}/approve` → mint raw token, `hash_token`, `approve_device`; 404 if unknown; 200 `{device_id, status:"paired", token: <raw>}`.
  - `POST /navigator/devices/{device_id}/reject` → 200 / 404.
  - `DELETE /navigator/devices/{device_id}` → `{deleted}` (idempotent-ish; 404 if absent is fine).
  - `GET /navigator/devices/me` — read `Authorization: Bearer <token>`; `verify_device_token` → 200 device | 401. (No token / malformed → 401.)
  - `verify_device_token(app, token) -> dict | None` helper = `device_by_token_hash(hash_token(token))`.
- **`ops/avahi/pantryatlas.service`** — avahi service XML advertising `_pantryatlas._tcp` on 8090 with TXT (`role=hub`, `schema=1`). `ops/systemd/install.sh` (or a sibling note) installs it to `/etc/avahi/services/` (`install -m 644`) + `systemctl reload avahi-daemon`.
- **Frontend (`web/`)** — `web/src/components/DevicesPanel.tsx` (collapsible section, mirrors the meal-log pattern): lists devices grouped by status with Approve/Reject/Remove; on approve, reveals the returned token **once** (copy-to-clipboard) with a "save this on the device" note. `signals.ts`: `devices` signal + `fetchDevices`/`approveDevice`(returns token)/`rejectDevice`/`removeDevice`. A "Devices" toggle in the top bar (like the Log toggle).

## Error handling

- Unknown `device_id` on approve/reject → **404**. Bad `role` on enroll → **422**.
- `/devices/me`: missing/malformed/`Bearer`-less header or non-matching token → **401** (never 500); constant-time-ish compare via hash equality.
- Token is returned **only** at approval; never in `GET /navigator/devices` or `/devices/me` (which returns the device record without the hash/token). Re-approve re-mints (rotation); the old token stops verifying.
- KitchenStore writes are lock-guarded (existing pattern); `devices` table created idempotently in `_DDL`.

## Testing strategy

- **Unit (system py3.13, plain sqlite):** `device_auth` mint uniqueness + hash determinism; KitchenStore device CRUD (enroll→pending, approve sets paired+hash+paired_at, `device_by_token_hash` finds only paired + bumps last_seen, reject, remove, `list_devices` never leaks `token_hash`).
- **Route tests** (duck-typed `_FakeStore` + real `KitchenStore`, as in `test_loop_routes.py`): enroll→201 pending; bad role→422; list; approve→200 raw token once + paired; `/devices/me` with that token→200, wrong/absent token→401, a rejected/removed device's token→401; reject; delete; unknown id→404. Assert `GET /navigator/devices` never contains `token_hash` or the raw token.
- **avahi `.service`:** a test parses `ops/avahi/pantryatlas.service` as XML and asserts the service type `_pantryatlas._tcp` + port 8090; assert `install.sh` references it.
- **Frontend:** `npm run build` clean; a headless or build-level check that the Devices panel renders pending devices + Approve issues the token reveal (mock_backend serves the devices routes against its KitchenStore).
- Gates: full `tests/navigator/` green, `ruff check .` clean, `npm run build` clean. No new Python dep (avahi file is config; `secrets`/`hashlib` are stdlib).

## Open questions (resolve in planning)

- **`/devices/me` is the only token-authenticated route in this slice** — confirm it's enough to prove the verify seam, or add a trivial authenticated echo. Lean: `/devices/me` suffices; SP-D adds real enforced routes.
- **Devices panel placement** — a top-bar "Devices" toggle vs folding into the existing "AI helpers" (providers) panel. Lean: separate "Devices" toggle now; unify with providers in the later refactor (keeps this slice small and avoids touching PR #4's panel).
- **avahi reload in `install.sh`** — `systemctl reload avahi-daemon` requires the file in place first; confirm the install order. Pure ops; no test impact (tests validate the XML only).
