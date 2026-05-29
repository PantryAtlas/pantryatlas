// On-device shelf-vision spike — runtime (browser). Pure helpers live in ./helpers.
//
// API note: the `image-text-to-text` pipeline task does NOT exist in this version of
// @huggingface/transformers, and `image-to-text` is caption-only (drops the prompt).
// SmolVLM (an Idefics3-class Vision2Seq model) is driven via the raw AutoProcessor +
// AutoModelForVision2Seq + apply_chat_template flow below — verified working in Node.
// The transformers module is cast to `any` because its .d.ts under-declares these methods.
import { signal } from '@preact/signals'
import { photoSheetState, photoDetectedItems, photoErrorMsg } from '../signals'
import { pickDevice, parseModelOutput, type Backend } from './helpers'

export const MODEL_ID = 'HuggingFaceTB/SmolVLM-256M-Instruct'
const SHELF_PROMPT =
  'List the food items visible in this photo, separated by commas. Just the item names.'

export interface OnDeviceTelemetry {
  backend: Backend
  model: string
  loadMs: number
  inferMs: number
  rawText: string
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

// eslint-disable-next-line @typescript-eslint/no-explicit-any
type Loaded = { processor: any; model: any }
let _loadPromise: Promise<Loaded> | null = null
let _backend: Backend = 'wasm'

/** Lazily load SmolVLM (processor + model) once; cached across calls. */
function getModel(): Promise<Loaded> {
  if (!_loadPromise) {
    _loadPromise = (async () => {
      // eslint-disable-next-line @typescript-eslint/no-explicit-any
      const tf: any = await import('@huggingface/transformers')
      _backend = pickDevice((globalThis.navigator as { gpu?: unknown } | undefined)?.gpu)
      const processor = await tf.AutoProcessor.from_pretrained(MODEL_ID)
      const model = await tf.AutoModelForVision2Seq.from_pretrained(MODEL_ID, {
        dtype: { embed_tokens: 'fp16', vision_encoder: 'fp16', decoder_model_merged: 'q4' },
        device: _backend,
      })
      return { processor, model }
    })()
  }
  return _loadPromise
}

/** Drop-in replacement for postToVision: parse the shelf photo on-device. */
export async function parseShelfOnDevice(file: File): Promise<void> {
  photoSheetState.value = 'loading'
  onDeviceTelemetry.value = null
  const blobUrl = URL.createObjectURL(file)
  try {
    // eslint-disable-next-line @typescript-eslint/no-explicit-any
    const tf: any = await import('@huggingface/transformers')
    const t0 = performance.now()
    const { processor, model } = await getModel()
    const loadMs = Math.round(performance.now() - t0)

    const image = await tf.RawImage.read(blobUrl)
    const messages = [
      { role: 'user', content: [{ type: 'image' }, { type: 'text', text: SHELF_PROMPT }] },
    ]
    const text = processor.apply_chat_template(messages, { add_generation_prompt: true })
    const inputs = await processor(text, [image])

    const t1 = performance.now()
    const generatedIds = await model.generate({ ...inputs, max_new_tokens: 256, do_sample: false })
    const inferMs = Math.round(performance.now() - t1)

    // Decode only the newly generated tokens (slice off the prompt).
    const promptLen = inputs.input_ids.dims.at(-1)
    const trimmed = generatedIds.slice(null, [promptLen, null])
    const decoded: string[] = processor.batch_decode(trimmed, { skip_special_tokens: true })
    const rawText = (decoded[0] ?? '').trim()

    const items = parseModelOutput(rawText)
    photoDetectedItems.value = items.map((label) => ({ label, checked: true }))
    onDeviceTelemetry.value = { backend: _backend, model: MODEL_ID, loadMs, inferMs, rawText }
    photoSheetState.value = 'parsed'
  } catch (err) {
    photoErrorMsg.value =
      `On-device model failed (${_backend}): ${(err as Error)?.message ?? String(err)}`
    photoSheetState.value = 'error'
  } finally {
    URL.revokeObjectURL(blobUrl)
  }
}
