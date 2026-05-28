# Design — Inference Provider Registry (Coral-edition foundation)

- **Date:** 2026-05-27
- **Status:** Approved (brainstorming) — ready for implementation planning
- **Scope of this document:** Sub-project 1 (V1) of the "support the new Coral board" effort
- **Branch context:** authored against `feat/navigator-v0.2.0`

## Motivation

We want PantryAtlas to support the **new Coral Dev Board** (the Synaptics
Astra SL2610 "Coralboard", launched March 2026, shown at Google I/O 2026). This
board is *not* the 2019 Edge TPU Coral Dev Board the current marketing copy
describes. Its real envelope:

- Dual-core Arm Cortex-A55 @ 2 GHz + Cortex-M52; **1 TOPS Coral NPU** (RISC-V).
- **Up to 2 GB LPDDR4 RAM**, up to 64 GB eMMC.
- **Yocto Linux** (+ Android), board-specific BSP — *not* Raspberry Pi OS.
- Ships out-of-box with **Gemma 3 270M**, which is **text-only** (only Gemma 3's
  4B/12B/27B are multimodal).

Two hard consequences: PantryAtlas's Gemma 4 E4B brain cannot fit in 2 GB, and
the on-board model cannot do vision. The board *can*, however, act as an
always-on LAN server that **borrows compute from a more capable device on the
same local network** (a desktop or Pi running Gemma 4, or any OpenAI-compatible
LLM) for heavy work, falling back to its small on-board model when no helper is
reachable. All traffic stays on the home network — still local-first.

This document specifies the **inference provider registry** that makes that
"borrow a beefier box on the LAN" capability real. It is deliberately
**hardware-independent**: it builds and is fully testable on the Pi 5 today, with
no Coralboard required. It is usable and verifiable immediately — configure and
**Test** a helper, with routing/fallback exercised end-to-end — and product
features (camera vision, natural-language pantry parsing) are wired to it as they
land in v0.2.

### Hailo clarification (resolved during brainstorming)

The Hailo-8 (26 TOPS) on the operator's Pi 5 is **not** used to "optimize" the
Coral board — they are separate accelerators with incompatible toolchains. For
this effort the Hailo-equipped Pi is simply the **beefy LAN helper box** running
Gemma 4. Note: Gemma 4 via `llama.cpp` runs on the Pi's CPU; it does **not** use
the Hailo silicon. A genuine HailoRT-accelerated vision pipeline (compiling a
model to HEF) is explicitly a *future, separate* sub-project, not in scope here.

## Decomposition of the overall effort

| # | Sub-project | Hardware dependency | This doc? |
|---|---|---|---|
| PR-0 | Marketing docs fix (correct stale Edge-TPU copy + old product link) | none | no — parallel, ships first |
| **1** | **Inference provider registry + on-board + LAN providers + fallback + settings UI** | **none (Pi 5)** | **yes** |
| 2 | Coral-edition packaging (Yocto/BSP image, Gemma 3 270M swap, fit in 2 GB) | Coralboard (ordered, arriving) | no — next up |
| 3 | On-board NPU vision (LiteRT), client-in-browser compute provider, HailoRT vision provider | Coralboard / browser / Hailo | no — deferred |

## Goals (V1)

- Route LLM requests to the highest-priority **available** provider that has the
  required capability, with graceful fallback down an ordered chain.
- Support two provider kinds in V1: **on-board local** (existing `llama.cpp`
  runner) and **LAN endpoint** (admin-configured OpenAI-compatible URL).
- Define a **`vision` capability** and implement it for the LAN provider (a
  multimodal Gemma 4 peer can perform it). On-board/NPU/Hailo vision are reserved.
- Provide a **settings UI** to add, test, enable/disable, and order providers.
- Be fully unit-testable without network or special hardware, reusing the
  existing `httpx.MockTransport` pattern.

## Non-goals (V1)

- Coral Yocto packaging / 270M model swap (Sub-project 2).
- On-board NPU/LiteRT vision, client-in-browser (WebGPU) inference, mDNS
  auto-discovery, HailoRT (Sub-project 3). The registry leaves labeled
  `kind`/capability slots for these; it does not implement them.
- Wiring the **camera UI** to the vision capability — a thin follow-up. V1
  delivers the capability + provider, not the end-to-end photo flow.

## Existing seam (why this is mostly greenfield wiring)

- `pantryatlas/gemma/client.py` — `GemmaClient(base_url, timeout_s, transport)`
  is already an **OpenAI-compatible** client (`POST /v1/chat/completions`) with a
  configurable `base_url`. `.generate(system, user, schema=, strict=, ...)`
  returns `str | dict`.
- `pantryatlas/gemma/runner.py` — `GemmaRunner` manages a local `llama-server`
  subprocess (E4B/E2B tiers, memory-aware), exposing `.url`, `.is_healthy()`,
  `.start()`, `.stop()`, context manager.
- **Only tests instantiate these today** — the navigator web server does not yet
  wire the LLM into request flow. So introducing the registry is new wiring, not
  a refactor of live call sites.
- Config precedent: `~/.pantryatlas/` already holds `pantry.json` and
  `recipes.db` (`navigator/server.py`). Provider config follows the JSON precedent.

## Architecture

New package `pantryatlas/inference/` (parallels `gemma/`, `embeddings/`):

```
pantryatlas/inference/
  __init__.py
  provider.py              # Provider protocol, Capability, ProviderInfo, errors
  registry.py              # ProviderRegistry: routing + fallback
  config.py                # load/save ~/.pantryatlas/providers.json
  providers/
    __init__.py
    local_runner.py        # LocalRunnerProvider (wraps GemmaRunner + GemmaClient)
    lan_endpoint.py        # LanEndpointProvider (GemmaClient against a LAN URL)
```

### Provider protocol (`provider.py`)

- `Capability = Literal["text", "vision"]`.
- `ProviderKind = Literal["local", "lan"]` with reserved (not implemented):
  `"client"`, `"npu"`, `"hailo"`.
- `Provider` Protocol:
  - `name: str`
  - `kind: ProviderKind`
  - `capabilities: set[Capability]`
  - `priority: int` (lower number = tried first)
  - `is_available() -> bool` — health check, short-TTL cached.
  - `generate(system, user, schema=None, strict=False, **opts) -> str | dict` —
    same signature surface as `GemmaClient.generate`.
  - `analyze_image(image: bytes, prompt: str, schema=None, **opts) -> str | dict` —
    raises `CapabilityUnavailable` if `"vision"` not in `capabilities`.
- Errors: `NoProviderAvailable(capability)`, `CapabilityUnavailable(capability)`.

### Providers

- **`LocalRunnerProvider`** — owns a `GemmaRunner`; `generate()` delegates to
  `GemmaClient(base_url=runner.url)`. `capabilities = {"text"}`. `is_available()`
  ⇒ `runner.is_healthy()` (lazily starting the subprocess per current behavior).
- **`LanEndpointProvider`** — `GemmaClient(base_url=<configured>)`.
  `capabilities` is `{"text"}` or `{"text","vision"}` per config flag.
  `is_available()` ⇒ cached `GET {base_url}/health` (or a cheap probe).
  `analyze_image()` sends OpenAI multimodal content (text + base64 image) — this
  requires a small extension to `GemmaClient` to accept image content; that
  extension is part of V1.

### Registry (`registry.py`)

- Holds providers ordered by `priority`.
- `generate(...)`: candidates = available providers with `"text"`, in priority
  order; try each; on transport error / non-2xx / timeout, fall to next; if all
  fail or none qualify ⇒ `NoProviderAvailable("text")`.
- `analyze_image(...)`: same, filtered by `"vision"`.
- `providers_status() -> list[ProviderInfo]` for the settings UI.
- Availability is cached with a short TTL (e.g. ~10 s) to avoid hammering peers
  on every request; `Test` in the UI forces a fresh probe.

## Data flow

```
caller needs capability C
  -> registry filters providers by C
  -> orders by priority
  -> for each: is_available() (cached)? -> attempt
       success -> return
       failure -> next
  -> exhausted -> NoProviderAvailable(C)  (server renders friendly message)
```

## Config & persistence (`config.py`)

`~/.pantryatlas/providers.json`:

```json
{
  "providers": [
    { "name": "on-board", "kind": "local", "priority": 100,
      "enabled": true, "capabilities": ["text"] },
    { "name": "kitchen-desktop", "kind": "lan",
      "base_url": "http://192.168.1.50:8080", "priority": 10,
      "enabled": true, "capabilities": ["text", "vision"] }
  ]
}
```

- Seeded with a single `local` provider at high `priority` number (last-resort
  fallback). Lower number = preferred; the operator's stated chain is
  client → LAN → on-board (V1: LAN → on-board).
- Side-effect-free defaults, matching `navigator/server.py` conventions.

## Settings UI

A new "AI helpers on your network" panel in the navigator web UI:

- List configured providers with **live status** (reachable / unreachable) and
  capabilities (text / vision).
- **Add LAN endpoint:** name, URL, "this endpoint is multimodal (can see
  photos)" checkbox.
- Per-provider: **Test** (forces a fresh probe), **enable/disable**, **reorder**
  priority.
- Follows existing navigator server + web patterns; persists via `config.py`.

## Error handling

- Per-provider request timeout (configurable; default from `GemmaClient`).
- Short-TTL availability cache; unreachable LAN peer is **skipped, never fatal**.
- Single typed `NoProviderAvailable` surfaced to the UI as a friendly message
  (e.g. "No AI helper is reachable right now — type your pantry instead, or
  bring a helper online"). Vision-specific: "Camera input needs a vision-capable
  helper on your network (or the Pi edition)."

## Testing strategy

- **Unit (no hardware/network):**
  - Registry routing + fallback with mock providers (capability filtering,
    priority order, skip-unavailable, exhaustion → `NoProviderAvailable`).
  - `config.py` load/save round-trip + defaults seeding.
  - `LanEndpointProvider` / `LocalRunnerProvider` `generate()` and
    `analyze_image()` via `httpx.MockTransport` (reusing existing test pattern).
  - `analyze_image()` raises `CapabilityUnavailable` for text-only providers.
- **Integration (Pi-gated, existing marker):** adapt
  `tests/integration/test_end_to_end_pi.py` to exercise the path through the
  registry against a real local `GemmaRunner`.

## Future sub-projects (reserved, not built here)

- **SP2 — Coral edition packaging:** Yocto image + BSP, Gemma 3 270M swap (via
  `LocalRunnerProvider` pointing at a 270M model or LiteRT), validation in 2 GB.
- **SP3 — vision + federation:** on-board NPU vision (LiteRT detector/OCR →
  text), client-in-browser provider (WebGPU/MediaPipe), mDNS auto-discovery,
  genuine HailoRT vision provider on the Pi. Each slots into the `kind` /
  capability enums defined here.

## References

- Synaptics/Google next-gen Coral Dev Board announcement (2026-03-10) and Google
  I/O 2026 showcase.
- Synaptics Astra SL2610 specs (Cortex-A55 + Coral NPU, ≤2 GB LPDDR4, Yocto).
- Coral NPU (RISC-V, MLIR/LiteRT/IREE toolchain; VeriSilicon + Google, 2025-11).
- Gemma 3 270M model card (text-only; multimodal only in 4B/12B/27B).
