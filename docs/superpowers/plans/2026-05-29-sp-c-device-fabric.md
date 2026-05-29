# SP-C (slice 1) Device-Trust Fabric — Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Let a LAN device request to join the mesh, let the operator approve/reject it from the PWA, and issue a bearer token on approval — the trust spine future spokes enroll into.

**Architecture:** A `devices` table in `KitchenStore` (registry) + pure token helpers (`device_auth.py`: mint + sha256-hash) + HTTP routes (`enroll`/list/`approve`/`reject`/delete/`me`) on the navigator app + a dep-free avahi `.service` self-advertise + a minimal Preact "Devices" approval panel. Approval mints `secrets.token_urlsafe(32)`, stores only its sha256 hash, and returns the raw token once; `GET /devices/me` verifies a presented bearer by hashing it.

**Tech Stack:** Python 3.11+ · FastAPI · stdlib `secrets`/`hashlib`/`sqlite3` · avahi (service XML) · pytest + `fastapi.testclient` · Preact + `@preact/signals`.

**Spec:** [`../specs/2026-05-29-sp-c-device-fabric-design.md`](../specs/2026-05-29-sp-c-device-fabric-design.md) · **Vision:** [`../specs/2026-05-28-kitchen-mesh-vision-design.md`](../specs/2026-05-28-kitchen-mesh-vision-design.md)

---

> **Env (this Pi):** the repo `.venv` is a uv-venv with NO pytest. Run tests with **`PYTHONPATH=. /usr/bin/python3 -m pytest <target> -q`** (system 3.13). Lint: `ruff check .`. Frontend: `cd web && npm run build`. No new Python dep in this slice (`secrets`/`hashlib` are stdlib; avahi file is config). Commit each task with the given message.

## File structure

| File | Responsibility | Action |
|---|---|---|
| `pantryatlas/navigator/device_auth.py` | `mint_token` + `hash_token` (pure) | **Create** |
| `pantryatlas/store/kitchen.py` | `devices` table + device CRUD + `device_by_token_hash` | **Modify** |
| `pantryatlas/navigator/server.py` | `DeviceEnrollIn` + 6 device routes + `verify` via Header | **Modify** |
| `ops/avahi/pantryatlas.service` | mDNS self-advertise `_pantryatlas._tcp` | **Create** |
| `ops/systemd/install.sh` | install the avahi file + reload avahi | **Modify** |
| `tests/navigator/test_device_auth.py` | token mint/hash | **Create** |
| `tests/navigator/test_kitchen_store.py` | device CRUD tests | **Modify** |
| `tests/navigator/test_device_routes.py` | route + token-verify tests | **Create** |
| `tests/navigator/test_avahi_service.py` | XML well-formed + type/port | **Create** |
| `web/src/signals.ts` | `devices` state + fetch/approve/reject/remove | **Modify** |
| `web/src/components/DevicesPanel.tsx` | approval panel | **Create** |
| `web/src/pages/Navigator.tsx` | "Devices" toggle + render panel | **Modify** |
| `web/mock_backend.py` | canned device routes for headless | **Modify** |
| `web/verify_devices.mjs` | headless approval check | **Create** |
| `docs/navigator.md` | document the device fabric | **Modify** |

---

## Task 1: device_auth — token mint + hash

**Files:** Create `pantryatlas/navigator/device_auth.py`; Test `tests/navigator/test_device_auth.py`

- [ ] **Step 1: Write the failing test**

```python
# tests/navigator/test_device_auth.py
from __future__ import annotations

from pantryatlas.navigator.device_auth import mint_token, hash_token


def test_mint_token_is_unique_and_urlsafe():
    a, b = mint_token(), mint_token()
    assert a != b
    assert len(a) >= 32
    assert all(c.isalnum() or c in "-_" for c in a)


def test_hash_token_is_deterministic_sha256_hex():
    h1 = hash_token("abc")
    h2 = hash_token("abc")
    assert h1 == h2
    assert len(h1) == 64 and all(c in "0123456789abcdef" for c in h1)
    assert hash_token("abc") != hash_token("abd")
```

- [ ] **Step 2: Run it to verify it fails**

Run: `PYTHONPATH=. /usr/bin/python3 -m pytest tests/navigator/test_device_auth.py -q`
Expected: FAIL — `ModuleNotFoundError: ... device_auth`

- [ ] **Step 3: Write the minimal implementation**

```python
# pantryatlas/navigator/device_auth.py
"""Bearer-token helpers for the device-trust fabric (pure, no I/O).

A device's raw token is minted once at approval and shown to the operator once;
only its sha256 hash is persisted. Verification hashes the presented bearer and
compares to the stored hash.
"""

from __future__ import annotations

import hashlib
import secrets


def mint_token() -> str:
    """Return a fresh URL-safe bearer token (~43 chars from 32 random bytes)."""
    return secrets.token_urlsafe(32)


def hash_token(raw: str) -> str:
    """Return the sha256 hex digest of a raw token (what we persist + compare)."""
    return hashlib.sha256(raw.encode("utf-8")).hexdigest()
```

- [ ] **Step 4: Run it to verify it passes**

Run: `PYTHONPATH=. /usr/bin/python3 -m pytest tests/navigator/test_device_auth.py -q`
Expected: PASS (2 passed)

- [ ] **Step 5: Commit**

```bash
git add pantryatlas/navigator/device_auth.py tests/navigator/test_device_auth.py
git commit -m "feat(navigator): device bearer-token mint + hash helpers"
```

---

## Task 2: KitchenStore devices registry

**Files:** Modify `pantryatlas/store/kitchen.py`; Test `tests/navigator/test_kitchen_store.py`

- [ ] **Step 1: Write the failing test**

```python
# append to tests/navigator/test_kitchen_store.py
def test_device_enroll_approve_verify_flow(tmp_path):
    store = KitchenStore(tmp_path / "kitchen.db")
    dev = store.enroll_device("Counter Pi", "sensor", kind="pi-cam", caps=["camera"])
    assert dev["status"] == "pending"
    assert dev["device_id"]
    assert "token_hash" not in dev          # never leaked
    assert dev["caps"] == ["camera"]
    # pending → not findable by token
    assert store.device_by_token_hash("deadbeef") is None
    # approve stores a hash; paired
    approved = store.approve_device(dev["device_id"], "hash123")
    assert approved["status"] == "paired" and approved["paired_at"]
    # findable by the exact hash, and only when paired
    found = store.device_by_token_hash("hash123")
    assert found is not None and found["device_id"] == dev["device_id"]
    assert found["last_seen"]               # verify bumped last_seen
    # list never leaks token_hash
    assert all("token_hash" not in d for d in store.list_devices())


def test_device_reject_and_remove(tmp_path):
    store = KitchenStore(tmp_path / "kitchen.db")
    dev = store.enroll_device("X", "compute")
    store.approve_device(dev["device_id"], "h")
    assert store.reject_device(dev["device_id"])["status"] == "rejected"
    assert store.device_by_token_hash("h") is None   # rejected token no longer verifies
    assert store.remove_device(dev["device_id"]) is True
    assert store.get_device(dev["device_id"]) is None
    assert store.reject_device("ghost") is None
    assert store.remove_device("ghost") is False
```

- [ ] **Step 2: Run it to verify it fails**

Run: `PYTHONPATH=. /usr/bin/python3 -m pytest tests/navigator/test_kitchen_store.py -k device -q`
Expected: FAIL — `AttributeError: ... 'enroll_device'`

- [ ] **Step 3: Write the minimal implementation**

Add a `devices` table to the `_DDL` string in `pantryatlas/store/kitchen.py` (after `off_cache`):

```sql
CREATE TABLE IF NOT EXISTS devices (
    device_id    TEXT PRIMARY KEY,
    name         TEXT NOT NULL,
    role         TEXT NOT NULL,
    kind         TEXT,
    caps_json    TEXT,
    status       TEXT NOT NULL DEFAULT 'pending',
    token_hash   TEXT,
    enrolled_at  TEXT NOT NULL,
    paired_at    TEXT,
    last_seen    TEXT
);
```

Add `import secrets` at the top of the file (next to `import json`). Add these methods to `class KitchenStore` (writes lock-guarded, reads lock-free — matching the existing pattern):

```python
    @staticmethod
    def _device_to_dict(row: dict[str, Any]) -> dict[str, Any]:
        # token_hash is deliberately NOT exposed
        return {
            "device_id": row["device_id"], "name": row["name"], "role": row["role"],
            "kind": row["kind"], "caps": json.loads(row["caps_json"]) if row["caps_json"] else [],
            "status": row["status"], "enrolled_at": row["enrolled_at"],
            "paired_at": row["paired_at"], "last_seen": row["last_seen"],
        }

    def enroll_device(self, name: str, role: str, kind: str | None = None,
                      caps: list[str] | None = None) -> dict[str, Any]:
        device_id = secrets.token_hex(8)
        now = _now_iso()
        with self._lock:
            self._conn.execute(
                "INSERT INTO devices (device_id, name, role, kind, caps_json, status, enrolled_at) "
                "VALUES (?,?,?,?,?, 'pending', ?)",
                (device_id, name, role, kind, json.dumps(caps) if caps else None, now),
            )
            self._conn.commit()
        return self.get_device(device_id)

    def get_device(self, device_id: str) -> dict[str, Any] | None:
        row = self._fetchone("SELECT * FROM devices WHERE device_id=?", (device_id,))
        return self._device_to_dict(row) if row is not None else None

    def list_devices(self) -> list[dict[str, Any]]:
        rows = self._fetchall("SELECT * FROM devices ORDER BY enrolled_at DESC")
        return [self._device_to_dict(r) for r in rows]

    def approve_device(self, device_id: str, token_hash: str) -> dict[str, Any] | None:
        with self._lock:
            cur = self._conn.execute(
                "UPDATE devices SET status='paired', token_hash=?, paired_at=? WHERE device_id=?",
                (token_hash, _now_iso(), device_id),
            )
            if not cur.rowcount:
                return None
            self._conn.commit()
        return self.get_device(device_id)

    def reject_device(self, device_id: str) -> dict[str, Any] | None:
        with self._lock:
            cur = self._conn.execute(
                "UPDATE devices SET status='rejected', token_hash=NULL WHERE device_id=?",
                (device_id,),
            )
            if not cur.rowcount:
                return None
            self._conn.commit()
        return self.get_device(device_id)

    def remove_device(self, device_id: str) -> bool:
        with self._lock:
            cur = self._conn.execute("DELETE FROM devices WHERE device_id=?", (device_id,))
            self._conn.commit()
            return bool(cur.rowcount)

    def device_by_token_hash(self, token_hash: str) -> dict[str, Any] | None:
        with self._lock:
            row = self._conn.execute(
                "SELECT device_id FROM devices WHERE token_hash=? AND status='paired'",
                (token_hash,),
            ).fetchone()
            if row is None:
                return None
            device_id = row[0]
            self._conn.execute(
                "UPDATE devices SET last_seen=? WHERE device_id=?", (_now_iso(), device_id)
            )
            self._conn.commit()
        return self.get_device(device_id)
```

- [ ] **Step 4: Run it to verify it passes**

Run: `PYTHONPATH=. /usr/bin/python3 -m pytest tests/navigator/test_kitchen_store.py -q`
Expected: PASS (all, incl. the 2 new device tests)

- [ ] **Step 5: Commit**

```bash
git add pantryatlas/store/kitchen.py tests/navigator/test_kitchen_store.py
git commit -m "feat(store): devices registry (enroll/approve/reject/verify)"
```

---

## Task 3: device routes + token verify

**Files:** Modify `pantryatlas/navigator/server.py`; Test `tests/navigator/test_device_routes.py`

- [ ] **Step 1: Write the failing test**

```python
# tests/navigator/test_device_routes.py
from __future__ import annotations

from pathlib import Path

import numpy as np
from fastapi.testclient import TestClient

from pantryatlas.pantry.models import Ingredient
from pantryatlas.store.kitchen import KitchenStore


def _resolver(raw): return Ingredient(canonical_name=raw.lower(), raw_text=raw)
def _embed(texts): return np.ones((len(texts), 8), dtype=np.float32)


class _FakeStore:
    def count(self): return 0
    def get(self, rid): return None
    def iter_overlapping(self, names): return []


def _client(tmp_path: Path) -> TestClient:
    from pantryatlas.navigator.server import create_app
    app = create_app(store=_FakeStore(), resolver=_resolver, embed_fn=_embed,
                     pantry_path=tmp_path / "pantry.json",
                     kitchen=KitchenStore(tmp_path / "kitchen.db"))
    return TestClient(app)


def test_enroll_list_approve_me_flow(tmp_path):
    client = _client(tmp_path)
    # enroll
    r = client.post("/navigator/devices/enroll",
                    json={"name": "Counter Pi", "role": "sensor", "kind": "pi-cam", "caps": ["camera"]})
    assert r.status_code == 201
    did = r.json()["device_id"]
    assert r.json()["status"] == "pending"
    # bad role rejected
    assert client.post("/navigator/devices/enroll", json={"name": "X", "role": "bogus"}).status_code == 422
    # list shows it, never leaks token_hash
    listing = client.get("/navigator/devices").json()
    assert any(d["device_id"] == did for d in listing)
    assert all("token_hash" not in d for d in listing)
    # approve → raw token once
    appr = client.post(f"/navigator/devices/{did}/approve")
    assert appr.status_code == 200
    token = appr.json()["token"]
    assert token and appr.json()["status"] == "paired"
    # the token authenticates /devices/me
    me = client.get("/navigator/devices/me", headers={"Authorization": f"Bearer {token}"})
    assert me.status_code == 200 and me.json()["device_id"] == did
    assert "token" not in me.json() and "token_hash" not in me.json()
    # subsequent list still never carries the raw token
    assert all("token" not in d for d in client.get("/navigator/devices").json())


def test_me_rejects_bad_or_missing_token(tmp_path):
    client = _client(tmp_path)
    assert client.get("/navigator/devices/me").status_code == 401
    assert client.get("/navigator/devices/me",
                      headers={"Authorization": "Bearer nope"}).status_code == 401
    assert client.get("/navigator/devices/me",
                      headers={"Authorization": "notbearer x"}).status_code == 401


def test_reject_and_delete(tmp_path):
    client = _client(tmp_path)
    did = client.post("/navigator/devices/enroll", json={"name": "X", "role": "compute"}).json()["device_id"]
    token = client.post(f"/navigator/devices/{did}/approve").json()["token"]
    assert client.post(f"/navigator/devices/{did}/reject").json()["status"] == "rejected"
    # rejected token no longer verifies
    assert client.get("/navigator/devices/me",
                      headers={"Authorization": f"Bearer {token}"}).status_code == 401
    assert client.delete(f"/navigator/devices/{did}").json()["deleted"] == did
    assert client.post(f"/navigator/devices/ghost/approve").status_code == 404
    assert client.delete("/navigator/devices/ghost").status_code == 404
```

- [ ] **Step 2: Run it to verify it fails**

Run: `PYTHONPATH=. /usr/bin/python3 -m pytest tests/navigator/test_device_routes.py -q`
Expected: FAIL — 404/405 (routes not defined)

- [ ] **Step 3: Write the minimal implementation**

In `pantryatlas/navigator/server.py`: ensure `Header` is imported from fastapi (change `from fastapi import FastAPI, File, HTTPException, UploadFile` to also include `Header`). Add the Pydantic model near the others (after `AddItemIn`/`CookIn`):

```python
class DeviceEnrollIn(BaseModel):
    """Body for POST /navigator/devices/enroll."""

    name: str
    role: str  # compute | sensor
    kind: str | None = None
    caps: list[str] | None = None
```

Add a module-level constant near the top (after `RECIPE_SOURCE_ATTRIBUTION`):

```python
_DEVICE_ROLES = ("compute", "sensor")
```

Add the routes inside `create_app` (after the barcode/pantry routes, before `return app`):

```python
    @app.post("/navigator/devices/enroll", status_code=201)
    def enroll_device(body: DeviceEnrollIn) -> dict[str, Any]:
        if body.role not in _DEVICE_ROLES:
            raise HTTPException(status_code=422, detail=f"role must be one of {list(_DEVICE_ROLES)}")
        device = _get_kitchen(app).enroll_device(body.name, body.role, body.kind, body.caps)
        return {"device_id": device["device_id"], "status": device["status"]}

    @app.get("/navigator/devices")
    def list_devices() -> list[dict[str, Any]]:
        return _get_kitchen(app).list_devices()

    @app.post("/navigator/devices/{device_id}/approve")
    def approve_device(device_id: str) -> dict[str, Any]:
        from pantryatlas.navigator.device_auth import hash_token, mint_token
        token = mint_token()
        device = _get_kitchen(app).approve_device(device_id, hash_token(token))
        if device is None:
            raise HTTPException(status_code=404, detail=f"No device '{device_id}'.")
        return {"device_id": device_id, "status": "paired", "token": token}

    @app.post("/navigator/devices/{device_id}/reject")
    def reject_device(device_id: str) -> dict[str, Any]:
        device = _get_kitchen(app).reject_device(device_id)
        if device is None:
            raise HTTPException(status_code=404, detail=f"No device '{device_id}'.")
        return {"device_id": device_id, "status": "rejected"}

    @app.delete("/navigator/devices/{device_id}")
    def delete_device(device_id: str) -> dict[str, str]:
        if not _get_kitchen(app).remove_device(device_id):
            raise HTTPException(status_code=404, detail=f"No device '{device_id}'.")
        return {"deleted": device_id}

    @app.get("/navigator/devices/me")
    def device_me(authorization: str | None = Header(default=None)) -> dict[str, Any]:
        from pantryatlas.navigator.device_auth import hash_token
        if not authorization or not authorization.lower().startswith("bearer "):
            raise HTTPException(status_code=401, detail="missing bearer token")
        token = authorization.split(" ", 1)[1].strip()
        device = _get_kitchen(app).device_by_token_hash(hash_token(token))
        if device is None:
            raise HTTPException(status_code=401, detail="invalid token")
        return device
```

> Note: FastAPI matches `/navigator/devices/me` against `/navigator/devices/{device_id}` only for the `{device_id}` *param* routes (approve/reject/delete use distinct methods/subpaths); `GET /navigator/devices/me` is a GET on a literal subpath and `GET /navigator/devices` is the list — no conflict. If a future GET `/navigator/devices/{id}` is added, declare `/devices/me` before it.

- [ ] **Step 4: Run it to verify it passes**

Run: `PYTHONPATH=. /usr/bin/python3 -m pytest tests/navigator/ -q`
Expected: PASS — the whole navigator suite (new device routes + everything pre-existing).

- [ ] **Step 5: Commit**

```bash
git add pantryatlas/navigator/server.py tests/navigator/test_device_routes.py
git commit -m "feat(navigator): device enroll/approve/reject/delete/me routes"
```

---

## Task 4: avahi self-advertise + install wiring

**Files:** Create `ops/avahi/pantryatlas.service`; Modify `ops/systemd/install.sh`; Test `tests/navigator/test_avahi_service.py`

- [ ] **Step 1: Write the failing test**

```python
# tests/navigator/test_avahi_service.py
from __future__ import annotations

import xml.etree.ElementTree as ET
from pathlib import Path

_REPO = Path(__file__).resolve().parents[2]


def test_avahi_service_advertises_pantryatlas():
    path = _REPO / "ops" / "avahi" / "pantryatlas.service"
    assert path.exists(), "avahi service file missing"
    root = ET.fromstring(path.read_text(encoding="utf-8"))
    assert root.tag == "service-group"
    svc = root.find("service")
    assert svc is not None
    assert svc.findtext("type") == "_pantryatlas._tcp"
    assert svc.findtext("port") == "8090"
    txts = [t.text for t in svc.findall("txt-record")]
    assert "role=hub" in txts


def test_install_sh_installs_avahi_service():
    install = (_REPO / "ops" / "systemd" / "install.sh").read_text(encoding="utf-8")
    assert "avahi/pantryatlas.service" in install
    assert "/etc/avahi/services" in install
```

- [ ] **Step 2: Run it to verify it fails**

Run: `PYTHONPATH=. /usr/bin/python3 -m pytest tests/navigator/test_avahi_service.py -q`
Expected: FAIL — file missing / install.sh lacks the lines

- [ ] **Step 3: Write the minimal implementation**

Create `ops/avahi/pantryatlas.service`:

```xml
<?xml version="1.0" standalone='no'?>
<!DOCTYPE service-group SYSTEM "avahi-service.dtd">
<service-group>
  <name replace-wildcards="yes">PantryAtlas on %h</name>
  <service>
    <type>_pantryatlas._tcp</type>
    <port>8090</port>
    <txt-record>role=hub</txt-record>
    <txt-record>schema=1</txt-record>
  </service>
</service-group>
```

Append to `ops/systemd/install.sh` (after the systemd unit install loop + `daemon-reload`, before the final echo). First read the script to match its variable style (`$UNIT_DIR` points at `ops/systemd`; derive the repo root from it):

```bash
# --- mDNS service advertisement (avahi) ---
AVAHI_SRC="$(dirname "$UNIT_DIR")/avahi/pantryatlas.service"
if [ -d /etc/avahi/services ] && [ -f "$AVAHI_SRC" ]; then
    install -m 644 "$AVAHI_SRC" /etc/avahi/services/pantryatlas.service
    systemctl reload avahi-daemon 2>/dev/null || true
    echo "Installed avahi service: PantryAtlas advertises _pantryatlas._tcp"
fi
```

(Verify `$UNIT_DIR` is the var the script uses for `ops/systemd`; if it's named differently, use that name so `$(dirname ...)/avahi/...` resolves to `ops/avahi`.)

- [ ] **Step 4: Run it to verify it passes**

Run: `PYTHONPATH=. /usr/bin/python3 -m pytest tests/navigator/test_avahi_service.py -q`
Expected: PASS (2 passed)

- [ ] **Step 5: Commit**

```bash
git add ops/avahi/pantryatlas.service ops/systemd/install.sh tests/navigator/test_avahi_service.py
git commit -m "feat(ops): advertise _pantryatlas._tcp via avahi service file"
```

---

## Task 5: frontend device data layer

**Files:** Modify `web/src/signals.ts`

- [ ] **Step 1: Append the device types + actions** (after the barcode helpers):

```typescript
export interface Device {
  device_id: string
  name: string
  role: string
  kind?: string | null
  caps?: string[]
  status: 'pending' | 'paired' | 'rejected'
  enrolled_at?: string
  paired_at?: string | null
  last_seen?: string | null
}

export const devicesPanelOpen = signal<boolean>(false)
export const devices = signal<Device[]>([])
/** The raw token from the most recent approval — shown ONCE in the UI, then cleared. */
export const lastIssuedToken = signal<{ device_id: string; token: string } | null>(null)

export async function fetchDevices() {
  try {
    const res = await fetch('/navigator/devices')
    if (res.ok) devices.value = await res.json()
  } catch {
    // keep existing
  }
}

export async function approveDevice(deviceId: string) {
  try {
    const res = await fetch(`/navigator/devices/${encodeURIComponent(deviceId)}/approve`, { method: 'POST' })
    if (res.ok) {
      const d = await res.json()
      lastIssuedToken.value = { device_id: deviceId, token: d.token }
      await fetchDevices()
    }
  } catch {
    // ignore
  }
}

export async function rejectDevice(deviceId: string) {
  try {
    await fetch(`/navigator/devices/${encodeURIComponent(deviceId)}/reject`, { method: 'POST' })
    await fetchDevices()
  } catch { /* ignore */ }
}

export async function removeDevice(deviceId: string) {
  try {
    await fetch(`/navigator/devices/${encodeURIComponent(deviceId)}`, { method: 'DELETE' })
    await fetchDevices()
  } catch { /* ignore */ }
}
```

- [ ] **Step 2: Build** — Run: `cd ~/pantryatlas/web && npm run build` — Expected: clean.
- [ ] **Step 3: Commit**

```bash
cd ~/pantryatlas && git add web/src/signals.ts
git commit -m "feat(web): device fabric data layer (fetch/approve/reject/remove)"
```

---

## Task 6: DevicesPanel + Navigator toggle

**Files:** Create `web/src/components/DevicesPanel.tsx`; Modify `web/src/pages/Navigator.tsx`

> Read `web/src/components/MealLog.tsx` (the meal-log section) + how `Navigator.tsx` wires the "Log" toggle (`showLog` signal + a top-bar button + a section). Mirror that for "Devices".

- [ ] **Step 1: Create the panel** (complete code):

```tsx
// web/src/components/DevicesPanel.tsx
import { h } from 'preact'
import { useEffect } from 'preact/hooks'
import { devices, fetchDevices, approveDevice, rejectDevice, removeDevice, lastIssuedToken } from '../signals'

export function DevicesPanel() {
  useEffect(() => { void fetchDevices() }, [])
  const list = devices.value
  if (list.length === 0) {
    return (
      <p data-devices-empty="true" style={{
        fontFamily: 'var(--font)', color: 'var(--md-sys-color-on-surface-variant)', padding: '12px 0',
      }}>
        No devices yet. A phone or sensor on your Wi-Fi can request to join here.
      </p>
    )
  }
  const token = lastIssuedToken.value
  return (
    <ul data-devices-panel="true" style={{ listStyle: 'none', display: 'flex', flexDirection: 'column', gap: '8px' }}>
      {list.map((d) => (
        <li key={d.device_id} data-device-row={d.device_id} style={{
          padding: '12px 16px', borderRadius: 'var(--md-sys-shape-corner-medium)',
          background: 'var(--md-sys-color-surface-container-low)', fontFamily: 'var(--font)',
          display: 'flex', flexDirection: 'column', gap: '8px',
        }}>
          <span style={{ color: 'var(--md-sys-color-on-surface)' }}>
            {d.name} · <span data-device-status={d.status} style={{ color: 'var(--md-sys-color-on-surface-variant)' }}>
              {d.role} · {d.status}
            </span>
          </span>
          {token && token.device_id === d.device_id && (
            <code data-token-reveal style={{
              fontSize: 'var(--md-sys-typescale-label-medium-size)',
              background: 'var(--md-sys-color-surface-container-highest)',
              padding: '6px 8px', borderRadius: 'var(--md-sys-shape-corner-small)', wordBreak: 'break-all',
            }}>
              Save this token on the device (shown once): {token.token}
            </code>
          )}
          <span style={{ display: 'flex', gap: '8px', flexWrap: 'wrap' }}>
            {d.status === 'pending' && (
              <button type="button" data-approve={d.device_id} onClick={() => approveDevice(d.device_id)}
                style={pillStyle('var(--md-sys-color-primary)', 'var(--md-sys-color-on-primary)')}>Approve</button>
            )}
            {d.status === 'pending' && (
              <button type="button" data-reject={d.device_id} onClick={() => rejectDevice(d.device_id)}
                style={pillStyle('transparent', 'var(--md-sys-color-on-surface-variant)')}>Reject</button>
            )}
            <button type="button" data-remove={d.device_id} onClick={() => removeDevice(d.device_id)}
              style={pillStyle('transparent', 'var(--md-sys-color-error)')}>Remove</button>
          </span>
        </li>
      ))}
    </ul>
  )
}

function pillStyle(bg: string, color: string): h.JSX.CSSProperties {
  return {
    minHeight: '36px', padding: '4px 14px', borderRadius: 'var(--md-sys-shape-corner-full)',
    background: bg, color, border: bg === 'transparent' ? '1px solid var(--md-sys-color-outline-variant)' : 'none',
    fontFamily: 'var(--font)', fontSize: 'var(--md-sys-typescale-label-medium-size)', cursor: 'pointer',
  }
}
```

- [ ] **Step 2: Wire the toggle + section into `Navigator.tsx`** — mirror the meal-log "Log" wiring: import `{ devicesPanelOpen }` + `{ DevicesPanel }`; add a "Devices" button in the top bar that flips `devicesPanelOpen.value`; render a collapsible section with `<DevicesPanel/>` when `devicesPanelOpen.value` is true (place it near the meal-log section).

```typescript
import { devicesPanelOpen } from '../signals'
import { DevicesPanel } from '../components/DevicesPanel'
```

- [ ] **Step 3: Build** — Run: `cd ~/pantryatlas/web && npm run build` — Expected: clean.
- [ ] **Step 4: Commit**

```bash
cd ~/pantryatlas && git add web/src/components/DevicesPanel.tsx web/src/pages/Navigator.tsx
git commit -m "feat(web): Devices approval panel + toggle"
```

---

## Task 7: headless verify + docs + final gates

**Files:** Modify `web/mock_backend.py`, `docs/navigator.md`; Create `web/verify_devices.mjs`

- [ ] **Step 1: Extend `web/mock_backend.py`** to serve the device routes against its `KitchenStore` (`POST /navigator/devices/enroll`, `GET /navigator/devices`, `POST .../{id}/approve` → mint+return a token via the real `device_auth` + `KitchenStore.approve_device`, `.../{id}/reject`, `DELETE`). Read the current mock_backend (KitchenStore-backed) and reuse `device_auth.mint_token`/`hash_token` so the approve path mirrors the real server. Keep existing routes intact.

- [ ] **Step 2: Create `web/verify_devices.mjs`** (model on `web/verify_loop.mjs`): build → spawn mock_backend on a tmp db → open the page in chromium → enroll a device via `page.evaluate(fetch POST /navigator/devices/enroll ...)` → open the Devices panel (set `devicesPanelOpen` or click the toggle) → assert `[data-device-row]` renders with `[data-device-status="pending"]` → click `[data-approve]` → assert `[data-token-reveal]` appears AND `GET /navigator/devices` shows the device `paired`. Print `DEVICES OK` / non-zero on failure. Document what's exercised (real approve→token-reveal via the panel).

- [ ] **Step 3: Document** in `docs/navigator.md`: the device-fabric routes (`enroll`/`devices`/`approve`/`reject`/`delete`/`me`), the approve→bearer-token (sha256-hash-stored, shown once) trust model, the `devices` table, and the avahi `_pantryatlas._tcp` advertisement. Note token *enforcement on spoke traffic* + peer *discovery* are SP-D; offline/HTTPS is a separate slice.

- [ ] **Step 4: Final gates** (paste results):

Run: `cd ~/pantryatlas && PYTHONPATH=. /usr/bin/python3 -m pytest tests/navigator/ -q` → all pass.
Run: `ruff check .` → clean.
Run: `cd web && npm run build` → clean.
Run: `node web/verify_devices.mjs` → `DEVICES OK`.

- [ ] **Step 5: Commit**

```bash
cd ~/pantryatlas && git add web/mock_backend.py web/verify_devices.mjs docs/navigator.md
git commit -m "test(web): headless device-approval verification + docs"
```

---

## Self-review (completed during planning)

- **Spec coverage:** token helpers (T1) · devices registry incl. token-hash-only + last_seen + never-leak (T2) · enroll/list/approve(token-once)/reject/delete/me + role validation + 401/404 (T3) · avahi self-advertise + install (T4) · approval UI + token-once reveal (T5, T6) · headless verify + docs (T7). Every spec section maps to a task. ✓
- **Security:** raw token returned only by `/approve`; `_device_to_dict` omits `token_hash`; tests assert `list`/`me` never carry `token_hash` or raw token; rejected/removed tokens stop verifying (T2, T3 tests). ✓
- **No placeholders:** complete code in every backend step; T6 panel is complete; T7 + the `Navigator.tsx`/`install.sh` wiring steps name exact insertion sites in existing files the implementer reads. ✓
- **Type consistency:** `mint_token`/`hash_token`; KitchenStore `enroll_device`/`get_device`/`list_devices`/`approve_device`/`reject_device`/`remove_device`/`device_by_token_hash` + `_device_to_dict`; route shapes `{device_id,status[,token]}`; `DeviceEnrollIn{name,role,kind?,caps?}`; frontend `Device`/`devices`/`fetchDevices`/`approveDevice`/`rejectDevice`/`removeDevice`/`lastIssuedToken`/`devicesPanelOpen` — all consistent across tasks. ✓
- **Env:** all tests under `/usr/bin/python3`; whole `tests/navigator/` run as the T3/T7 gate (regression); no new Python dep. ✓
- **Honest limit:** "real second device joins" is unit/TestClient-level (a request bearing the issued token) + a headless panel approve; live mDNS/`avahi-browse` is operator-side (T4 validates the XML only). Stated in the spec. ✓
