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
