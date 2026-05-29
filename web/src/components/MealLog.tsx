// web/src/components/MealLog.tsx
import { h } from 'preact'
import { useEffect } from 'preact/hooks'
import { meals, fetchMeals } from '../signals'

/** Kitchen log — a reverse-chronological list of cook events. */
export function MealLog() {
  useEffect(() => { void fetchMeals() }, [])
  const list = meals.value
  if (list.length === 0) {
    return (
      <p style={{
        fontFamily: 'var(--font)',
        color: 'var(--md-sys-color-on-surface-variant)',
        padding: '12px 0',
      }} data-meal-empty="true">
        Nothing cooked yet — tap "I cooked this" on a recipe to start your log.
      </p>
    )
  }
  return (
    <ul style={{ listStyle: 'none', display: 'flex', flexDirection: 'column', gap: '8px' }}
        data-meal-log="true">
      {list.map((m) => (
        <li key={m.id}
            data-meal-id={m.id}
            style={{
              padding: '12px 16px',
              borderRadius: 'var(--md-sys-shape-corner-medium)',
              background: 'var(--md-sys-color-surface-container-low)',
              fontFamily: 'var(--font)',
            }}>
          <span style={{
            fontSize: 'var(--md-sys-typescale-title-small-size)',
            fontWeight: 'var(--md-sys-typescale-title-small-weight)',
            color: 'var(--md-sys-color-on-surface)',
          }}>{m.dish_name}</span>
          <span style={{
            display: 'block',
            fontSize: 'var(--md-sys-typescale-label-small-size)',
            color: 'var(--md-sys-color-on-surface-variant)',
            marginTop: '2px',
          }}>
            {new Date(m.cooked_at).toLocaleDateString()}
            {m.consumed.length > 0 ? ` · used ${m.consumed.length} item${m.consumed.length === 1 ? '' : 's'}` : ''}
          </span>
        </li>
      ))}
    </ul>
  )
}
