import { h, Fragment } from 'preact'
import { useEffect, useState } from 'preact/hooks'
import { CoverageRing } from './CoverageRing'
import { fetchSwaps, recipeSwaps, recipeKey, cookRecipe, reflectMeal, buildReflectPayload, type SwapSuggestion } from '../signals'
import { shouldShowPairingBadge } from '../lib/flavor'

/**
 * RecipeCard — collapsible recipe card with inline expansion.
 *
 * Design contract (DESIGN.md Section D):
 * - CoverageRing top-centered on mobile, leading on desktop (≥720px).
 * - Single chip line: "N missing · M min" or "All ingredients · M min".
 * - Source attribution "From RecipeNLG · CC-BY-NC-4.0" always visible.
 * - Tap → expands INLINE (no sheet): ingredient check/circle list +
 *   numbered instructions in sub-cards + actions.
 * - Chevron collapses.
 * - No literal hex colors or px padding values in this file.
 */

export interface RankedRecipe {
  recipe: {
    title: string
    ingredients: string[]
    instructions: string[]
    cook_time_min?: number
    source?: string
  }
  score: number
  coverage: number
  missing: string[]
  expiration_urgency: number
  substitution_penalty: number
  cultural_fit: number
  flavor?: number
}

interface RecipeCardProps {
  ranked: RankedRecipe
  /** Stagger delay in ms for entry animation (0 = no stagger) */
  animDelay?: number
}

// Check-circle icon (in-pantry)
function CheckCircleIcon() {
  return (
    <svg
      width="20"
      height="20"
      viewBox="0 0 24 24"
      fill="none"
      aria-hidden="true"
      style={{ flexShrink: 0 }}
    >
      <circle cx="12" cy="12" r="10" fill="var(--md-sys-color-tertiary-container)" />
      <path
        d="M8 12.5L10.5 15L16 9.5"
        stroke="var(--md-sys-color-tertiary)"
        stroke-width="2"
        stroke-linecap="round"
        stroke-linejoin="round"
      />
    </svg>
  )
}

// Circle-outline icon (missing)
function CircleIcon() {
  return (
    <svg
      width="20"
      height="20"
      viewBox="0 0 24 24"
      fill="none"
      aria-hidden="true"
      style={{ flexShrink: 0 }}
    >
      <circle
        cx="12"
        cy="12"
        r="10"
        stroke="var(--md-sys-color-outline)"
        stroke-width="1.8"
      />
    </svg>
  )
}

// Chevron-up icon
function ChevronUpIcon() {
  return (
    <svg width="20" height="20" viewBox="0 0 24 24" fill="none" aria-hidden="true">
      <path
        d="M6 15L12 9L18 15"
        stroke="var(--md-sys-color-on-surface-variant)"
        stroke-width="2"
        stroke-linecap="round"
        stroke-linejoin="round"
      />
    </svg>
  )
}

// Chevron-down icon
function ChevronDownIcon() {
  return (
    <svg width="20" height="20" viewBox="0 0 24 24" fill="none" aria-hidden="true">
      <path
        d="M6 9L12 15L18 9"
        stroke="var(--md-sys-color-on-surface-variant)"
        stroke-width="2"
        stroke-linecap="round"
        stroke-linejoin="round"
      />
    </svg>
  )
}

// Link icon for attribution
function LinkIcon() {
  return (
    <svg width="12" height="12" viewBox="0 0 24 24" fill="none" aria-hidden="true" style={{ display: 'inline', verticalAlign: 'middle', marginLeft: '3px' }}>
      <path
        d="M10 13a5 5 0 007.54.54l3-3a5 5 0 00-7.07-7.07l-1.72 1.71"
        stroke="var(--md-sys-color-on-surface-variant)"
        stroke-width="2"
        stroke-linecap="round"
        stroke-linejoin="round"
      />
      <path
        d="M14 11a5 5 0 00-7.54-.54l-3 3a5 5 0 007.07 7.07l1.71-1.71"
        stroke="var(--md-sys-color-on-surface-variant)"
        stroke-width="2"
        stroke-linecap="round"
        stroke-linejoin="round"
      />
    </svg>
  )
}

export function RecipeCard({ ranked, animDelay = 0 }: RecipeCardProps) {
  const [expanded, setExpanded] = useState(false)

  const { recipe, coverage, missing } = ranked
  const total = recipe.ingredients.length
  const present = total - missing.length
  const missingCount = missing.length
  const cookMin = recipe.cook_time_min ?? 30
  const missingHalf = total > 0 && missingCount >= total / 2

  // Lazy smart-swaps: fetch only when the card is expanded and only if there
  // are missing ingredients to swap (reading recipeSwaps.value subscribes here).
  const key = recipeKey(ranked)
  const swapEntry = recipeSwaps.value[key]
  // Re-fire when the cache entry's state changes (incl. cleared → undefined on
  // a pantry mutation), so swaps recover instead of sticking on "finding…".
  useEffect(() => {
    if (expanded && missingCount > 0) fetchSwaps(ranked)
  }, [expanded, key, missingCount, swapEntry?.state])

  // Map missing-ingredient → its swap suggestion for quick lookup in the list.
  const swapByMissing: Record<string, SwapSuggestion> = {}
  if (swapEntry?.state === 'done' && swapEntry.swaps) {
    for (const s of swapEntry.swaps) swapByMissing[s.missing] = s
  }
  const swapLineFor = (ing: string): string | null => {
    if (missing.indexOf(ing) === -1) return null
    if (!swapEntry || swapEntry.state === 'loading') return 'finding a swap…'
    if (swapEntry.state === 'offline') return 'swaps unavailable offline'
    if (swapEntry.state === 'error') return null
    const s = swapByMissing[ing]
    if (!s) return null
    if (s.best_swap) return `try ${s.best_swap} · ${Math.round(s.similarity * 100)}% match`
    if (s.reason === 'no_pantry') return null
    return 'no close swap in your pantry'
  }

  const [cooking, setCooking] = useState(false)
  const [cooked, setCooked] = useState(false)
  const [servings, setServings] = useState(2)
  // Post-cook reflection state
  const [cookedEventId, setCookedEventId] = useState<number | null>(null)
  const [rating, setRating] = useState<number | null>(null)
  const [note, setNote] = useState('')
  const [reflectDone, setReflectDone] = useState(false)
  const [saving, setSaving] = useState(false)

  async function handleCooked(e: MouseEvent) {
    e.stopPropagation()
    setCooking(true)
    const consumed = recipe.ingredients
      .filter((ing) => !missing.includes(ing))
      .map((ing) => ({ canonical_name: ing, coarse_amount: 'cook' }))
    const ev = await cookRecipe({ dish_name: recipe.title, servings, consumed })
    setCooking(false)
    if (ev) { setCooked(true); setCookedEventId(ev.id) }
  }

  async function handleReflectSave(e: MouseEvent) {
    e.stopPropagation()
    setSaving(true)
    if (cookedEventId != null) {
      const p = buildReflectPayload(rating, note)
      await reflectMeal(cookedEventId, p.rating, p.notes)
    }
    setSaving(false)
    setReflectDone(true)
  }

  // Single chip label
  const chipLabel = missingCount === 0
    ? `All ingredients · ${cookMin} min`
    : `${missingCount} missing · ${cookMin} min`

  // Chip style — error-container when missing ≥ half
  const chipBg = missingHalf
    ? 'var(--md-sys-color-error-container)'
    : 'transparent'
  const chipColor = missingHalf
    ? 'var(--md-sys-color-on-error-container)'
    : 'var(--md-sys-color-on-surface-variant)'
  const chipBorder = missingHalf
    ? 'none'
    : '1px solid var(--md-sys-color-outline-variant)'

  // Entry animation style
  const entryStyle: h.JSX.CSSProperties = animDelay >= 0
    ? {
        animation: `recipe-card-enter 320ms cubic-bezier(0.2,0,0,1) ${animDelay}ms both`,
      }
    : {}

  function toggleExpand(e: MouseEvent) {
    // Don't collapse when clicking action buttons inside the card
    const target = e.target as HTMLElement
    if (target.closest('button') && !target.closest('[data-collapse-trigger]')) return
    setExpanded((v) => !v)
  }

  return (
    <Fragment>
      <style>{`
        @keyframes recipe-card-enter {
          from { opacity: 0; transform: translateY(8px); }
          to   { opacity: 1; transform: translateY(0); }
        }
        @media (prefers-reduced-motion: reduce) {
          @keyframes recipe-card-enter {
            from { opacity: 0; }
            to   { opacity: 1; }
          }
        }
      `}</style>

      <li
        style={{
          borderRadius: 'var(--md-sys-shape-corner-extra-large)',
          background: 'var(--md-sys-color-surface-container-high)',
          boxShadow: 'var(--shadow-rest)',
          padding: 'var(--card-p, 1.25rem)',
          display: 'flex',
          flexDirection: 'column',
          gap: '0',
          cursor: 'pointer',
          transition: 'box-shadow 0.18s cubic-bezier(0.2,0,0,1)',
          position: 'relative',
          ...entryStyle,
        }}
        onClick={toggleExpand}
        onMouseEnter={(e) => {
          ;(e.currentTarget as HTMLLIElement).style.boxShadow = 'var(--shadow-active)'
        }}
        onMouseLeave={(e) => {
          ;(e.currentTarget as HTMLLIElement).style.boxShadow = 'var(--shadow-rest)'
        }}
        role="article"
        aria-label={`${recipe.title}, ${chipLabel}`}
        aria-expanded={expanded}
      >
        {/* Card header — ring + title + chip */}
        <div
          style={{
            display: 'flex',
            flexDirection: 'column',
            alignItems: 'center',
            gap: '12px',
          }}
          class="recipe-card-header"
        >
          {/* Mobile: ring centered at top; Desktop: ring leading via flex-row on parent */}
          <style>{`
            @media (min-width: 600px) {
              .recipe-card-header {
                flex-direction: row !important;
                align-items: flex-start !important;
              }
            }
          `}</style>

          {/* Coverage ring — 80px mobile, 64px desktop */}
          <div aria-hidden="true" class="ring-wrapper">
            <style>{`
              .ring-wrapper { display: contents; }
              @media (min-width: 600px) {
                .ring-wrapper { flex-shrink: 0; }
              }
              .ring-wrapper .ring-mobile { display: block; }
              .ring-wrapper .ring-desktop { display: none; }
              @media (min-width: 600px) {
                .ring-wrapper .ring-mobile { display: none; }
                .ring-wrapper .ring-desktop { display: block; }
              }
            `}</style>
            <div class="ring-mobile">
              <CoverageRing present={present} total={total} size={80} />
            </div>
            <div class="ring-desktop">
              <CoverageRing present={present} total={total} size={64} />
            </div>
          </div>

          {/* Title + chip + attribution row */}
          <div style={{ flex: 1, minWidth: 0, width: '100%' }}>
            {/* Title + chevron row */}
            <div style={{ display: 'flex', alignItems: 'flex-start', justifyContent: 'space-between', gap: '8px' }}>
              <p
                style={{
                  fontFamily: 'var(--font)',
                  fontSize: 'var(--md-sys-typescale-title-medium-size)',
                  fontWeight: 'var(--md-sys-typescale-title-medium-weight)',
                  lineHeight: 'var(--md-sys-typescale-title-medium-line-height)',
                  color: 'var(--md-sys-color-on-surface)',
                  overflow: 'hidden',
                  display: '-webkit-box',
                  WebkitLineClamp: expanded ? 'unset' : '2',
                  WebkitBoxOrient: 'vertical',
                  flex: 1,
                  margin: '0',
                }}
              >
                {recipe.title}
              </p>
              {/* Collapse chevron — always rendered but visible on expand */}
              <button
                type="button"
                data-collapse-trigger="true"
                onClick={(e) => { e.stopPropagation(); setExpanded((v) => !v) }}
                aria-label={expanded ? 'Collapse recipe' : 'Expand recipe'}
                style={{
                  width: '36px',
                  height: '36px',
                  borderRadius: 'var(--md-sys-shape-corner-full)',
                  background: 'transparent',
                  border: 'none',
                  cursor: 'pointer',
                  display: 'flex',
                  alignItems: 'center',
                  justifyContent: 'center',
                  flexShrink: 0,
                  marginTop: '-4px',
                  marginRight: '-8px',
                  transition: 'background 0.15s',
                }}
                onMouseEnter={(e) => {
                  ;(e.currentTarget as HTMLButtonElement).style.background =
                    'var(--md-sys-color-surface-container)'
                }}
                onMouseLeave={(e) => {
                  ;(e.currentTarget as HTMLButtonElement).style.background = 'transparent'
                }}
              >
                {expanded ? <ChevronUpIcon /> : <ChevronDownIcon />}
              </button>
            </div>

            {/* Single chip line */}
            <div style={{ marginTop: '8px' }}>
              <span
                style={{
                  display: 'inline-flex',
                  alignItems: 'center',
                  padding: '3px 12px',
                  borderRadius: 'var(--md-sys-shape-corner-full)',
                  background: chipBg,
                  color: chipColor,
                  border: chipBorder,
                  fontFamily: 'var(--font)',
                  fontSize: 'var(--md-sys-typescale-label-medium-size)',
                  fontWeight: 'var(--md-sys-typescale-label-medium-weight)',
                  whiteSpace: 'nowrap',
                }}
              >
                {chipLabel}
              </span>
              {shouldShowPairingBadge(ranked.flavor) && (
                <span
                  data-pairing-badge="true"
                  style={{
                    display: 'inline-flex',
                    alignItems: 'center',
                    marginLeft: '6px',
                    padding: '3px 12px',
                    borderRadius: 'var(--md-sys-shape-corner-full)',
                    background: 'var(--md-sys-color-tertiary-container)',
                    color: 'var(--md-sys-color-on-tertiary-container)',
                    fontFamily: 'var(--font)',
                    fontSize: 'var(--md-sys-typescale-label-medium-size)',
                    fontWeight: 'var(--md-sys-typescale-label-medium-weight)',
                    whiteSpace: 'nowrap',
                  }}
                >
                  great pairing
                </span>
              )}
            </div>

            {/* Source attribution — RecipeNLG, always visible on collapsed card */}
            <p
              style={{
                fontFamily: 'var(--font)',
                fontSize: 'var(--md-sys-typescale-label-small-size)',
                fontWeight: 'var(--md-sys-typescale-label-small-weight)',
                lineHeight: 'var(--md-sys-typescale-label-small-line-height)',
                color: 'var(--md-sys-color-on-surface-variant)',
                marginTop: '6px',
                opacity: '0.8',
              }}
            >
              From RecipeNLG · CC-BY-NC-4.0
              <LinkIcon />
            </p>
          </div>
        </div>

        {/* Expanded content — ingredient list + instructions + actions */}
        {expanded && (
          <div
            style={{
              marginTop: '20px',
              display: 'flex',
              flexDirection: 'column',
              gap: '20px',
              animation: 'recipe-card-enter 320ms cubic-bezier(0.2,0,0,1)',
            }}
            onClick={(e) => e.stopPropagation()}
          >
            {/* Ingredient list */}
            <div>
              <p
                style={{
                  fontFamily: 'var(--font)',
                  fontSize: 'var(--md-sys-typescale-headline-medium-size)',
                  fontWeight: 'var(--md-sys-typescale-headline-medium-weight)',
                  lineHeight: 'var(--md-sys-typescale-headline-medium-line-height)',
                  color: 'var(--md-sys-color-on-surface)',
                  marginBottom: '12px',
                }}
              >
                Ingredients
              </p>
              <ul style={{ listStyle: 'none', display: 'flex', flexDirection: 'column', gap: '8px' }}>
                {recipe.ingredients.map((ing) => {
                  const inPantry = !missing.includes(ing)
                  const swapLine = inPantry ? null : swapLineFor(ing)
                  const hasSwap =
                    swapEntry?.state === 'done' && swapByMissing[ing]?.best_swap != null
                  return (
                    <li
                      key={ing}
                      data-ingredient={ing}
                      style={{
                        display: 'flex',
                        flexDirection: 'column',
                        gap: '2px',
                        fontFamily: 'var(--font)',
                        fontSize: 'var(--md-sys-typescale-body-large-size)',
                        color: inPantry
                          ? 'var(--md-sys-color-on-surface)'
                          : 'var(--md-sys-color-on-surface-variant)',
                      }}
                    >
                      <span style={{ display: 'flex', alignItems: 'center', gap: '10px' }}>
                        {inPantry ? <CheckCircleIcon /> : <CircleIcon />}
                        <span>{ing}</span>
                      </span>
                      {swapLine && (
                        <span
                          data-swap-line={hasSwap ? 'match' : 'none'}
                          style={{
                            marginLeft: '30px',
                            fontSize: 'var(--md-sys-typescale-label-medium-size)',
                            fontWeight: 'var(--md-sys-typescale-label-medium-weight)',
                            color: hasSwap
                              ? 'var(--md-sys-color-primary)'
                              : 'var(--md-sys-color-on-surface-variant)',
                          }}
                        >
                          ↳ {swapLine}
                        </span>
                      )}
                    </li>
                  )
                })}
              </ul>
            </div>

            {/* Instructions */}
            <div>
              <p
                style={{
                  fontFamily: 'var(--font)',
                  fontSize: 'var(--md-sys-typescale-headline-medium-size)',
                  fontWeight: 'var(--md-sys-typescale-headline-medium-weight)',
                  lineHeight: 'var(--md-sys-typescale-headline-medium-line-height)',
                  color: 'var(--md-sys-color-on-surface)',
                  marginBottom: '12px',
                }}
              >
                Instructions
              </p>
              <ol style={{ listStyle: 'none', display: 'flex', flexDirection: 'column', gap: '8px' }}>
                {recipe.instructions.map((step, i) => (
                  <li
                    key={i}
                    style={{
                      display: 'flex',
                      gap: '12px',
                      padding: '12px 16px',
                      borderRadius: 'var(--md-sys-shape-corner-medium)',
                      background: 'var(--md-sys-color-surface-container-low)',
                    }}
                  >
                    <span
                      style={{
                        fontFamily: 'var(--font)',
                        fontSize: 'var(--md-sys-typescale-label-medium-size)',
                        fontWeight: 'var(--md-sys-typescale-label-medium-weight)',
                        color: 'var(--md-sys-color-primary)',
                        flexShrink: 0,
                        lineHeight: 'var(--md-sys-typescale-body-large-line-height)',
                        minWidth: '20px',
                      }}
                    >
                      {i + 1}.
                    </span>
                    <p
                      style={{
                        fontFamily: 'var(--font)',
                        fontSize: 'var(--md-sys-typescale-body-large-size)',
                        lineHeight: 'var(--md-sys-typescale-body-large-line-height)',
                        color: 'var(--md-sys-color-on-surface)',
                        margin: '0',
                      }}
                    >
                      {step}
                    </p>
                  </li>
                ))}
              </ol>
            </div>

            {/* Source attribution (expanded — links inline) */}
            <p
              style={{
                fontFamily: 'var(--font)',
                fontSize: 'var(--md-sys-typescale-body-medium-size)',
                color: 'var(--md-sys-color-on-surface-variant)',
              }}
            >
              From RecipeNLG · CC-BY-NC-4.0
              <LinkIcon />
            </p>

            {/* Action buttons */}
            <div style={{ display: 'flex', gap: '12px', flexWrap: 'wrap' }}>
              {/* Servings stepper — visible before cook is logged */}
              {!cooked && (
                <div
                  style={{
                    display: 'flex',
                    alignItems: 'center',
                    gap: '4px',
                    minHeight: '44px',
                    padding: '4px 8px',
                    borderRadius: 'var(--md-sys-shape-corner-full)',
                    border: '1.5px solid var(--md-sys-color-outline-variant)',
                    background: 'var(--md-sys-color-surface-container-low)',
                    flexShrink: 0,
                  }}
                >
                  <button
                    type="button"
                    aria-label="Fewer servings"
                    disabled={cooking || servings <= 1}
                    onClick={(e) => { e.stopPropagation(); setServings((s) => Math.max(1, s - 1)) }}
                    style={{
                      width: '32px',
                      height: '32px',
                      borderRadius: 'var(--md-sys-shape-corner-full)',
                      background: 'transparent',
                      border: 'none',
                      cursor: (cooking || servings <= 1) ? 'default' : 'pointer',
                      color: 'var(--md-sys-color-on-surface-variant)',
                      fontFamily: 'var(--font)',
                      fontSize: '1.25rem',
                      display: 'flex',
                      alignItems: 'center',
                      justifyContent: 'center',
                      opacity: (cooking || servings <= 1) ? '0.38' : '1',
                      transition: 'background 0.15s',
                      flexShrink: 0,
                    }}
                    onMouseEnter={(e) => {
                      if (!cooking && servings > 1)
                        (e.currentTarget as HTMLButtonElement).style.background =
                          'var(--md-sys-color-surface-container)'
                    }}
                    onMouseLeave={(e) => {
                      (e.currentTarget as HTMLButtonElement).style.background = 'transparent'
                    }}
                  >−</button>
                  <span
                    style={{
                      minWidth: '28px',
                      textAlign: 'center',
                      fontFamily: 'var(--font)',
                      fontSize: 'var(--md-sys-typescale-label-large-size)',
                      fontWeight: 'var(--md-sys-typescale-label-large-weight)',
                      color: 'var(--md-sys-color-on-surface)',
                    }}
                    aria-live="polite"
                    aria-label={`${servings} servings`}
                  >{servings}</span>
                  <button
                    type="button"
                    aria-label="More servings"
                    disabled={cooking || servings >= 99}
                    onClick={(e) => { e.stopPropagation(); setServings((s) => Math.min(99, s + 1)) }}
                    style={{
                      width: '32px',
                      height: '32px',
                      borderRadius: 'var(--md-sys-shape-corner-full)',
                      background: 'transparent',
                      border: 'none',
                      cursor: (cooking || servings >= 99) ? 'default' : 'pointer',
                      color: 'var(--md-sys-color-on-surface-variant)',
                      fontFamily: 'var(--font)',
                      fontSize: '1.25rem',
                      display: 'flex',
                      alignItems: 'center',
                      justifyContent: 'center',
                      opacity: (cooking || servings >= 99) ? '0.38' : '1',
                      transition: 'background 0.15s',
                      flexShrink: 0,
                    }}
                    onMouseEnter={(e) => {
                      if (!cooking && servings < 99)
                        (e.currentTarget as HTMLButtonElement).style.background =
                          'var(--md-sys-color-surface-container)'
                    }}
                    onMouseLeave={(e) => {
                      (e.currentTarget as HTMLButtonElement).style.background = 'transparent'
                    }}
                  >+</button>
                </div>
              )}

              {/* "I cooked this" — filled primary pill; logs + soft-decrements */}
              <button
                type="button"
                data-cooked-btn={cooked ? 'done' : 'idle'}
                disabled={cooking || cooked}
                onClick={handleCooked}
                style={{
                  flex: '1 1 auto',
                  minHeight: '44px',
                  padding: '10px 20px',
                  borderRadius: 'var(--md-sys-shape-corner-full)',
                  background: cooked
                    ? 'var(--md-sys-color-tertiary-container)'
                    : 'var(--md-sys-color-primary)',
                  color: cooked
                    ? 'var(--md-sys-color-on-tertiary-container)'
                    : 'var(--md-sys-color-on-primary)',
                  border: 'none',
                  fontFamily: 'var(--font)',
                  fontSize: 'var(--md-sys-typescale-label-large-size)',
                  fontWeight: 'var(--md-sys-typescale-label-large-weight)',
                  cursor: cooking || cooked ? 'default' : 'pointer',
                  whiteSpace: 'nowrap',
                }}
              >
                {cooked
                  ? `✓ Logged${reflectDone && rating ? ` · ${'★'.repeat(rating)}` : ''}`
                  : cooking ? 'Logging…' : 'I cooked this'}
              </button>

              {/* "Add missing to shopping list" — outlined pill */}
              <button
                type="button"
                disabled={missingCount === 0}
                style={{
                  flex: '1 1 auto',
                  minHeight: '44px',
                  padding: '10px 20px',
                  borderRadius: 'var(--md-sys-shape-corner-full)',
                  background: 'transparent',
                  border: '1.5px solid var(--md-sys-color-outline)',
                  color: 'var(--md-sys-color-primary)',
                  fontFamily: 'var(--font)',
                  fontSize: 'var(--md-sys-typescale-label-large-size)',
                  fontWeight: 'var(--md-sys-typescale-label-large-weight)',
                  cursor: missingCount === 0 ? 'default' : 'pointer',
                  opacity: missingCount === 0 ? '0.4' : '1',
                  transition: 'background 0.15s',
                  whiteSpace: 'nowrap',
                }}
                onMouseEnter={(e) => {
                  if (missingCount > 0) {
                    ;(e.currentTarget as HTMLButtonElement).style.background =
                      'var(--md-sys-color-primary-container)'
                  }
                }}
                onMouseLeave={(e) => {
                  ;(e.currentTarget as HTMLButtonElement).style.background = 'transparent'
                }}
              >
                Add missing to shopping list
              </button>

              {/* "Hide for now" — filled tonal pill */}
              <button
                type="button"
                style={{
                  flex: '0 1 auto',
                  minHeight: '44px',
                  padding: '10px 20px',
                  borderRadius: 'var(--md-sys-shape-corner-full)',
                  background: 'var(--md-sys-color-secondary-container)',
                  color: 'var(--md-sys-color-on-secondary-container)',
                  border: 'none',
                  fontFamily: 'var(--font)',
                  fontSize: 'var(--md-sys-typescale-label-large-size)',
                  fontWeight: 'var(--md-sys-typescale-label-large-weight)',
                  cursor: 'pointer',
                  transition: 'background 0.15s',
                  whiteSpace: 'nowrap',
                }}
                onMouseEnter={(e) => {
                  ;(e.currentTarget as HTMLButtonElement).style.background =
                    'var(--md-sys-color-surface-container-highest)'
                }}
                onMouseLeave={(e) => {
                  ;(e.currentTarget as HTMLButtonElement).style.background =
                    'var(--md-sys-color-secondary-container)'
                }}
                onClick={(e) => { e.stopPropagation(); setExpanded(false) }}
              >
                Hide for now
              </button>
            </div>

            {/* Post-cook reflection panel — appears once logged, until saved/skipped */}
            {cooked && !reflectDone && (
              <div
                data-reflect-panel="true"
                style={{
                  display: 'flex',
                  flexDirection: 'column',
                  gap: '12px',
                  padding: '16px',
                  borderRadius: 'var(--md-sys-shape-corner-medium)',
                  background: 'var(--md-sys-color-surface-container-low)',
                  border: '1px solid var(--md-sys-color-outline-variant)',
                }}
              >
                <p
                  style={{
                    fontFamily: 'var(--font)',
                    fontSize: 'var(--md-sys-typescale-label-large-size)',
                    fontWeight: 'var(--md-sys-typescale-label-large-weight)',
                    color: 'var(--md-sys-color-on-surface)',
                    margin: '0',
                  }}
                >
                  How was it?
                </p>

                {/* Star rating — five toggle buttons */}
                <div
                  role="group"
                  aria-label="Rate this dish"
                  style={{ display: 'flex', gap: '4px' }}
                >
                  {[1, 2, 3, 4, 5].map((n) => (
                    <button
                      key={n}
                      type="button"
                      aria-label={`Rate ${n} star${n === 1 ? '' : 's'}`}
                      aria-pressed={rating === n}
                      onClick={(e) => { e.stopPropagation(); setRating(n) }}
                      style={{
                        width: '40px',
                        height: '40px',
                        borderRadius: 'var(--md-sys-shape-corner-full)',
                        background: 'transparent',
                        border: 'none',
                        cursor: 'pointer',
                        fontSize: '1.5rem',
                        lineHeight: '1',
                        color: n <= (rating ?? 0)
                          ? 'var(--md-sys-color-primary)'
                          : 'var(--md-sys-color-outline)',
                        display: 'flex',
                        alignItems: 'center',
                        justifyContent: 'center',
                        transition: 'background 0.15s, color 0.15s',
                      }}
                      onMouseEnter={(e) => {
                        ;(e.currentTarget as HTMLButtonElement).style.background =
                          'var(--md-sys-color-surface-container)'
                      }}
                      onMouseLeave={(e) => {
                        ;(e.currentTarget as HTMLButtonElement).style.background = 'transparent'
                      }}
                    >
                      {n <= (rating ?? 0) ? '★' : '☆'}
                    </button>
                  ))}
                </div>

                {/* Optional note */}
                <input
                  type="text"
                  maxLength={140}
                  aria-label="Add a note"
                  placeholder="Add a note (optional)"
                  value={note}
                  onInput={(e) => setNote((e.currentTarget as HTMLInputElement).value)}
                  onClick={(e) => e.stopPropagation()}
                  style={{
                    minHeight: '44px',
                    padding: '10px 14px',
                    borderRadius: 'var(--md-sys-shape-corner-medium)',
                    border: '1.5px solid var(--md-sys-color-outline-variant)',
                    background: 'var(--md-sys-color-surface)',
                    color: 'var(--md-sys-color-on-surface)',
                    fontFamily: 'var(--font)',
                    fontSize: 'var(--md-sys-typescale-body-large-size)',
                  }}
                />

                {/* Save + Skip */}
                <div style={{ display: 'flex', gap: '12px', flexWrap: 'wrap' }}>
                  <button
                    type="button"
                    data-reflect-save="true"
                    disabled={saving}
                    onClick={handleReflectSave}
                    style={{
                      flex: '1 1 auto',
                      minHeight: '44px',
                      padding: '10px 20px',
                      borderRadius: 'var(--md-sys-shape-corner-full)',
                      background: 'var(--md-sys-color-primary)',
                      color: 'var(--md-sys-color-on-primary)',
                      border: 'none',
                      fontFamily: 'var(--font)',
                      fontSize: 'var(--md-sys-typescale-label-large-size)',
                      fontWeight: 'var(--md-sys-typescale-label-large-weight)',
                      cursor: saving ? 'default' : 'pointer',
                      whiteSpace: 'nowrap',
                    }}
                  >
                    {saving ? 'Saving…' : 'Save'}
                  </button>
                  <button
                    type="button"
                    data-reflect-skip="true"
                    disabled={saving}
                    onClick={(e) => { e.stopPropagation(); setReflectDone(true) }}
                    style={{
                      flex: '0 1 auto',
                      minHeight: '44px',
                      padding: '10px 20px',
                      borderRadius: 'var(--md-sys-shape-corner-full)',
                      background: 'var(--md-sys-color-secondary-container)',
                      color: 'var(--md-sys-color-on-secondary-container)',
                      border: 'none',
                      fontFamily: 'var(--font)',
                      fontSize: 'var(--md-sys-typescale-label-large-size)',
                      fontWeight: 'var(--md-sys-typescale-label-large-weight)',
                      cursor: saving ? 'default' : 'pointer',
                      whiteSpace: 'nowrap',
                    }}
                  >
                    Skip
                  </button>
                </div>
              </div>
            )}
          </div>
        )}
      </li>
    </Fragment>
  )
}
