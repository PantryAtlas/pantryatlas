# On-Device Shelf-Vision Spike — Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Prove a small vision-language model can run entirely in the Navigator PWA on the operator's iPhone and parse a shelf photo on-device — and capture the real numbers (backend, load/infer time, did-the-tab-survive, output quality).

**Architecture:** A lazily-imported `@huggingface/transformers` `image-text-to-text` pipeline running **SmolVLM-256M-Instruct** in the browser (WebGPU, WASM fallback). It lives in an isolated `web/src/ondevice/` module that mirrors the existing `postToVision` signal contract, gated behind a `?ondevice=1` / `localStorage` flag inside `PhotoReviewSheet`. **No backend/Python changes.** Tested on the pi-nas dev node (`http://pi-nas.local:8090`) from the iPhone.

**Tech Stack:** Preact + `@preact/signals` (existing), `@huggingface/transformers` (new, lazy), `vitest` (new dev-only, for the two pure helpers), Vite build, deployed via `ops/dev/pa-deploy.sh`.

**Spec:** `docs/superpowers/specs/2026-05-28-ondevice-vision-poc-design.md`

---

## File Structure

| File | Responsibility | New/Mod |
|---|---|---|
| `web/package.json` | add `@huggingface/transformers` dep + `vitest` devDep + `test` script | Modify |
| `web/src/ondevice/helpers.ts` | the two **pure, import-free** helpers (`pickDevice`, `parseModelOutput`) + the `Backend` type. No signals/transformers imports, so unit tests run in plain Node. | Create |
| `web/src/ondevice/helpers.test.ts` | vitest unit tests for the two pure helpers | Create |
| `web/src/ondevice/parseShelfOnDevice.ts` | the spike's runtime: feature flag, telemetry signal, lazy SmolVLM pipeline singleton, `parseShelfOnDevice(file)` that imports the helpers and sets the same signals as `postToVision` | Create |
| `web/src/components/PhotoReviewSheet.tsx` | route to on-device path when the flag is on; render telemetry caption | Modify (`:34-43`, body render) |

Everything else (server, registry, embeddings, signals.ts) is untouched. The spike is deletable by removing `web/src/ondevice/`, reverting the `PhotoReviewSheet` edit, and dropping the dep.

**Why the helpers are split out:** `parseShelfOnDevice.ts` imports `../signals` (browser-oriented). Keeping the unit-tested pure functions in a separate import-free `helpers.ts` means vitest never transitively loads `../signals`/`@preact/signals` in Node — no jsdom or vitest config needed.

---

## Task 1: Add dependencies + test runner

**Files:**
- Modify: `web/package.json`

- [ ] **Step 1: Install the runtime + dev deps**

Run (from repo root):
```bash
npm --prefix web install @huggingface/transformers
npm --prefix web install -D vitest
```
Expected: both resolve and write to `web/package.json` / `web/package-lock.json`. `@huggingface/transformers` is large (~10MB incl. onnxruntime-web wasm) — that's fine; it's lazy-imported so it never enters the main bundle.

- [ ] **Step 2: Add a `test` script**

In `web/package.json`, add to `"scripts"`:
```json
"test": "vitest run"
```

- [ ] **Step 3: Verify the runner works (no tests yet)**

Run:
```bash
npm --prefix web run test
```
Expected: vitest runs and reports "No test files found" (exit 0 or a benign "no tests" message). This confirms vitest is installed and wired.

- [ ] **Step 4: Commit**

```bash
git add web/package.json web/package-lock.json
git commit -m "build(web): add @huggingface/transformers + vitest for on-device vision spike"
```

---

## Task 2: Pure helpers — `pickDevice` + `parseModelOutput` (TDD)

These are the only unit-testable parts (model inference is proven manually in Task 5). `pickDevice` chooses WebGPU vs WASM; `parseModelOutput` turns the VLM's free-text into a clean item list. They live in an **import-free** `helpers.ts` so the test runs in plain Node.

**Files:**
- Create: `web/src/ondevice/helpers.ts`
- Create: `web/src/ondevice/helpers.test.ts`

- [ ] **Step 1: Write the failing tests**

Create `web/src/ondevice/helpers.test.ts`:
```ts
import { describe, it, expect } from 'vitest'
import { pickDevice, parseModelOutput } from './helpers'

describe('pickDevice', () => {
  it('returns webgpu when a gpu object is present', () => {
    expect(pickDevice({})).toBe('webgpu')
  })
  it('falls back to wasm when gpu is absent', () => {
    expect(pickDevice(undefined)).toBe('wasm')
    expect(pickDevice(null)).toBe('wasm')
  })
})

describe('parseModelOutput', () => {
  it('splits lines and strips bullets/numbering', () => {
    const raw = '1. Tomatoes\n2) Milk\n- Eggs\n* Butter'
    expect(parseModelOutput(raw)).toEqual(['Tomatoes', 'Milk', 'Eggs', 'Butter'])
  })
  it('drops blanks, dedupes case-insensitively, and trims', () => {
    const raw = '  Onion \n\nonion\nGarlic\n'
    expect(parseModelOutput(raw)).toEqual(['Onion', 'Garlic'])
  })
  it('drops sentence-like lines longer than 40 chars and caps at 20 items', () => {
    const longLine = 'This is clearly a full sentence describing the shelf contents in detail'
    expect(parseModelOutput(longLine)).toEqual([])
    const many = Array.from({ length: 30 }, (_, i) => `item${i}`).join('\n')
    expect(parseModelOutput(many).length).toBe(20)
  })
})
```

- [ ] **Step 2: Run the tests to verify they fail**

Run:
```bash
npm --prefix web run test
```
Expected: FAIL — `pickDevice`/`parseModelOutput` are not exported (import error / undefined).

- [ ] **Step 3: Implement the helpers**

Create `web/src/ondevice/helpers.ts`:
```ts
// On-device shelf-vision spike — pure, import-free helpers. See
// docs/superpowers/specs/2026-05-28-ondevice-vision-poc-design.md

export type Backend = 'webgpu' | 'wasm'

/** Choose the inference backend from the presence of `navigator.gpu`. */
export function pickDevice(gpu: unknown): Backend {
  return gpu ? 'webgpu' : 'wasm'
}

/** Turn the VLM's free-text answer into a clean, de-duped item list. */
export function parseModelOutput(raw: string): string[] {
  const seen = new Set<string>()
  const out: string[] = []
  for (const line of raw.split('\n')) {
    const cleaned = line.replace(/^\s*[-*\d.)\]]+\s*/, '').trim()
    if (!cleaned) continue
    if (cleaned.length > 40) continue // sentence, not an item
    const key = cleaned.toLowerCase()
    if (seen.has(key)) continue
    seen.add(key)
    out.push(cleaned)
    if (out.length >= 20) break
  }
  return out
}
```

- [ ] **Step 4: Run the tests to verify they pass**

Run:
```bash
npm --prefix web run test
```
Expected: PASS — all 5 assertions green.

- [ ] **Step 5: Commit**

```bash
git add web/src/ondevice/helpers.ts web/src/ondevice/helpers.test.ts
git commit -m "feat(ondevice): pure pickDevice + parseModelOutput helpers (TDD)"
```

---

## Task 3: The on-device pipeline + flag + telemetry

Adds the lazy SmolVLM pipeline, the feature flag, the telemetry signal, and `parseShelfOnDevice(file)` which sets the **same signals** `postToVision` does (`photoSheetState`, `photoDetectedItems`, `photoErrorMsg`) so the existing UI renders the result unchanged.

**Files:**
- Create: `web/src/ondevice/parseShelfOnDevice.ts`

- [ ] **Step 1: Create the runtime module (flag, telemetry signal, pipeline singleton, main function)**

Create `web/src/ondevice/parseShelfOnDevice.ts`:
```ts
// On-device shelf-vision spike — runtime (browser). Pure helpers live in ./helpers.
import { signal } from '@preact/signals'
import { photoSheetState, photoDetectedItems, photoErrorMsg } from '../signals'
import { pickDevice, parseModelOutput, type Backend } from './helpers'

export const MODEL_ID = 'HuggingFaceTB/SmolVLM-256M-Instruct'
const SHELF_PROMPT =
  'List the individual food items visible in this photo. ' +
  'Respond with one item per line, just the item name — no numbering, no sentences.'

export interface OnDeviceTelemetry {
  backend: Backend
  model: string
  loadMs: number
  inferMs: number
}
export const onDeviceTelemetry = signal<OnDeviceTelemetry | null>(null)

/** On when `?ondevice=1` is in the URL (persisted) or localStorage `pa-ondevice=1`. */
export function isOnDeviceEnabled(): boolean {
  try {
    if (typeof location !== 'undefined') {
      const q = new URLSearchParams(location.search).get('ondevice')
      if (q === '1') {
        try { localStorage.setItem('pa-ondevice', '1') } catch { /* ignore */ }
        return true
      }
      if (q === '0') {
        try { localStorage.removeItem('pa-ondevice') } catch { /* ignore */ }
        return false
      }
    }
    if (typeof localStorage !== 'undefined') return localStorage.getItem('pa-ondevice') === '1'
  } catch { /* ignore */ }
  return false
}

let _genPromise: Promise<(messages: unknown, opts: unknown) => Promise<unknown>> | null = null
let _backend: Backend = 'wasm'

function getGenerator() {
  if (!_genPromise) {
    _genPromise = (async () => {
      const { pipeline } = await import('@huggingface/transformers')
      _backend = pickDevice((globalThis.navigator as { gpu?: unknown } | undefined)?.gpu)
      return pipeline('image-text-to-text', MODEL_ID, {
        device: _backend,
        dtype: { embed_tokens: 'fp16', vision_encoder: 'fp16', decoder_model_merged: 'q4' },
      }) as unknown as (messages: unknown, opts: unknown) => Promise<unknown>
    })()
  }
  return _genPromise
}

/** Defensive: pipeline returns [{ generated_text: string | Array<{role,content}> }]. */
function extractText(out: unknown): string {
  const first = Array.isArray(out) ? out[0] : out
  const gt = (first as { generated_text?: unknown })?.generated_text
  if (typeof gt === 'string') return gt
  if (Array.isArray(gt)) {
    const last = gt[gt.length - 1] as { content?: unknown }
    if (typeof last?.content === 'string') return last.content
  }
  return ''
}

/** Drop-in replacement for postToVision: parse the shelf photo on-device. */
export async function parseShelfOnDevice(file: File): Promise<void> {
  photoSheetState.value = 'loading'
  onDeviceTelemetry.value = null
  const blobUrl = URL.createObjectURL(file)
  try {
    const t0 = performance.now()
    const gen = await getGenerator()
    const loadMs = Math.round(performance.now() - t0)
    const messages = [
      { role: 'user', content: [
        { type: 'image', image: blobUrl },
        { type: 'text', text: SHELF_PROMPT },
      ] },
    ]
    const t1 = performance.now()
    const out = await gen(messages, { max_new_tokens: 256, do_sample: false })
    const inferMs = Math.round(performance.now() - t1)
    const items = parseModelOutput(extractText(out))
    photoDetectedItems.value = items.map((label) => ({ label, checked: true }))
    onDeviceTelemetry.value = { backend: _backend, model: MODEL_ID, loadMs, inferMs }
    photoSheetState.value = 'parsed'
  } catch (err) {
    photoErrorMsg.value =
      `On-device model failed (${_backend}): ${(err as Error)?.message ?? String(err)}`
    photoSheetState.value = 'error'
  } finally {
    URL.revokeObjectURL(blobUrl)
  }
}
```

- [ ] **Step 2: Verify the helper tests still pass**

Run:
```bash
npm --prefix web run test
```
Expected: PASS — the 5 helper assertions still green. (The test imports only `./helpers`, which has no `../signals`/`@huggingface/transformers` imports, so it's unaffected by this new runtime module.)

- [ ] **Step 3: Verify it type-checks and bundles (lazy chunk split out)**

Run:
```bash
npm --prefix web run build
```
Expected: build succeeds; output shows a **separate async chunk** for `@huggingface/transformers` (a large `assets/*.js` distinct from `main-*.js`), confirming it is NOT in the main bundle.

- [ ] **Step 4: Commit**

```bash
git add web/src/ondevice/parseShelfOnDevice.ts
git commit -m "feat(ondevice): lazy SmolVLM image-text-to-text pipeline + flag + telemetry"
```

---

## Task 4: Wire the flag into `PhotoReviewSheet`

Route the captured photo to the on-device path when the flag is on, and show a telemetry caption. Keeps the server path as the default.

**Files:**
- Modify: `web/src/components/PhotoReviewSheet.tsx`

- [ ] **Step 1: Add the imports**

At the top of `web/src/components/PhotoReviewSheet.tsx`, after the existing `../signals` import block, add:
```ts
import { parseShelfOnDevice, onDeviceTelemetry, isOnDeviceEnabled } from '../ondevice/parseShelfOnDevice'
```

- [ ] **Step 2: Route the `useEffect` to the on-device path when enabled**

Replace the existing effect body (currently `:34-43`):
```ts
  useEffect(() => {
    if (file) {
      objectUrl.current = URL.createObjectURL(file)
      // POST to vision endpoint
      postToVision(file)
    }
    return () => {
      if (objectUrl.current) URL.revokeObjectURL(objectUrl.current)
    }
  }, [file])
```
with:
```ts
  useEffect(() => {
    if (file) {
      objectUrl.current = URL.createObjectURL(file)
      if (isOnDeviceEnabled()) {
        parseShelfOnDevice(file) // runs SmolVLM in-browser; sets the same signals
      } else {
        postToVision(file)
      }
    }
    return () => {
      if (objectUrl.current) URL.revokeObjectURL(objectUrl.current)
    }
  }, [file])
```

- [ ] **Step 3: Read the telemetry signal in the component body**

After the existing signal reads (currently `:26-29`, the `const errorMsg = photoErrorMsg.value` line), add:
```ts
  const telemetry = onDeviceTelemetry.value
```

- [ ] **Step 4: Render the telemetry caption in the parsed state**

In the `sheetState === 'parsed'` block, immediately after the opening `<div>` (before the "Found N items" `<p>`, currently around `:255`), add:
```tsx
              {telemetry && (
                <p
                  style={{
                    fontFamily: 'var(--font)',
                    fontSize: 'var(--md-sys-typescale-label-small-size, 11px)',
                    color: 'var(--md-sys-color-on-surface-variant)',
                    margin: '0 0 10px',
                    opacity: 0.8,
                  }}
                >
                  On-device · {telemetry.backend} · load {telemetry.loadMs}ms · infer {telemetry.inferMs}ms · {telemetry.model}
                </p>
              )}
```

- [ ] **Step 5: Show backend in the loading state (so the long first-load is legible)**

In the `sheetState === 'loading'` block, replace the existing loading text `Reading your shelf...` (currently `:209`) with:
```tsx
                {isOnDeviceEnabled() ? 'Reading your shelf on this phone…' : 'Reading your shelf...'}
```

- [ ] **Step 6: Verify build + tests**

Run:
```bash
npm --prefix web run build && npm --prefix web run test
```
Expected: build succeeds; tests still PASS.

- [ ] **Step 7: Commit**

```bash
git add web/src/components/PhotoReviewSheet.tsx
git commit -m "feat(ondevice): route PhotoReviewSheet to on-device VLM behind ?ondevice=1 flag"
```

---

## Task 5: Deploy to the dev node + on-device proof (the actual experiment)

This is the spike's real test — manual, on the iPhone, against the dev node. Record the five success-criteria numbers from the spec.

**Files:** none (deploy + observe)

- [ ] **Step 1: Deploy the new build to the dev node**

Run (from repo root, on robot):
```bash
ops/dev/pa-deploy.sh
```
Expected: `OK: PWA served`, `navigator/pantry=200`, `live: http://pi-nas.local:8090/`.

- [ ] **Step 2: Desktop sanity check first (separates iOS-specific failures from general ones)**

On a desktop browser, open `http://pi-nas.local:8090/?ondevice=1`, use the camera/upload to submit a shelf-like photo, and confirm the on-device path runs (telemetry caption appears, items listed). If it fails here, it's a code/model bug, not iOS — fix before testing the phone.

Expected: parsed items + a telemetry caption like `On-device · webgpu · load <N>ms · infer <N>ms · HuggingFaceTB/SmolVLM-256M-Instruct`.

- [ ] **Step 3: On the iPhone — run the proof**

On the iPhone (home WiFi): scan the kiosk QR or open `http://pi-nas.local:8090/?ondevice=1`. Take a real shelf photo. Watch the loading → parsed flow. **Record the five answers:**

1. **Did it run at all?** (yes/no)
2. **Backend** — `webgpu` or `wasm`? (from the telemetry caption)
3. **Load time** (first, uncached) and **infer time** (from the caption; reload for a warm number).
4. **Did Safari keep the tab alive** through model load, or did it reload/crash? (the memory-ceiling answer)
5. **Output plausibility** — are the listed items recognizably on the shelf?

- [ ] **Step 4: If the model OOMs / tab dies — retry lighter, once**

If Step 3 fails on load/memory: edit `web/src/ondevice/parseShelfOnDevice.ts` `dtype` to all-`q4` (`dtype: 'q4'`), redeploy (`ops/dev/pa-deploy.sh`), retest. If it still dies, that is a **valid recorded outcome** ("SmolVLM-256M does not fit in iOS Safari on <device>"). Do not escalate further — note it and stop.

- [ ] **Step 5: Record results in the spec + commit**

Append a short "Spike results (2026-05-28)" section to `docs/superpowers/specs/2026-05-28-ondevice-vision-poc-design.md` with the five answers and the verdict (does on-device vision work for this iPhone? worth pursuing the `kind:"client"` provider?). Then:
```bash
git add docs/superpowers/specs/2026-05-28-ondevice-vision-poc-design.md
git commit -m "docs(ondevice): record on-device shelf-vision spike results"
```

---

## Notes for the executor

- **Git / concurrent session:** another session has been committing to `feat/sp-a-loop-foundation`. Use the **targeted `git add <paths>`** shown in each task (never `git add -A`) so you only commit spike files. If a dedicated branch is preferred, the operator will create `feat/pinas-dev-node` first.
- **`web/dist` is built by `pa-deploy.sh`** — don't hand-edit it. The editable install on the dev node serves it.
- **First on-device load downloads ~hundreds of MB** from the HF CDN (one-time, cached in the browser). Use home WiFi.
- **This is a spike.** If the transformers.js `image-text-to-text` pipeline output shape differs from `extractText`'s two handled cases on the real run, adjust `extractText` (it's defensive but the live model is the source of truth) — that's expected spike iteration, not a plan defect.
