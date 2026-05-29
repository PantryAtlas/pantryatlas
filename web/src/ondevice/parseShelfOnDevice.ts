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
      return pipeline('image-text-to-text' as Parameters<typeof pipeline>[0], MODEL_ID, {
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
