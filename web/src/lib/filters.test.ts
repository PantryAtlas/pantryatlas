import { describe, it, expect } from 'vitest'
import { buildFilterQuery, CUISINE_OPTIONS, hasActiveFilters } from './filters'

describe('buildFilterQuery', () => {
  it('empty when no filters', () => {
    expect(buildFilterQuery(null, new Set(), null)).toBe('')
  })
  it('encodes cuisine + excludes + time', () => {
    const q = buildFilterQuery('italian', new Set(['meat', 'gluten']), 30)
    expect(q).toContain('cuisine=italian')
    expect(q).toMatch(/exclude=meat%2Cgluten|exclude=gluten%2Cmeat/)
    expect(q).toContain('max_time_min=30')
    expect(q.startsWith('?')).toBe(true)
  })
})

describe('hasActiveFilters', () => {
  it('false when all empty, true otherwise', () => {
    expect(hasActiveFilters(null, new Set(), null)).toBe(false)
    expect(hasActiveFilters('mexican', new Set(), null)).toBe(true)
    expect(hasActiveFilters(null, new Set(['dairy']), null)).toBe(true)
    expect(hasActiveFilters(null, new Set(), 60)).toBe(true)
  })
})

describe('CUISINE_OPTIONS', () => {
  it('is the shipped six', () => {
    expect(CUISINE_OPTIONS).toEqual(['italian', 'mexican', 'asian', 'american', 'indian', 'greek'])
  })
})
