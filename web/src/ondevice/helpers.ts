// On-device shelf-vision spike — pure, import-free helpers. See
// docs/superpowers/specs/2026-05-28-ondevice-vision-poc-design.md

export type Backend = 'webgpu' | 'wasm'

/** Choose the inference backend from the presence of `navigator.gpu`. */
export function pickDevice(gpu: unknown): Backend {
  return gpu ? 'webgpu' : 'wasm'
}

/**
 * Turn the VLM's free-text answer into a clean, de-duped item list.
 * SmolVLM-256M often returns prose ("a car, a blue door, and a garage door"),
 * so we split on newlines, commas, semicolons, and the word "and", then strip
 * list markers / leading articles / trailing punctuation. Pieces >40 chars are
 * treated as sentence fragments and dropped (the raw text is shown separately).
 */
export function parseModelOutput(raw: string): string[] {
  const seen = new Set<string>()
  const out: string[] = []
  for (const piece of raw.split(/\n|,|;|\band\b/i)) {
    const cleaned = piece
      .trim() // first, so the ^-anchored strips below see no leading whitespace
      .replace(/^[-*\d.)\]]+\s*/, '') // leading list markers
      .replace(/^(?:the|a|an)\s+/i, '') // leading article
      .replace(/[.!?]+\s*$/, '') // trailing sentence punctuation
      .trim()
    if (cleaned.length < 2 || cleaned.length > 40) continue
    const key = cleaned.toLowerCase()
    if (seen.has(key)) continue
    seen.add(key)
    out.push(cleaned)
    if (out.length >= 20) break
  }
  return out
}
