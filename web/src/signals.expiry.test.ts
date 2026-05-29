import { describe, it, expect, beforeEach } from 'vitest'
import {
  mostWasted,
  expired,
  expiringSoon,
  daysUntilExpiry,
  pantry,
  type WasteTally,
  type PantryItem,
} from './signals'

function isoFromOffset(days: number): string {
  const d = new Date()
  d.setHours(0, 0, 0, 0)
  d.setDate(d.getDate() + days)
  const y = d.getFullYear()
  const m = String(d.getMonth() + 1).padStart(2, '0')
  const day = String(d.getDate()).padStart(2, '0')
  return `${y}-${m}-${day}`
}

describe('mostWasted', () => {
  const tally: WasteTally = {
    window_days: 30, discarded: 3, expired: 1, total: 4,
    items: ['milk', 'milk', 'milk', 'eggs'],
    by_item: [{ name: 'milk', count: 3 }, { name: 'eggs', count: 1 }],
  }
  it('returns the top-N by_item rows', () => {
    expect(mostWasted(tally, 1)).toEqual([{ name: 'milk', count: 3 }])
  })
  it('handles null/empty safely', () => {
    expect(mostWasted(null)).toEqual([])
    expect(mostWasted({ ...tally, by_item: [] })).toEqual([])
  })
})

describe('expired / expiringSoon partition', () => {
  beforeEach(() => { pantry.value = [] })
  it('puts a past-date item in expired, not expiringSoon', () => {
    const item: PantryItem = { canonical_name: 'milk', raw_text: 'milk', expires_at: isoFromOffset(-2) }
    pantry.value = [item]
    expect(expired.value.map(i => i.canonical_name)).toEqual(['milk'])
    expect(expiringSoon.value.map(i => i.canonical_name)).toEqual([])
  })
  it('puts a soon item in expiringSoon, not expired', () => {
    pantry.value = [{ canonical_name: 'bread', raw_text: 'bread', expires_at: isoFromOffset(1) }]
    expect(expiringSoon.value.map(i => i.canonical_name)).toEqual(['bread'])
    expect(expired.value.map(i => i.canonical_name)).toEqual([])
  })
  it('excludes used_up items from both', () => {
    pantry.value = [{ canonical_name: 'milk', raw_text: 'milk', expires_at: isoFromOffset(-2), state: 'used_up' }]
    expect(expired.value).toEqual([])
    expect(expiringSoon.value).toEqual([])
  })
  it('daysUntilExpiry returns an integer for a YYYY-MM-DD date', () => {
    expect(daysUntilExpiry(isoFromOffset(-2))).toBe(-2)
  })
})
