# Grounding Brief — PantryAtlas Kitchen Mesh

> Provenance artifact. Synthesis of a 7-agent research workflow (4 research dimensions +
> 2 adversarial verification verdicts + synthesis) run 2026-05-28 to ground the
> [kitchen-mesh vision design](../specs/2026-05-28-kitchen-mesh-vision-design.md).
> Where a verdict and a raw finding diverge, the verdict (the later adversarial check) wins.

---

## 1. Executive grounding

- **Inventory is barcode-FIRST, vision-fallback — not a vision-everywhere mesh.** The strongest
  grocery primitive is not a model: a barcode decode (pyzbar/zbar on Pi CPU) + Open Food Facts
  lookup returns the *exact* product and its *full ingredient list* at ~100% accuracy for packaged
  goods — something no detector or VLM can recover from a photo of the box. Vision only carries
  produce, loose items, and leftovers. <https://openfoodfacts.github.io/openfoodfacts-server/api/tutorial-off-api/>
- **The truth model must never depend on faithful manual logging.** The universal, famous death of
  every prior tool (NoWaste, CozZo, even Grocy's manual "consume-recipe") is the double-entry
  problem: every depletion must be hand-logged or stock drifts, trust collapses, users abandon. This
  *validates* PantryAtlas's stated model — cooking soft-decrements, camera rescans reconcile — as the
  correct antidote.
- **The mesh spine is the HTTP-vs-HTTPS fork, not discovery.** mDNS discovery is the easy, solved
  part. The core camera→recipe loop works over plain HTTP-on-LAN because PantryAtlas uses
  file-capture, not `getUserMedia` (`web/src/pages/Navigator.tsx:504-506`). Only the service-worker
  (offline cache + Android install) needs HTTPS, which drags in cloudless cert trust.
- **Hub-and-spoke is the single highest-leverage decision.** The PWA speaks HTTPS to *only* the Pi
  hub; the Pi proxies to other Pis, the Coral, and ESP32-cams over its own LAN backend. This
  collapses an N-device browser-cert-trust problem (forced by mixed-content rules) to one origin, and
  removes any need for ESP32/Coral to be TLS servers.
- **All heavy compute leaves the Pi to a LAN brain; degrade in tiers.** barcode (always) → Hailo-8
  CNN detector (if HAT present) → Gemma 4 E4B on CPU (always, slow/async) → LAN open-vocab/VLM (if a
  provider is registered). The existing Coral LAN inference-provider registry (PR #4, merged) is the
  architecture slot for the brain — not new work.
- **The Hailo-8 accelerates CNNs only; Gemma stays CPU-bound forever.** Hailo-8 runs the YOLO family
  from its Model Zoo; transformer-decoder VLMs are the Hailo-10H's job. Do not plan to offload Gemma
  to the HAT. <https://hailo.ai/blog/bringing-generative-ai-to-the-edge-llm-on-hailo-10h/>
- **Open lane = fusion.** Grocy proves auto-deplete-on-cook; Mealie proves the dated photo cook-log;
  smart fridges prove passive-vision demand but lock it behind ~$3–4k cloud-tethered appliances
  (Samsung: ~37 unobscured items, no freezer). Nobody joins passive-vision inventory +
  auto-deplete-on-cook + a rich cook-log + local-first durability + multi-device. PantryAtlas is the
  first to fuse them.
- **Cloud food apps die; local-first is structurally immune.** Kitche retired post-acquisition; CozZo
  is shutting down because its cloud backend is decommissioned. A Pi-resident server is immune to that
  entire failure class — make durability a headline.

## 2. Camera → inventory

Pipeline order is the design, not a detail. Degrade gracefully:

| Tier | Mechanism | Where it runs | Accuracy expectation |
|---|---|---|---|
| 1 (always) | Barcode → Open Food Facts | Pi CPU, ms; cache OFF responses in local sqlite | ~Exact for covered packaged goods; the *only* path that yields a real ingredient list. Gaps: regional/store-brand, no produce. |
| 2 (if HAT) | Fixed-vocabulary CNN detector (YOLO-class) compiled to a Hailo-8 HEF | Hailo-8 | Fast produce / common-item detection. Good for the long-tail of barcode-less staples. |
| 3 (always) | Gemma 4 E4B shelf-parse | Pi CPU, ~minutes/image | Flexible, open-vocabulary, **slow** — async only. Noticeably lower than benchmarks; real shelves are OOD. |
| 4 (optional) | OWLv2 / Grounding DINO / YOLO-World / fast VLM | LAN box via Coral registry (PR #4) | High-accuracy open-vocab — but not Pi-CPU or Hailo-8 viable. |

**Phone: upload-to-host, not on-device.** Phone-uploads-photo-to-Pi is the **quality-superior
default**, not a fallback — the Pi runs Gemma 4 E4B, a strictly more capable VLM than any
browser-viable model (SmolVLM-256M). Phone in-browser WebGPU vision is **RESERVED/EXPERIMENTAL**
(see §7): it earns a slot only for host-*independence* (Pi down/unprovisioned/load-shedding), never
for accuracy, and iOS reliability is not there (open transformers.js OOM crash #1242, ~300 MB Safari
WASM ceiling). Target Android Chrome + iPadOS first if pursued at all.

Architecture facts that bind the build:

- **Detection ≠ recognition → two-stage design.** A class-agnostic localizer (SKU-110K-style) finds
  item regions; recognizing each crop is the brittle part. For packaged crops with an occluded
  barcode, fall back to **packaging OCR + OFF text search**.
- **Custom Hailo HEFs need a separate x86_64 Linux build box (~32 GB RAM) + a 200–1000-image
  calibration set.** The Pi only *runs* pre-compiled HEFs. Prefer a Model Zoo YOLO baseline to dodge
  unsupported-op surgery; ship the `.hef` pre-compiled, never built on-Pi.
- **UX around Gemma latency:** mirror the existing v0.2 fast-paint-then-refine pattern — paint a
  placeholder, run the parse async, refine in the background. Never design for real-time on CPU.
- **Privacy/offline:** every tier runs on the LAN; the only network call is OFF (cacheable,
  bulk-downloadable for fully-offline operation).

## 3. Completed-dish capture

Tap-to-cook is the real path; plate-photo is the garnish.

- **Tap-to-cook (realistic, primary):** user marks a recipe "made it" → atomically (a) write a dated
  timeline event (photo, rating, notes — Mealie proves users want this) AND (b) deduct the recipe's
  *estimated* ingredients from inventory. This is the one event that fuses the two proven patterns
  nobody has joined.
- **Plate-photo (low-confidence FLOURISH only):** Gemma (or a Food-101-class classifier) *names* the
  dish, then maps the name to a recipe already in the local DB to suggest a plausible
  consumed-ingredient set. Food-101 SOTA ~99.5% is a **clean-benchmark ceiling, not field accuracy** —
  real plates are mixed, garnished, OOD, often outside the class set.
- **Dish → consumed quantities is fundamentally lossy.** A photo cannot reveal hidden ingredients
  (oil, salt, stock), exact amounts, or eaten-vs-plated. Inverse Cooking predicts ingredient
  *presence*, not quantity. **Never auto-decrement the ledger from a plate photo** — present it as a
  one-tap-confirm suggestion with editable quantities, always human-in-the-loop before mutation.
- **Make consume actions coarse and forgiving:** "used up / half left / threw away." NoWaste's
  "partial"-portion complaint shows portion-precision kills the feature.

## 4. Mesh fabric

Discovery + trust:

- **Discovery is a hub job; approval is a UI job.** A browser/PWA cannot do mDNS enumeration. The Pi
  hub runs `python-zeroconf` `ServiceBrowser`, dedupes/persists a candidate list, and exposes
  `GET /devices` (pending|paired|rejected); the PWA renders the approval gate.
- **mDNS TXT records are advisory hints, never authorization.** Advertisement is unauthenticated and
  spoofable. Advertise `_pantryatlas._tcp.local` with TXT for role / caps / scan_mode / schema-version
  / device-id / friendly-name — all *untrusted claims* shown plainly. Authorization comes only from
  pairing → a **bearer token**; all later calls authenticate by token, not mDNS identity. Reuse the
  bearer-token pattern already on this Pi (`robot-md enable-dispatch`).
- **Pairing UX must not re-trigger HTTPS.** In-PWA QR scanning uses `getUserMedia` → secure context →
  forces HTTPS. Prefer device/hub *displays* a short code the operator types in, or a printed sticker
  scanned with the *native* iOS camera app.
- **If you choose HTTPS, budget the iOS CA-trust friction explicitly** (mkcert root install + the
  separate, bug-prone *Certificate Trust Settings* full-trust toggle). Hub-and-spoke makes this a
  one-time, one-device (the Pi's) step. **Exclude cloud TLS tricks** (Plex `.plex.direct`, Nabu Casa
  need internet + public DNS) and **Chrome-142-only** `targetAddressSpace` (absent on iPhone/Safari).
  Serve the app *from the Pi*: Local→Local is ungated by Local Network Access; the public marketing
  origin would trip the LNA prompt.
- **Plan avahi/:5353 coexistence up front** — this Pi already runs `avahi-daemon`; decide share-socket
  vs D-Bus vs single-responder before implementation to avoid a silent "never advertises" failure.

Device classes — two roles, pick hardware per role:

- **Compute providers:** Pi 5 hub (host, runs all vision + brain orchestration); LAN inference box /
  Coral as registered providers behind the hub (§5). Old Pis can be powered scan stations or inference
  spokes — no true low-power sleep (~120 mA floor), so plugged-in only.
- **Sensor nodes (upload-only): ESP32-vs-old-phone is decided by power, not preference.**
  - **Powered scan station** (USB nearby): **old phone wins decisively** — autofocus, HDR, low-light,
    near-zero firmware (just an app). Best *single* scanner; does not scale to one-per-shelf.
  - **Battery + door/PIR-triggered wireless node** (in-cabinet, no outlet): **ESP32 class is the ONLY
    candidate** — a phone cannot deep-sleep to µA. Recommend the **M5Stack Timer Camera** (ESP32 +
    OV3660 3 MP + RTC 2 µA sleep + battery + built-in HTTP upload) over the bare AI-Thinker ESP32-CAM,
    whose ~4 mA sleep and brownout fragility make it a poor battery node.
  - **Node contract (identical across hardware):** on trigger → wake, WiFi, resolve `pantryatlas.local`
    via mDNS, capture one JPEG, HTTP POST to one host ingest endpoint (tagged node-id + location +
    timestamp), sleep. **Host does ALL vision.** This makes ESP32/phone/Pi nodes interchangeable.
  - **Best trigger:** magnetic reed switch on the door, capture on door-*close*, with a periodic timer
    fallback (e.g. 1/12 h) for silent changes.

## 5. Coral's place

Per the verdict (MIXED, high confidence): the architecture's conclusion holds — soften the fallback
wording.

- **Coral cannot host Gemma 4 E4B** (~5 GB at Q4 vs ≤2 GB DDR4). Heavy work *must* go to a LAN peer
  (the §4 brain). The board is a **sensor + modest-compute node that borrows a LAN brain.**
- **Frame the 270M as the DEFAULT, not a hard ceiling.** Gemma 3 270M (~0.5 GB) is the always-on local
  fallback and the *only* LLM with a validated Coral NPU path (Torq). A **Gemma 3 1B Q4** local upgrade
  *borderline-fits the 2 GB SKU IF embeddings are precomputed at ingest* (the recipe DB is static, so
  the bge-m3 embedder need not be resident at query time) — **but it runs CPU-only on the dual A55 with
  no NPU accel**, so it is a slow optional upgrade, not baseline. On the 1 GB SKU even 270M + embedder
  is tight.
- **Packaging tension is real:** a Docker runtime exists only on the RAM-heavy `astra-media-oobe` image
  (Wayland+Chromium+Docker burns the RAM the model needs); lean `astra-core`/`astra-tiny` frees RAM but
  lacks a container runtime → **prefer lean image + a Yocto meta-layer recipe** to ship the
  Python/FastAPI app. Storage is a non-issue (16 GB+ eMMC; bake the 238 MB DB in or fetch on first
  boot).
- **Wording correction:** Synaptics' "offload" means CPU→NPU *on-chip*; the LAN-peer mesh is
  PantryAtlas's design, not Synaptics-prescribed. Do not imply Coral offloads to a peer natively.
- **Hardware-gated:** no public benchmark of any LLM >270M on this board; the 1B-fits claim is
  capacity-based, not observed; free-RAM-after-boot per image variant is unmeasured (see §7).

## 6. Prior-art positioning + differentiation

The market splits three ways: consumer waste apps (NoWaste, CozZo, Samsung Food/Whisk) that *prove
demand* but die on manual-entry drift and cloud shutdowns; smart-fridge vision (Samsung Bespoke
"Vision Inside," LG ThinQ) that *proves passive camera inventory is the desired antidote* but locks it
behind $3–4k cloud-tethered appliances with hard limits (~37 unobscured items, no freezer, no
pantry/counter); and self-hosted managers (Grocy, KitchenOwl, Mealie, Tandoor) that *own your data*
but each stop short — only Grocy has a real consume/stock loop (and its trigger is still *manual*),
only Mealie has the photo cook-log (with *no* stock model), and none have vision. **PantryAtlas's open
lane is the fusion none of them attempt:** on-device Gemma vision automates the passive capture that
smart fridges charge thousands for, while staying free, private, durable (Pi-resident, immune to the
Kitche/CozZo cloud-death class), and — uniquely — multi-camera/multi-device, which directly attacks
the "single diligent updater" failure that sinks every single-instance and single-app tool.

> One sentence: *smart-fridge passive-vision inventory for any kitchen, free and local, fused with
> auto-deplete-on-cook and a rich cook-log, captured passively across a mesh so no one person has to
> remember to log.*

## 7. Confidence tiering

**CONFIDENT (high-confidence, primary-sourced):**

- Barcode + OFF is the strongest grocery primitive; returns exact product + ingredient list on Pi CPU.
- Open-vocab transformer detectors (OWLv2/Grounding DINO/YOLO-World) are not Pi-CPU or Hailo-8 viable → LAN box.
- Hailo-8 accelerates CNNs only; Gemma is permanently CPU-bound on the Pi.
- HEF compilation needs a separate x86_64 box (~32 GB RAM) + calibration set; Pi only runs HEFs.
- mDNS is the right discovery substrate but unauthenticated/spoofable → token-based authorization; browser can't do mDNS → hub discovers, UI approves.
- Core camera loop works over plain HTTP (file-capture, `Navigator.tsx:504-506`); only the service worker needs HTTPS; hub-and-spoke collapses N cert problems to one.
- Coral cannot host E4B → must borrow a LAN brain; 270M is the validated-NPU local default.
- Manual-logging drift is the universal abandonment cause; cloud food apps die (Kitche/CozZo); Grocy/Mealie prove the two patterns to fuse.
- Dish→consumed-quantities is fundamentally lossy → confirm-only, never auto-decrement.
- For battery/triggered nodes, ESP32 is the only viable class; M5Stack Timer Camera beats bare AI-Thinker.

**UNCERTAIN (medium-confidence / single-source / behavioral):**

- Real-world plate-photo dish classification accuracy (benchmarks are clean/OOD; field number unknown).
- Whether waste-tracking/journal patterns actually change behavior vs. just guilt users (check LOWINFOOD's CozZo assessment before investing UX).
- Edge-VLM CPU latency framing (~1–2 min/image) — single blog source, extrapolated from Qwen2.5-VL-3B.
- Illumination scheme for glare-free legible frames on glossy packaging without a battery penalty.
- Multi-camera/phone inventory conflict reconciliation strategy (LWW vs confidence-weighted vs human-on-conflict).

**NEEDS-HARDWARE-TO-CONFIRM (empirical spike required — not more searching):**

- **Can Gemma 4 E4B read grocery labels from a manually-defocused OV2640/OV3660 at 20–40 cm under real
  cabinet/fridge lighting?** This single result decides whether ESP32 nodes deliver text-level
  inventory or only coarse change-detection.
- **Gemma 4 E4B image latency on *this* Pi 5** (with vs. without an idle Hailo HAT) — the ~2 min figure
  is extrapolated.
- **Does a Gemma 3 1B Q4 actually fit the 2 GB Coral SKU after boot** with embeddings precomputed
  (embedder non-resident)? Capacity-based claim, never observed; no free-RAM-after-boot figure exists
  for any Astra image.
- **M5Stack Timer Camera real battery life** in the door-reed→WiFi→POST→sleep pattern (WiFi association
  dominates per-wake energy; vendor "1 photo/hour" is idealized).
- **iOS in-browser VLM viability** (transformers.js OOM crash #1242 still open; recheck before relying
  on any Android/iPad experimental slot).
- **Router DNS-rebinding protection / multicast filtering** that could break `.local` resolution or
  mDNS discovery on the operator's network.

## 8. Top design implications

1. **Build the inventory pipeline barcode-FIRST with explicit tiered degradation:** barcode+OFF
   (always) → Hailo-8 CNN (if HAT) → Gemma CPU async (always) → LAN open-vocab/VLM (if registered).
   Cache OFF responses locally for offline repeat scans.
2. **Adopt hub-and-spoke as the load-bearing mesh architecture:** PWA→HTTPS→Pi hub only; Pi proxies to
   all other devices over its LAN backend. Single highest-leverage decision; dissolves both the
   N-device cert problem and ESP32/Coral TLS-server pain.
3. **Document the HTTP-vs-HTTPS fork first, before discovery.** Decide whether offline/installable PWA
   (service worker) is a v1 requirement — that one answer picks the branch.
4. **Make the truth model passive-capture by default, hand-correction the exception.** Vision-on-cook
   and vision-on-discard capture depletion; periodic camera rescans reconcile against the
   recipe-estimate decrement. Never block on exact quantities; offer coarse states.
5. **Fuse cook-log and inventory into one atomic event:** tap-to-cook writes a dated photo/note
   timeline entry AND deducts the recipe's estimated ingredients — the differentiator nobody ships.
6. **Ship plate-photo as a confirm-only, low-confidence flourish** that names a dish and suggests a
   DB-recipe ingredient set; it must never mutate the ledger without one-tap operator confirmation.
7. **Treat mDNS TXT as hints, authorize via bearer tokens** (reuse `robot-md enable-dispatch`);
   discovery on the hub, approval in the UI; pairing UX avoids in-PWA QR. Give headless ESP32/old-Pi
   nodes an out-of-band flash/provision-time enrollment path.
8. **Split sensor nodes by power, not preference:** old phone for powered scan stations, M5Stack-class
   ESP32 for battery/door-triggered nodes; one identical upload-only node contract behind a single
   node-agnostic host ingest endpoint. Gate any ESP32 fleet on the label-legibility spike.
9. **Slot the LAN brain into the existing Coral inference-provider registry (PR #4)** — the heavy
   detector/VLM is a registered provider, not a new build. Keep Coral as a 270M-default local fallback
   that borrows the LAN brain; ship it on a lean Astra image + Yocto recipe. Treat phone in-browser
   vision as a RESERVED/EXPERIMENTAL resilience slot.
10. **Run the gating empirical spikes before committing the doc's hardware bets:** OV2640/OV3660 label
    legibility for Gemma at fridge range; Gemma 4 E4B latency on this Pi; 1B-Q4 fit on the 2 GB Coral.
    Set honest accuracy expectations in copy/telemetry and keep a human-in-the-loop confirm before any
    ledger mutation.

---

### Primary sources

- Open Food Facts API — <https://openfoodfacts.github.io/openfoodfacts-server/api/tutorial-off-api/>, bulk data <https://world.openfoodfacts.org/data>
- Edge VLM latency — <https://learnopencv.com/vlm-on-edge-devices/>
- Gemma 3 multimodal — <https://huggingface.co/blog/gemma3>
- Grounding DINO 1.5 Edge — <https://arxiv.org/html/2405.10300v1>
- Hailo GenAI / Hailo-10H — <https://hailo.ai/blog/bringing-generative-ai-to-the-edge-llm-on-hailo-10h/>
- Hailo HEF compile (Ultralytics) — <https://github.com/ultralytics/ultralytics/blob/main/docs/en/integrations/hailo.md>
- SKU-110K / RP2K — <https://arxiv.org/pdf/2006.12634>
- Food-101 SOTA — <https://arxiv.org/abs/2503.18997>; Inverse Cooking — <https://arxiv.org/pdf/1812.06164>
- python-zeroconf — <https://python-zeroconf.readthedocs.io/en/latest/api.html>
- mDNS spoofing — <https://book.hacktricks.wiki/en/generic-methodologies-and-resources/pentesting-network/spoofing-llmnr-nbt-ns-mdns-dns-and-wpad-and-relay-attacks.html>
- MDN secure contexts — <https://developer.mozilla.org/en-US/docs/Web/Security/Defenses/Secure_Contexts>
- Chrome Local Network Access — <https://developer.chrome.com/blog/local-network-access>; LNA spec <https://wicg.github.io/local-network-access/>
- Plex HTTPS — <https://words.filippo.io/how-plex-is-doing-https-for-all-its-users/>; mkcert <https://github.com/FiloSottile/mkcert>
- M5Stack Timer Camera — <https://docs.m5stack.com/en/unit/timercam>; ESP32-CAM troubleshooting <https://randomnerdtutorials.com/esp32-cam-troubleshooting-guide/>
- Grocy cooking — <https://github.com/grocy/grocy-docs/blob/master/tutorials/cooking.md>; Mealie timeline <https://docs.mealie.io/news/surveys/2024-october/q11/>
- Samsung Bespoke AI Vision Inside — <https://www.samsung.com/us/home-appliances/refrigerators/bespoke/>
- Kitche acquisition/retirement — <https://www.thegrocer.co.uk/news/new-ai-household-food-waste-reduction-app-remy-acquires-rival-kitche-to-boost-user-base/701748.article>
