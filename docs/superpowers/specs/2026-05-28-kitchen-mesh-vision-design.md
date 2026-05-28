# Design — PantryAtlas Kitchen Mesh (north-star vision)

- **Date:** 2026-05-28
- **Status:** Approved (brainstorming) — vision doc; NOT directly implementable. Carves into sub-projects.
- **Scope:** The whole multi-device ecosystem. Each sub-project below gets its own spec → plan → build.
  The first slice (**SP-A — Loop Foundation**) is specced separately in
  [`2026-05-28-sp-a-loop-foundation-design.md`](./2026-05-28-sp-a-loop-foundation-design.md).
- **Grounding:** [`../research/2026-05-28-kitchen-mesh-grounding-brief.md`](../research/2026-05-28-kitchen-mesh-grounding-brief.md)
  (7-agent research workflow + 2 adversarial verdicts).
- **Builds on:** the LAN inference-provider registry (PR #4, merged) and the live-vision wiring
  (PR #3, open/unrun). Supersedes the placeholder plans in issues **#17** (Coral host) and **#18**
  (camera/sensor provider), which become sub-projects E and B/D below.

## Why this exists

PantryAtlas today is a single-screen kitchen server: list or photograph ingredients, get delicious
recipes ranked from what's on hand. This document defines where it grows next — into a **multi-device,
local-first kitchen mesh that closes the loop on food waste**, with delicious recipes always one tap
away.

The north-star, in the operator's words: *"close the loop on waste while having delicious recipes easy
to pull up."*

### The loop

```
        ┌─────────── IN ───────────┐
        │  barcode scan · shelf      │
        │  photo · manual add        │
        ▼                            │
   ┌─────────┐    MATCH      ┌──────────────┐
   │ PANTRY  │ ────────────▶ │  delicious    │
   │ (truth) │  expiring      │  recipes      │
   └─────────┘  first         └──────────────┘
        ▲                            │
        │   reconcile         OUT     ▼
        │  (rescan)       ┌────────────────────┐
        └──────────────── │ "I cooked this" →   │
                          │ soft-decrement +    │
                          │ dated cook-log      │
                          └────────────────────┘
```

### The open lane (prior-art positioning)

The market splits three ways and **nobody fuses what we will**:

- **Consumer waste apps** (NoWaste, CozZo, Samsung Food) *prove demand* but die on manual-entry drift
  and **cloud shutdowns** — Kitche retired after acquisition; CozZo is shutting down as its backend is
  decommissioned.
- **$3–4k smart fridges** (Samsung Bespoke "Vision Inside", LG ThinQ) *prove that passive-vision
  inventory is the wanted antidote* — but lock it behind cloud-tethered hardware with hard limits
  (~37 unobscured items, no freezer, no pantry/counter).
- **Self-hosted managers** (Grocy, Mealie, KitchenOwl, Tandoor) *own your data* but stop short: only
  Grocy has a real consume/stock loop (still *manually* triggered), only Mealie has the photo cook-log
  (with *no* stock model), and **none** have vision.

> **PantryAtlas's lane:** *smart-fridge passive-vision inventory for any kitchen — free, private, and
> durable (Pi-resident, immune to the cloud-death class) — fused with auto-deplete-on-cook and a rich
> cook-log, captured passively across a device mesh so no one person has to remember to log.*

This also fixes the **universal abandonment cause**: every prior tool dies on the double-entry problem
(every depletion must be hand-logged or stock drifts and trust collapses). Our truth model is the
antidote (below).

## Decisions locked (brainstorming)

| Decision | Choice | Rationale |
|---|---|---|
| North-star | Close the loop on food waste; delicious recipes one tap away | operator |
| Truth model | **Blend** — cooking soft-decrements; camera rescan reconciles to ground truth | tolerant of imperfect quantities; never depends on faithful manual logging |
| Scan modes | All modes (on-demand / scheduled / continuous), declared **per-device**, privacy-safest default | operator chose the full spectrum as the ceiling; manual = floor |
| Joining | mDNS auto-discovery + **approval gate**; broad device tent; manual-add as floor | operator |
| Cooking capture | Tiered — **tap-to-cook** primary, manual quick-log secondary, plate-photo flourish | tap-to-cook is nearly free and the only accurate decrement |
| Sensor architecture | **Unified device fabric; `compute` + `sensor` roles** | operator (Fork 1); honest "extend vs separate" answer |
| HTTP vs HTTPS | **Document both; decide when specced (SP-C)** | core loop works on HTTP; offline/installable PWA needs HTTPS |
| First slice | **SP-A — Loop Foundation, no vision/devices** | buildable & verifiable today; lands the shared data model everything needs |
| Pantry storage | **Migrate `pantry.json` → SQLite in SP-A** | mesh will have concurrent device writers; JSON read-modify-write races |

## Architecture — six pillars

### 1. Hub-and-spoke (the load-bearing decision)

The Pi 5 is the **hub**. The phone/PWA talks to **only** the Pi. The Pi proxies to every other device
(other Pis, the Coral, phones-as-cameras, ESP32-cams) over its own LAN backend.

This is the single highest-leverage decision because of browser security rules: an HTTPS page cannot
make active requests to plain-HTTP peers (mixed content), and Safari/iOS has no escape hatch
(Chrome 142's `targetAddressSpace` is Chrome-only). Routing all PWA→device traffic through one origin
**collapses an N-device cert-trust problem to one** and means **ESP32/Coral never have to be TLS
servers**. Corollary: serve the app *from the Pi* — a Local→Local transition is ungated by Local
Network Access, whereas loading the PWA from the public marketing origin would trip the LNA prompt.

**The host does all vision; nodes only capture-and-upload.**

### 2. Unified device fabric, two roles

One device registry is the shared fabric: device identity, mDNS discovery, approval/trust, health, and
a single "devices on your network" settings surface. On top of it, a device advertises one or more
**roles**:

- **`compute`** — the existing inference `Provider` protocol from PR #4 (`text` / `vision`
  capabilities, priority/fallback routing). A registered LAN box or the Coral lends compute.
- **`sensor`** — NEW: an upload-only artifact source. Carries a **scan mode**
  (`on-demand` / `scheduled` / `continuous`) and produces **inventory deltas** by handing images to
  the host's vision pipeline. It does **not** run inference itself.

A device can hold **both** roles — a Coral board or a spare phone is a modest `compute` provider *and*
a `sensor` via its camera. The young `pantryatlas/inference/` registry (PR #4) refactors to sit under
this fabric; the inference registry becomes the `compute`-role view.

### 3. Discovery is the hub's job; trust is a bearer token

- The Pi runs `python-zeroconf` `ServiceBrowser`, discovers `_pantryatlas._tcp.local` peers, dedupes
  and persists a candidate list, and exposes `GET /devices` returning `pending | paired | rejected`.
- A browser/PWA **cannot** enumerate mDNS services, so the **PWA renders the approval gate** over the
  hub's list. Discovery = hub responsibility; approval = UI responsibility.
- **mDNS TXT records are advisory hints, never authorization** — advertisement is unauthenticated and
  spoofable. TXT carries `role` / `caps` / `scan_mode` / `schema-version` / `device-id` /
  `friendly-name` as *untrusted claims shown plainly*. Authorization comes **only** from pairing,
  which mints a **bearer token**; all later calls authenticate by token, not by mDNS identity. Reuse
  the bearer-token pattern already running on this Pi (`robot-md enable-dispatch`).
- **Pairing UX must not re-trigger HTTPS:** in-PWA QR scanning uses `getUserMedia` (secure-context →
  forces HTTPS). Prefer a hub/device-*displayed* short code the operator types, or a printed sticker
  scanned with the *native* camera app. Headless nodes (ESP32/old-Pi) get an out-of-band,
  provision-time enrollment path.
- Plan `avahi`/:5353 coexistence up front — this Pi already runs `avahi-daemon`.

### 4. Inventory pipeline is barcode-FIRST and degrades gracefully

The strongest grocery primitive is not a model. Tiers, in order, each falling through to the next:

1. **`barcode → Open Food Facts`** (always) — pyzbar/zbar on Pi CPU + a free, keyless OFF lookup
   returns the *exact* product and its *full ingredient list* at ~100% accuracy for covered packaged
   goods. Cache responses in local SQLite for offline repeats. This is the only path that yields a
   real ingredient list.
2. **Hailo-8 CNN produce detector** (if the HAT is present) — a fixed-vocabulary YOLO-class detector
   compiled to a `.hef` for fast produce / common-item detection. *Custom HEFs must be built on a
   separate x86_64 box (~32 GB RAM) + calibration set; the Pi only runs pre-compiled HEFs.*
3. **Gemma 4 E4B shelf-parse** (always) — flexible, open-vocabulary, but **CPU-bound and slow
   (~minutes/image)**. Run async; mirror the v0.2 paint-then-refine UX. **Gemma never offloads to the
   Hailo-8** (that accelerates CNNs only; VLMs are the Hailo-10H's domain).
4. **LAN open-vocab detector / fast VLM** (optional) — OWLv2 / Grounding DINO / YOLO-World on a
   registered `compute` provider. Not Pi-CPU or Hailo-8 viable.

Vision only carries produce, loose items, and leftovers. For packaged crops with an occluded barcode,
fall back to packaging OCR + OFF text search. Set honest accuracy expectations in copy/telemetry
(barcode ~exact; vision lower and OOD vs. clean benchmarks). Keep a human-in-the-loop confirm before
any ledger mutation.

### 5. Sensor nodes split by power, not preference

Identical **upload-only node contract** across all hardware: *on trigger → wake → Wi-Fi → resolve
`pantryatlas.local` via mDNS → capture one JPEG → HTTP POST to a single host ingest endpoint (tagged
node-id + location + timestamp) → sleep.* The host does all vision, so node hardware is interchangeable.

- **Powered scan station** (outlet nearby): a spare **phone wins decisively** — autofocus, HDR,
  low-light, ~zero firmware. Best single scanner; doesn't scale to one-per-shelf.
- **Battery + door/PIR-triggered in-cabinet node:** an **ESP32-class cam is the only candidate** (a
  phone can't deep-sleep to µA). Prefer the **M5Stack Timer Camera** (ESP32 + OV3660 3 MP + RTC 2 µA
  sleep + battery + built-in HTTP upload) over the brownout-fragile bare AI-Thinker ESP32-CAM. Best
  trigger: a magnetic reed switch firing on door-*close*, with a periodic timer fallback.
- Old Pis make fine powered scan stations or inference spokes but have no true low-power sleep
  (~120 mA floor) — plugged-in only.

### 6. Coral's honest place (from the adversarial verdict — *mixed, high-confidence*)

- The Coral SL2610 **cannot** host the Gemma 4 E4B brain (~5 GB at Q4 vs ≤2 GB DDR4). It is a
  **sensor + modest-compute node that borrows a LAN brain** via the PR #4 registry, falling back to a
  small onboard model when no helper is reachable.
- **Onboard Gemma 3 270M (~0.5 GB) is the always-on default**, not a hard ceiling — it's the only LLM
  with a validated Coral-NPU path (Torq). A **Gemma 3 1B Q4** upgrade *might* fit the 2 GB SKU **if
  embeddings are precomputed at ingest** (the recipe DB is static, so the bge-m3 embedder need not be
  resident at query time), **but runs CPU-only on the dual A55** — a slow optional upgrade, not
  baseline. (Hardware-gated; never observed — see spikes.)
- **Packaging:** prefer a **lean Astra image (`astra-core`/`astra-tiny`) + a Yocto meta-layer recipe**
  for the Python/FastAPI app, *not* the RAM-heavy `astra-media-oobe` Docker image (Wayland+Chromium+
  Docker burns the RAM the model needs). Storage is a non-issue (16 GB+ eMMC; bake the 238 MB DB in or
  fetch on first boot).
- **Wording note:** Synaptics' "offload" means CPU→NPU on-chip; the LAN-peer mesh is *our* design, not
  Synaptics-prescribed. Don't imply Coral borrows a peer natively.

## Data-model evolution

The blend truth-model and the waste loop need three things (full SQLite schema in the SP-A spec):

1. **Pantry item gains a confidence/provenance axis** (forward-compatible — cameras fill these later):
   `state` (`present | low | used_up` — coarse and forgiving, because portion-precision kills the
   feature), `confidence` (0..1 — cooking lowers it, an observation raises it; *this is the blend*),
   `last_observed_at` (drives "stale — rescan?" nudges), `source` (provenance:
   `manual | barcode | vision:<device-id> | cook`), `added_at` / `updated_at`.
2. **`CookEvent`** (append-only) — `{recipe_id?, dish_name, servings, cooked_at, photo?, rating?,
   notes?, consumed:[{canonical_name, coarse_amount}], source}`. Tapping **"I cooked this"** does ONE
   atomic thing: append the dated timeline entry AND soft-decrement the consumed ingredients. This is
   the Grocy×Mealie fusion nobody ships.
3. **`InventoryEvent` ledger** (append-only) — `{ts, canonical_name, change_type
   (add/observe/consume/discard/expire/adjust), source, device_id?}`. The honest truth-of-record that
   powers waste analytics and, later, multi-device reconciliation. The pantry is the *materialized
   current view*; the ledger is the *truth of record*.

**Storage:** mutable user state (pantry + events + meals) moves to a new SQLite DB
(`~/.pantryatlas/kitchen.db`, plain tables — no sqlite-vec, so this Pi's Python 3.11 runs it fine),
separate from the static `recipes.db`. Migrating the pantry off `pantry.json` now lands the
concurrent-write-safe substrate the multi-device mesh requires (cameras/devices writing inventory
deltas would race on a JSON file).

## Sub-project roadmap

Each is an independent spec → plan → build cycle. Sequencing reflects value × risk × hardware
availability.

| SP | Scope | Gating prerequisite | Order |
|---|---|---|---|
| **A — Loop Foundation** ⭐ | SQLite pantry + event ledger + cook-log; tap-to-cook→soft-decrement; meal-log timeline; expiry/"running-low" nudges; coarse consume ("used up / half left / threw away"); light waste analytics; manual edits | none — **buildable & verifiable on the Pi today** | **FIRST (specced)** |
| B — Barcode + photo inventory | `barcode → OFF → exact item + ingredient list` (cached); then manual snap-photo → host Gemma vision → inventory | photo path needs **host-vision bootstrap** (PR #3 mmproj, currently unrun/503) + OV-cam legibility spike. **Barcode part has no vision dep** — can ship first | next |
| C — Mesh fabric | `_pantryatlas._tcp` discovery on hub + `/devices` approval gate + bearer-token pairing + hub-and-spoke proxy; inference registry refactors under the unified fabric. **Decide HTTP-vs-HTTPS here** | none (Pi-side) | after B |
| D — Sensor nodes | Upload-only node contract + host ingest endpoint; phone scan-station first, then M5Stack ESP32 door-triggered node; multi-camera conflict reconciliation | builds on C | after C |
| E — Coral host (#17) | Lean Astra image + Yocto recipe; 270M onboard `compute` provider; borrows LAN brain; onboard cam = `sensor` node | **board arriving** + 1B-Q4-fit spike | when hardware lands |
| F — Flourishes | Plate-photo → dish-name → confirm-only decrement; Hailo-8 CNN produce detector; LAN open-vocab/VLM provider; in-browser phone vision (experimental) | various | last |

### Empirical spikes (cross-cutting — gate the hardware bets)

These are **decided by hardware, not by more searching**. Run before committing the dependent SP:

- **OV2640/OV3660 label legibility** for Gemma at 20–40 cm under real cabinet/fridge light → decides
  whether ESP32 nodes deliver text-level inventory or only coarse change-detection (gates SP-D ESP32).
- **Gemma 4 E4B image latency on *this* Pi 5** (with vs. without an idle Hailo HAT) — the ~2 min/image
  figure is extrapolated (gates SP-B photo UX).
- **Gemma 3 1B Q4 fit on the 2 GB Coral SKU** after boot, embeddings precomputed (gates SP-E upgrade).
- **M5Stack Timer Camera battery life** in the door-reed→WiFi→POST→sleep pattern (gates SP-D ESP32).
- **iOS in-browser VLM viability** (transformers.js OOM crash #1242 still open) (gates SP-F experimental).
- **Router DNS-rebinding / multicast filtering** that could break `.local` / mDNS on the operator's
  network (gates SP-C).

## Privacy & trust posture

Local-first is a hard constraint: barcode decode, OFF cache, Hailo CNN, and Gemma all run on the LAN;
the only network call is the OFF lookup (cacheable; OFF data is bulk-downloadable for fully-offline
operation). No cloud image upload, ever. **No facial-image gathering** — kitchen scenes may include
people; scope vision to shelves/products and retain only what the operator keeps. Every camera device
declares its scan mode; default is the privacy-safest (on-demand). Trust is earned only by explicit
operator approval → bearer token; mDNS claims grant nothing.

## Confidence tiering (what we're sure of vs. not)

- **Confident:** barcode-first; hub-and-spoke; Gemma is CPU-bound on the Pi forever; mDNS needs
  token auth + hub-side discovery; core loop works on HTTP; Coral must borrow a brain; manual-logging
  drift is the universal killer; dish→quantities is lossy (confirm-only); ESP32 (M5Stack) for battery
  nodes.
- **Uncertain:** real-world plate-photo accuracy; whether waste journaling changes behavior; exact
  edge-VLM CPU latency; glare-free illumination scheme; multi-camera conflict-reconciliation strategy.
- **Needs-hardware-to-confirm:** the six spikes above.

## Relationship to existing work

- **PR #4 (merged)** — LAN inference-provider registry → becomes the `compute`-role view under the
  unified fabric (Pillar 2). No rework of its routing/fallback; a refactor to sit under shared
  device identity/discovery (SP-C).
- **PR #3 (open, unrun)** — live Gemma vision (mmproj). The host-vision bootstrap it represents is the
  **prerequisite for SP-B's photo path**; nothing in SP-A depends on it.
- **Issue #17** → SP-E (Coral host). **Issue #18** → SP-B (artifact provider, photo→inventory) + SP-D
  (sensor nodes). Update both issues to point here.

## References

See the [grounding brief](../research/2026-05-28-kitchen-mesh-grounding-brief.md) for the full
primary-source list (Open Food Facts, Gemma 3, Hailo, SKU-110K, Food-101/Inverse-Cooking,
python-zeroconf, MDN secure contexts, Chrome LNA, Plex/mkcert, M5Stack, Grocy/Mealie, Samsung Bespoke,
Kitche).
