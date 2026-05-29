# Design — On-Device Shelf-Vision Feasibility Spike (iPhone PWA)

**Date:** 2026-05-28
**Status:** Design — awaiting operator review
**Scope:** A throwaway-grade **feasibility spike**, not a feature. Goal: learn whether a small VLM can run *in the Navigator PWA on the operator's iPhone* and produce useful shelf-parsing output, and capture the real numbers. Tested on the pi-nas dev node (`http://pi-nas.local:8090`), never prod.

## Motivation

PantryAtlas's shelf-photo parsing (`POST /navigator/vision/parse-shelf`) is server-side: the phone captures (`<input capture="environment">` in `Navigator.tsx`), uploads, and a Gemma-4B llama.cpp server parses. On the dev node there is no Gemma, so that route is 503. The operator asked: **could the iPhone itself run the model on-device, so the photo never leaves the phone and no server needs the 4B?** This spike answers that with the smallest real proof — and if it works, it could replace the deferred "stand up Gemma on robot" Phase 2 of the dev-node entirely.

The codebase already anticipates this: `pantryatlas/inference/provider.py:8` reserves an unimplemented `ProviderKind = "client"` ("the browser/phone is the inference provider"). This spike is the empirical precursor to implementing that kind — but does **not** implement it.

## Goal / success criteria

Deploy to the dev node, open `http://pi-nas.local:8090/` on the iPhone (via the kiosk QR), capture a real shelf photo, toggle "parse on-device," and record:

1. **Does it run at all** in Safari on the iPhone via the PWA? (binary)
2. **Which backend** — WebGPU or WASM fallback? (`navigator.gpu` present + model actually ran on it)
3. **Model load time** (first, uncached) and **inference time** (warm).
4. **Does Safari keep the tab alive** — i.e., does the VLM fit under iOS Safari's per-tab memory ceiling, or does the tab get killed? (the central unknown)
5. **Output plausibility** — are the parsed items recognizably the shelf's contents?

The deliverable is these five answers plus a working toggle, not production quality.

## Non-goals (YAGNI for the spike)

- The `kind:"client"` provider registry integration (this is pure client-side; it only *seeds* that work).
- Any backend / Python change.
- Video / live camera (still photo only; video is the frame-sampling follow-on).
- On-device embeddings.
- Self-hosting the model on pi-nas (spike loads from the HF CDN; local hosting is the obvious follow-up for offline/local-first).
- Prod deployment, polish, accuracy tuning, i18n.

## Architecture

- **Library:** `@huggingface/transformers` (transformers.js v3+) — added as the **first ML dependency** in the currently ML-free Preact frontend (`web/package.json`). Loaded lazily (dynamic `import()`) so it never bloats the main bundle or the non-experimental path.
- **Model:** `HuggingFaceTB/SmolVLM-256M-Instruct` (smallest; best chance of fitting iOS memory), with a one-constant switch to `HuggingFaceTB/SmolVLM-500M-Instruct`. Loaded via `AutoProcessor` + `AutoModelForVision2Seq.from_pretrained(id, { device, dtype })`.
- **Backend selection:** feature-detect `navigator.gpu`; use `device: 'webgpu'` when present, else `device: 'wasm'`. Per-module `dtype` tuned for memory (e.g. `{ embed_tokens: 'fp16', vision_encoder: 'fp16', decoder_model_merged: 'q4' }`); fall back to lighter dtypes if load fails. Report the chosen backend + dtype in the UI.
- **Image path:** the captured `File`/blob from `PhotoReviewSheet` → `RawImage.fromBlob(...)` → `processor(image, prompt)` → `model.generate({ ...inputs, max_new_tokens })` → `tokenizer.batch_decode(...)`. Prompt: a chat-templated instruction like *"List the food items visible on this shelf, one per line."*
- **Where it lives:** an **experimental toggle inside `web/src/components/PhotoReviewSheet.tsx`**, beside the existing server `postToVision(file)` path, gated behind a flag (`?ondevice=1` query param or a `localStorage('pa-ondevice')` switch) so it is off by default, isolated, and trivially removable. When on, the sheet calls a new `web/src/ondevice/parseShelfOnDevice.ts` module instead of `postToVision`.
- **Model caching:** transformers.js caches weights in the browser Cache API after first download from the HF CDN. First load is a multi-hundred-MB one-time download over WiFi; subsequent loads are cache hits.

### Module boundaries (isolation)

| Unit | Responsibility | Depends on |
|---|---|---|
| `web/src/ondevice/parseShelfOnDevice.ts` | Lazy-load transformers.js, pick backend, load SmolVLM (singleton), run one image→text parse, return `{ items, backend, dtype, loadMs, inferMs }` | `@huggingface/transformers` |
| `PhotoReviewSheet.tsx` (edit) | When the experimental flag is on, route the captured photo to `parseShelfOnDevice` instead of `postToVision`; render the result + telemetry | the module above |

Everything else (server, registry, embeddings, other components) is untouched. The module is deletable in one commit.

## Error handling / fallback

- **WebGPU absent** → automatic WASM fallback (slower; reported).
- **Model load OOM / tab pressure** → catch, retry once with a lighter dtype (e.g. all-`q4`) or the 256M model; if it still fails, surface a clear "on-device model didn't fit on this device" message with the captured numbers. This *is* a valid spike outcome.
- **First-load latency** → show a progress indicator (transformers.js exposes `progress_callback`); cache makes subsequent runs fast.
- **Output empty/garbled** → still record it; plausibility is a success-criterion measurement, not a hard failure.

## Testing / how we validate

Manual, on-device (this is a spike): `ops/dev/pa-deploy.sh` → on the iPhone open the kiosk QR → capture a shelf photo → flip the experimental toggle → observe the five success-criteria numbers. A tiny unit test for `parseShelfOnDevice`'s backend-selection logic (mockable `navigator.gpu`) is worthwhile; full model inference is not unit-tested (it's the manual proof). Compare against the desktop/robot browser to separate "iOS-specific" from "general" failures.

## Open risks / what could make the answer "no"

- **iOS Safari memory ceiling** is the real unknown — a VLM (even 256M, with vision encoder + KV cache) may exceed the per-tab budget and get evicted. This spike exists precisely to find out.
- **WebGPU on iOS is maintainer-flagged "experimental"** — it may fall back to WASM (much slower) or misbehave; the spike reports which.
- **First-load download size** over cellular would be painful; assume home WiFi for the proof.
- **Parse quality** of a 256M VLM is well below Gemma-4B; the spike judges "useful enough to pursue," not "good."

## Components summary

| Component | Action |
|---|---|
| `web/package.json` | add `@huggingface/transformers` |
| `web/src/ondevice/parseShelfOnDevice.ts` | new — lazy model load + image→text, returns result + telemetry |
| `web/src/components/PhotoReviewSheet.tsx` | edit — experimental flag routes to on-device path; render telemetry |
| backend / Python | **none** |

## If the spike succeeds → next steps (out of scope here)

Implement `kind:"client"` in the provider registry so the navigator can formally prefer on-device vision; self-host the SmolVLM ONNX files on pi-nas for offline/local-first; explore SmolVLM2 for the video ("pan the fridge") idea via frame sampling.
