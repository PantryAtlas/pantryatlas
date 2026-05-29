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
