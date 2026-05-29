import { describe, it, expect } from 'vitest'
import { shouldShowPairingBadge, FLAVOR_BADGE_THRESHOLD } from './flavor'

describe('shouldShowPairingBadge', () => {
  it('true at/above threshold', () => {
    expect(shouldShowPairingBadge(FLAVOR_BADGE_THRESHOLD)).toBe(true)
    expect(shouldShowPairingBadge(0.9)).toBe(true)
  })
  it('false below threshold or missing', () => {
    expect(shouldShowPairingBadge(FLAVOR_BADGE_THRESHOLD - 0.01)).toBe(false)
    expect(shouldShowPairingBadge(0)).toBe(false)
    expect(shouldShowPairingBadge(undefined)).toBe(false)
  })
})
