import { describe, it, expect } from 'vitest'
import { buildReflectPayload } from './signals'

describe('buildReflectPayload', () => {
  it('passes rating and trims notes', () => {
    expect(buildReflectPayload(5, '  yum ')).toEqual({ rating: 5, notes: 'yum' })
  })
  it('empty note becomes null', () => {
    expect(buildReflectPayload(4, '   ')).toEqual({ rating: 4, notes: null })
  })
  it('no rating becomes null', () => {
    expect(buildReflectPayload(null, 'note')).toEqual({ rating: null, notes: 'note' })
  })
})
