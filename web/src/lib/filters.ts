export const CUISINE_OPTIONS = ['italian', 'mexican', 'asian', 'american', 'indian', 'greek'] as const
export type Cuisine = (typeof CUISINE_OPTIONS)[number]
export const EXCLUDE_OPTIONS = ['meat', 'dairy', 'gluten'] as const
export const TIME_OPTIONS = [30, 60] as const

export function hasActiveFilters(
  cuisine: string | null,
  excludes: Set<string>,
  maxTime: number | null,
): boolean {
  return cuisine != null || excludes.size > 0 || maxTime != null
}

export function buildFilterQuery(
  cuisine: string | null,
  excludes: Set<string>,
  maxTime: number | null,
): string {
  const p = new URLSearchParams()
  if (cuisine) p.set('cuisine', cuisine)
  if (excludes.size) p.set('exclude', [...excludes].join(','))
  if (maxTime != null) p.set('max_time_min', String(maxTime))
  const s = p.toString()
  return s ? `?${s}` : ''
}
