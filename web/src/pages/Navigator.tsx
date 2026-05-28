import { h, Fragment } from 'preact'
import { useEffect, useRef, useState } from 'preact/hooks'
import { useSignalEffect } from '@preact/signals'
import {
  mode,
  modeSwitcherOpen,
  modeLabel,
  modeIcon,
  pantry,
  pantryCount,
  recipeSectionLabel,
  fetchPantry,
  fetchRecipes,
  recipes,
  recipeLoadState,
  refineState,
  recipeKey,
  deleteItem,
  addItem,
  addInputValue,
  addState,
  addResolvedName,
  addErrorMsg,
  photoSheetOpen,
  photoFile,
  photoSheetState,
  daysUntilExpiry,
  hasPersistedMode,
  wireOfflineReplay,
} from '../signals'
import { ModeSwitcher } from '../components/ModeSwitcher'
import { PhotoReviewSheet } from '../components/PhotoReviewSheet'
import { RecipeCard } from '../components/RecipeCard'
import { OfflineBanner } from '../components/OfflineBanner'
import { AiHelpersPanel } from '../components/AiHelpersPanel'

// ---------------------------------------------------------------------------
// Debounce util
// ---------------------------------------------------------------------------
function debounce<T extends (...args: Parameters<T>) => void>(fn: T, ms: number): T {
  let timer: ReturnType<typeof setTimeout>
  return ((...args: Parameters<T>) => {
    clearTimeout(timer)
    timer = setTimeout(() => fn(...args), ms)
  }) as T
}

// ---------------------------------------------------------------------------
// Navigator — single scrolling screen
// ---------------------------------------------------------------------------

// Debounce returns a stable fn reference — used outside the component for recipe refetch
function debounceRecipe<T extends (...args: Parameters<T>) => void>(fn: T, ms: number): T {
  let timer: ReturnType<typeof setTimeout>
  return ((...args: Parameters<T>) => {
    clearTimeout(timer)
    timer = setTimeout(() => fn(...args), ms)
  }) as T
}

const _debouncedFetchRecipes = debounceRecipe(
  (items: ReturnType<typeof pantry.value.slice>, m: typeof mode.value) => {
    fetchRecipes(items, m)
  },
  600,
)

export function Navigator() {
  const [showHelpers, setShowHelpers] = useState(false)

  useEffect(() => {
    fetchPantry()
    wireOfflineReplay()
    // Open mode switcher on first launch (no persisted mode)
    if (!hasPersistedMode()) {
      modeSwitcherOpen.value = true
    }
  }, [])

  // Live-recompute recipes whenever pantry or mode changes (debounced 600ms).
  // useSignalEffect auto-tracks the signals read inside (pantry.value, mode.value).
  useSignalEffect(() => {
    const items = pantry.value
    const m = mode.value
    _debouncedFetchRecipes(items, m)
  })

  return (
    <Fragment>
      {/* Offline banner — shown when navigator.onLine === false */}
      <OfflineBanner />

      {/* Main scrolling screen */}
      <div
        style={{
          width: '100%',
          minHeight: '100svh',
          display: 'flex',
          flexDirection: 'column',
          alignItems: 'center',
        }}
      >
        {/* Top bar */}
        <TopBar />

        {/* Scrolling content, 720px max-width column */}
        <main
          style={{
            width: '100%',
            maxWidth: '720px',
            padding: '80px 16px 64px', // 80px = top-bar height clearance
            display: 'flex',
            flexDirection: 'column',
            gap: '0',
          }}
        >
          {/* Section B: Add-ingredient input */}
          <AddIngredientRow />

          {/* Section C: Pantry list */}
          <PantrySection />

          {/* Divider */}
          <hr
            aria-hidden="true"
            style={{
              border: 'none',
              borderTop: '1px solid var(--md-sys-color-outline-variant)',
              margin: '32px 0',
              opacity: 0.5,
            }}
          />

          {/* Section D: Recipes section (T-008) */}
          <RecipesSection />

          {/* Section E: AI helpers settings panel (T-014) */}
          <div style={{ marginTop: '48px' }}>
            <button
              type="button"
              className="link"
              onClick={() => setShowHelpers((v) => !v)}
              style={{
                background: 'none',
                border: 'none',
                cursor: 'pointer',
                fontFamily: 'var(--font)',
                fontSize: 'var(--md-sys-typescale-label-medium-size)',
                fontWeight: 'var(--md-sys-typescale-label-medium-weight)',
                color: 'var(--md-sys-color-on-surface-variant)',
                padding: '4px 0',
                textDecoration: 'underline',
                textUnderlineOffset: '3px',
              }}
            >
              {showHelpers ? 'Hide AI helpers' : 'AI helpers'}
            </button>
            {showHelpers && <AiHelpersPanel />}
          </div>
        </main>
      </div>

      {/* Overlay sheets — rendered outside the column */}
      <ModeSwitcher />
      <PhotoReviewSheet />
    </Fragment>
  )
}

// ---------------------------------------------------------------------------
// Section A: Top bar
// ---------------------------------------------------------------------------

function TopBar() {
  function openModeSwitcher() {
    modeSwitcherOpen.value = true
  }

  return (
    <header
      style={{
        position: 'fixed',
        top: 0,
        left: 0,
        right: 0,
        zIndex: 100,
        height: '64px',
        background: 'var(--md-sys-color-surface)',
        display: 'flex',
        alignItems: 'center',
        justifyContent: 'space-between',
        padding: '0 16px',
        // No shadow per spec — flat against gradient page background
      }}
    >
      {/* Brand wordmark — gradient clip */}
      <h1
        style={{
          fontFamily: 'var(--font)',
          fontSize: 'var(--md-sys-typescale-title-medium-size)',
          fontWeight: 'var(--md-sys-typescale-title-medium-weight)',
          lineHeight: 'var(--md-sys-typescale-title-medium-line-height)',
          letterSpacing: '-0.02em',
          background: 'var(--gradient-gemini)',
          WebkitBackgroundClip: 'text',
          WebkitTextFillColor: 'transparent',
          backgroundClip: 'text',
          color: 'transparent',
        }}
      >
        PantryAtlas
      </h1>

      {/* Mode chip — tap to open mode switcher */}
      <button
        type="button"
        onClick={() => openModeSwitcher()}
        aria-label={`Current mode: ${modeLabel.value}. Tap to change.`}
        style={{
          display: 'flex',
          alignItems: 'center',
          gap: '6px',
          padding: '6px 14px',
          borderRadius: 'var(--md-sys-shape-corner-full)',
          background: 'var(--md-sys-color-secondary-container)',
          color: 'var(--md-sys-color-on-secondary-container)',
          border: 'none',
          cursor: 'pointer',
          fontFamily: 'var(--font)',
          fontSize: 'var(--md-sys-typescale-label-medium-size)',
          fontWeight: 'var(--md-sys-typescale-label-medium-weight)',
          lineHeight: 'var(--md-sys-typescale-label-medium-line-height)',
          minHeight: '44px',
          transition: 'background 0.15s',
        }}
      >
        <span aria-hidden="true">{modeIcon.value}</span>
        <span>{modeLabel.value}</span>
      </button>
    </header>
  )
}

// ---------------------------------------------------------------------------
// Section B: Add-ingredient input (dual modality)
// ---------------------------------------------------------------------------

function AddIngredientRow() {
  const fileInputRef = useRef<HTMLInputElement>(null)
  const inputRef = useRef<HTMLInputElement>(null)
  const [isShaking, setIsShaking] = useState(false)

  const currentValue = addInputValue.value
  const state = addState.value
  const resolvedName = addResolvedName.value
  const errorMsg = addErrorMsg.value

  // Debounced resolve
  const debouncedResolve = useRef(
    debounce(async (text: string) => {
      if (!text.trim()) {
        addState.value = 'idle'
        return
      }
      addState.value = 'resolving'
      try {
        const res = await fetch('/navigator/pantry/resolve', {
          method: 'POST',
          headers: { 'Content-Type': 'application/json' },
          body: JSON.stringify({ raw: text.trim() }),
        })
        if (res.ok) {
          const data = await res.json()
          addResolvedName.value = data.canonical_name
          addState.value = 'resolved'
          addErrorMsg.value = ''
        } else {
          addState.value = 'error'
          addResolvedName.value = ''
          const raw = text.trim()
          addErrorMsg.value = `I don't know '${raw}' yet — try a simpler name?`
        }
      } catch {
        addState.value = 'idle'
      }
    }, 300)
  ).current

  function handleInput(e: Event) {
    const val = (e.target as HTMLInputElement).value
    addInputValue.value = val
    if (!val.trim()) {
      addState.value = 'idle'
      addErrorMsg.value = ''
      addResolvedName.value = ''
      return
    }
    debouncedResolve(val)
  }

  async function handleSubmit() {
    const raw = addInputValue.value.trim()
    if (!raw) return

    try {
      const result = await addItem(raw)
      if (result.ok) {
        addInputValue.value = ''
        addState.value = 'idle'
        addErrorMsg.value = ''
        addResolvedName.value = ''
        // fetchPantry() already called by addItem on online path;
        // offline path updates pantry signal directly.
      } else if (result.status === 422) {
        addState.value = 'error'
        addErrorMsg.value = `I don't know '${raw}' yet — try a simpler name?`
        triggerShake()
      }
    } catch {
      addState.value = 'error'
      addErrorMsg.value = 'Network error — please try again.'
      triggerShake()
    }
  }

  function triggerShake() {
    setIsShaking(true)
    setTimeout(() => setIsShaking(false), 500)
  }

  function handleKeyDown(e: KeyboardEvent) {
    if (e.key === 'Enter') {
      e.preventDefault()
      handleSubmit()
    }
  }

  function handleCameraClick() {
    fileInputRef.current?.click()
  }

  function handleFileChange(e: Event) {
    const file = (e.target as HTMLInputElement).files?.[0]
    if (!file) return
    photoFile.value = file
    photoSheetState.value = 'loading'
    photoSheetOpen.value = true
    // Reset file input so same file can be reselected
    ;(e.target as HTMLInputElement).value = ''
  }

  return (
    <div style={{ margin: '24px 0 28px' }}>
      {/* Pill input row */}
      <div
        style={{
          position: 'relative',
          display: 'flex',
          alignItems: 'center',
          height: '56px',
          borderRadius: 'var(--md-sys-shape-corner-full)',
          background: 'var(--md-sys-color-surface-container)',
          border: `1.5px solid var(--md-sys-color-outline-variant)`,
          animation: isShaking ? 'input-shake 0.4s ease-in-out' : 'none',
        }}
      >
        <style>{`
          @keyframes input-shake {
            0%, 100% { transform: translateX(0); }
            20% { transform: translateX(-4px); }
            40% { transform: translateX(4px); }
            60% { transform: translateX(-4px); }
            80% { transform: translateX(4px); }
          }
        `}</style>

        {/* Leading: thinking pulse + "+" icon */}
        <div
          aria-hidden="true"
          style={{
            position: 'relative',
            width: '44px',
            height: '56px',
            display: 'flex',
            alignItems: 'center',
            justifyContent: 'center',
            flexShrink: 0,
          }}
        >
          {/* Radial pulse behind the + icon during resolving */}
          {state === 'resolving' && (
            <div
              style={{
                position: 'absolute',
                width: '24px',
                height: '24px',
                borderRadius: 'var(--md-sys-shape-corner-full)',
                background: 'var(--gradient-thinking)',
                opacity: 0.7,
                animation: 'thinking-pulse 1.4s ease-in-out infinite',
              }}
            />
          )}
          <style>{`
            @keyframes thinking-pulse {
              0%, 100% { transform: scale(1); opacity: 0.6; }
              50% { transform: scale(1.06); opacity: 1; }
            }
            @media (prefers-reduced-motion: reduce) {
              @keyframes thinking-pulse { 0%, 100% { opacity: 0.7; } }
            }
          `}</style>
          <span
            style={{
              position: 'relative',
              fontSize: '20px',
              fontWeight: '600',
              color: 'var(--md-sys-color-primary)',
              lineHeight: 1,
              zIndex: 1,
            }}
          >
            +
          </span>
        </div>

        {/* Text input */}
        <input
          ref={inputRef}
          type="text"
          value={currentValue}
          onInput={handleInput}
          onKeyDown={handleKeyDown}
          placeholder="Add ingredient or take a photo..."
          aria-label="Add ingredient"
          style={{
            flex: 1,
            background: 'transparent',
            border: 'none',
            outline: 'none',
            fontFamily: 'var(--font)',
            fontSize: 'var(--md-sys-typescale-body-large-size)',
            color: 'var(--md-sys-color-on-surface)',
            padding: '0 4px',
          }}
        />

        {/* Trailing: camera icon button */}
        <button
          type="button"
          onClick={handleCameraClick}
          aria-label="Take a photo of your shelf"
          style={{
            width: '44px',
            height: '44px',
            borderRadius: 'var(--md-sys-shape-corner-full)',
            background: 'var(--md-sys-color-primary-container)',
            border: 'none',
            cursor: 'pointer',
            display: 'flex',
            alignItems: 'center',
            justifyContent: 'center',
            marginRight: '6px',
            flexShrink: 0,
            transition: 'background 0.15s',
          }}
        >
          {/* Camera icon — Material-style line glyph */}
          <svg
            width="22"
            height="22"
            viewBox="0 0 24 24"
            fill="none"
            aria-hidden="true"
          >
            <path
              d="M9 3H15L17 5H21C21.5523 5 22 5.44772 22 6V19C22 19.5523 21.5523 20 21 20H3C2.44772 20 2 19.5523 2 19V6C2 5.44772 2.44772 5 3 5H7L9 3Z"
              stroke="var(--md-sys-color-on-primary-container)"
              stroke-width="1.8"
              stroke-linecap="round"
              stroke-linejoin="round"
            />
            <circle
              cx="12"
              cy="12"
              r="3.5"
              stroke="var(--md-sys-color-on-primary-container)"
              stroke-width="1.8"
            />
          </svg>
        </button>

        {/* Hidden file input */}
        <input
          ref={fileInputRef}
          type="file"
          accept="image/*"
          capture="environment"
          onChange={handleFileChange}
          aria-hidden="true"
          tabIndex={-1}
          style={{ position: 'absolute', opacity: 0, width: 0, height: 0, pointerEvents: 'none' }}
        />
      </div>

      {/* Resolution chip — appears when resolved */}
      {state === 'resolved' && resolvedName && (
        <div
          style={{
            marginTop: '8px',
            display: 'flex',
            alignItems: 'center',
            gap: '8px',
          }}
        >
          <span
            style={{
              display: 'inline-flex',
              alignItems: 'center',
              gap: '6px',
              padding: '4px 14px',
              borderRadius: 'var(--md-sys-shape-corner-full)',
              background: 'var(--md-sys-color-primary-container)',
              color: 'var(--md-sys-color-on-primary-container)',
              fontFamily: 'var(--font)',
              fontSize: 'var(--md-sys-typescale-label-medium-size)',
              fontWeight: 'var(--md-sys-typescale-label-medium-weight)',
              animation: 'chip-settle 0.32s cubic-bezier(0.2,0,0,1)',
            }}
          >
            <style>{`
              @keyframes chip-settle {
                from { opacity: 0; transform: translateY(4px); }
                to   { opacity: 1; transform: translateY(0); }
              }
              @media (prefers-reduced-motion: reduce) {
                @keyframes chip-settle { from { opacity: 0; } to { opacity: 1; } }
              }
            `}</style>
            <span aria-hidden="true">✓</span>
            {resolvedName}
          </span>
          <span
            style={{
              fontFamily: 'var(--font)',
              fontSize: 'var(--md-sys-typescale-body-medium-size)',
              color: 'var(--md-sys-color-on-surface-variant)',
            }}
          >
            — press Enter to add
          </span>
        </div>
      )}

      {/* Error message — conversational tone */}
      {state === 'error' && errorMsg && (
        <p
          role="alert"
          style={{
            marginTop: '8px',
            fontFamily: 'var(--font)',
            fontSize: 'var(--md-sys-typescale-body-medium-size)',
            color: 'var(--md-sys-color-error)',
            padding: '8px 14px',
            background: 'var(--md-sys-color-error-container)',
            borderRadius: 'var(--md-sys-shape-corner-medium)',
          }}
        >
          {errorMsg}
        </p>
      )}
    </div>
  )
}

// ---------------------------------------------------------------------------
// Section C: Pantry list
// ---------------------------------------------------------------------------

function PantrySection() {
  const items = pantry.value
  const count = pantryCount.value

  return (
    <section aria-label="My pantry">
      {/* Section label */}
      <p
        style={{
          fontFamily: 'var(--font)',
          fontSize: 'var(--md-sys-typescale-label-medium-size)',
          fontWeight: 'var(--md-sys-typescale-label-medium-weight)',
          lineHeight: 'var(--md-sys-typescale-label-medium-line-height)',
          color: 'var(--md-sys-color-on-surface-variant)',
          marginBottom: '16px',
        }}
        aria-live="polite"
        aria-atomic="true"
      >
        My Pantry · {count} {count === 1 ? 'item' : 'items'}
      </p>

      {/* Empty state */}
      {items.length === 0 && <PantryEmptyState />}

      {/* Items list */}
      {items.length > 0 && (
        <ul
          style={{
            listStyle: 'none',
            display: 'flex',
            flexDirection: 'column',
            gap: '12px',
          }}
        >
          {items.map((item) => (
            <PantryCard key={item.canonical_name} item={item} />
          ))}
        </ul>
      )}
    </section>
  )
}

// ---------------------------------------------------------------------------
// Pantry card
// ---------------------------------------------------------------------------

interface PantryCardProps {
  item: {
    canonical_name: string
    raw_text: string
    expires_at?: string
    _pending?: boolean
  }
}

function PantryCard({ item }: PantryCardProps) {
  const days = daysUntilExpiry(item.expires_at)
  const isPending = item._pending === true

  // Expiry chip styling
  let expiryBg = 'var(--md-sys-color-secondary-container)'
  let expiryColor = 'var(--md-sys-color-on-secondary-container)'
  let expiryText = ''
  let expiryStrikethrough = false

  if (days !== null) {
    if (days >= 3) {
      expiryBg = 'var(--md-sys-color-secondary-container)'
      expiryColor = 'var(--md-sys-color-on-secondary-container)'
      expiryText = `${days} day${days !== 1 ? 's' : ''}`
    } else if (days === 2 || days === 1) {
      expiryBg = 'var(--md-sys-color-tertiary-container)'
      expiryColor = 'var(--md-sys-color-on-tertiary-container)'
      expiryText = days === 1 ? '1 day' : '2 days'
    } else if (days === 0) {
      expiryBg = 'var(--md-sys-color-error-container)'
      expiryColor = 'var(--md-sys-color-on-error-container)'
      expiryText = 'today'
    } else {
      // Expired
      expiryBg = 'var(--md-sys-color-error-container)'
      expiryColor = 'var(--md-sys-color-error)'
      expiryText = `${Math.abs(days)}d ago`
      expiryStrikethrough = true
    }
  }

  const showRaw = item.raw_text && item.raw_text.toLowerCase() !== item.canonical_name.toLowerCase()

  return (
    <li
      style={{
        borderRadius: 'var(--md-sys-shape-corner-extra-large)',
        background: 'var(--md-sys-color-surface-container)',
        boxShadow: 'var(--shadow-rest)',
        padding: '16px 20px',
        display: 'flex',
        alignItems: 'center',
        gap: '14px',
        transition: 'box-shadow 0.18s cubic-bezier(0.2,0,0,1)',
      }}
      onMouseEnter={(e) => {
        ;(e.currentTarget as HTMLLIElement).style.boxShadow = 'var(--shadow-active)'
      }}
      onMouseLeave={(e) => {
        ;(e.currentTarget as HTMLLIElement).style.boxShadow = 'var(--shadow-rest)'
      }}
    >
      {/* Leading icon vessel */}
      <div
        aria-hidden="true"
        style={{
          width: '40px',
          height: '40px',
          borderRadius: 'var(--md-sys-shape-corner-full)',
          background: 'var(--md-sys-color-surface-container-high)',
          display: 'flex',
          alignItems: 'center',
          justifyContent: 'center',
          flexShrink: 0,
        }}
      >
        {/* Generic pantry leaf icon */}
        <svg width="22" height="22" viewBox="0 0 24 24" fill="none" aria-hidden="true">
          <path
            d="M12 2C12 2 4 6 4 14C4 18.42 7.58 22 12 22C16.42 22 20 18.42 20 14C20 6 12 2 12 2Z"
            stroke="var(--md-sys-color-on-surface-variant)"
            stroke-width="1.8"
            stroke-linecap="round"
            stroke-linejoin="round"
            fill="none"
          />
          <path
            d="M12 22L12 8"
            stroke="var(--md-sys-color-on-surface-variant)"
            stroke-width="1.8"
            stroke-linecap="round"
          />
        </svg>
      </div>

      {/* Text body */}
      <div style={{ flex: 1, minWidth: 0 }}>
        <p
          style={{
            fontFamily: 'var(--font)',
            fontSize: 'var(--md-sys-typescale-title-small-size)',
            fontWeight: 'var(--md-sys-typescale-title-medium-weight)',
            lineHeight: 'var(--md-sys-typescale-title-medium-line-height)',
            color: 'var(--md-sys-color-on-surface)',
            whiteSpace: 'nowrap',
            overflow: 'hidden',
            textOverflow: 'ellipsis',
          }}
        >
          {item.canonical_name}
        </p>
        {showRaw && (
          <p
            style={{
              fontFamily: 'var(--font)',
              fontSize: 'var(--md-sys-typescale-body-small-size)',
              fontWeight: 'var(--md-sys-typescale-body-small-weight)',
              lineHeight: 'var(--md-sys-typescale-body-small-line-height)',
              color: 'var(--md-sys-color-on-surface-variant)',
              marginTop: '2px',
            }}
          >
            {item.raw_text}
          </p>
        )}
      </div>

      {/* Trailing: pending-sync chip + expiry chip + delete button */}
      <div style={{ display: 'flex', alignItems: 'center', gap: '8px', flexShrink: 0 }}>
        {/* Pending-sync indicator — shown for optimistic offline items */}
        {isPending && (
          <span
            data-testid="pending-sync"
            aria-label="Pending sync — will upload when back online"
            style={{
              display: 'inline-flex',
              alignItems: 'center',
              gap: '4px',
              padding: '3px 10px',
              borderRadius: 'var(--md-sys-shape-corner-full)',
              background: 'var(--md-sys-color-secondary-container)',
              color: 'var(--md-sys-color-on-secondary-container)',
              fontFamily: 'var(--font)',
              fontSize: 'var(--md-sys-typescale-label-small-size)',
              fontWeight: 'var(--md-sys-typescale-label-medium-weight)',
              whiteSpace: 'nowrap',
            }}
          >
            {/* Sync icon */}
            <svg width="12" height="12" viewBox="0 0 24 24" fill="none" aria-hidden="true">
              <path
                d="M1 4v6h6M23 20v-6h-6"
                stroke="currentColor"
                stroke-width="2"
                stroke-linecap="round"
                stroke-linejoin="round"
              />
              <path
                d="M20.49 9A9 9 0 0 0 5.64 5.64L1 10M23 14l-4.64 4.36A9 9 0 0 1 3.51 15"
                stroke="currentColor"
                stroke-width="2"
                stroke-linecap="round"
                stroke-linejoin="round"
              />
            </svg>
            pending sync
          </span>
        )}

        {/* Expiry chip */}
        {expiryText && (
          <span
            style={{
              display: 'inline-flex',
              alignItems: 'center',
              padding: '3px 10px',
              borderRadius: 'var(--md-sys-shape-corner-full)',
              background: expiryBg,
              color: expiryColor,
              fontFamily: 'var(--font)',
              fontSize: 'var(--md-sys-typescale-label-small-size)',
              fontWeight: 'var(--md-sys-typescale-label-medium-weight)',
              textDecoration: expiryStrikethrough ? 'line-through' : 'none',
              whiteSpace: 'nowrap',
            }}
          >
            {expiryText}
          </span>
        )}

        {/* Delete button — 44×44 touch target */}
        <button
          type="button"
          onClick={() => deleteItem(item.canonical_name)}
          aria-label={`Remove ${item.canonical_name} from pantry`}
          style={{
            width: '44px',
            height: '44px',
            borderRadius: 'var(--md-sys-shape-corner-full)',
            background: 'transparent',
            border: 'none',
            cursor: 'pointer',
            display: 'flex',
            alignItems: 'center',
            justifyContent: 'center',
            color: 'var(--md-sys-color-on-surface-variant)',
            transition: 'background 0.15s',
          }}
          onMouseEnter={(e) => {
            ;(e.currentTarget as HTMLButtonElement).style.background =
              'var(--md-sys-color-surface-container-high)'
          }}
          onMouseLeave={(e) => {
            ;(e.currentTarget as HTMLButtonElement).style.background = 'transparent'
          }}
        >
          {/* Delete/trash icon */}
          <svg width="20" height="20" viewBox="0 0 24 24" fill="none" aria-hidden="true">
            <path
              d="M3 6H21M8 6V4H16V6M19 6L18.2 19.1C18.09 20.16 17.2 21 16.14 21H7.86C6.8 21 5.91 20.16 5.8 19.1L5 6H19Z"
              stroke="currentColor"
              stroke-width="1.8"
              stroke-linecap="round"
              stroke-linejoin="round"
            />
          </svg>
        </button>
      </div>
    </li>
  )
}

// ---------------------------------------------------------------------------
// Pantry empty state
// ---------------------------------------------------------------------------

function PantryEmptyState() {
  return (
    <div
      style={{
        textAlign: 'center',
        padding: '48px 24px',
        display: 'flex',
        flexDirection: 'column',
        alignItems: 'center',
        gap: '16px',
      }}
    >
      {/* 96px circular vessel illustration */}
      <div
        class="vessel"
        aria-hidden="true"
        style={{
          width: '96px',
          height: '96px',
        }}
      >
        {/* Empty bowl SVG */}
        <svg width="52" height="52" viewBox="0 0 52 52" fill="none" aria-hidden="true">
          <ellipse cx="26" cy="32" rx="18" ry="8" stroke="white" stroke-width="2.2" fill="none" />
          <path d="M8 32 Q8 44 26 44 Q44 44 44 32" stroke="white" stroke-width="2.2" fill="none" stroke-linecap="round" />
          <path d="M26 20 L26 24" stroke="white" stroke-width="2.2" stroke-linecap="round" />
          <path d="M20 22 Q18 18 22 16" stroke="white" stroke-width="2" stroke-linecap="round" fill="none" />
          <path d="M32 22 Q34 18 30 16" stroke="white" stroke-width="2" stroke-linecap="round" fill="none" />
        </svg>
      </div>

      <p
        style={{
          fontFamily: 'var(--font)',
          fontSize: 'var(--md-sys-typescale-display-large-size)',
          fontWeight: 'var(--md-sys-typescale-display-large-weight)',
          lineHeight: 'var(--md-sys-typescale-display-large-line-height)',
          letterSpacing: 'var(--md-sys-typescale-display-large-tracking)',
          background: 'var(--gradient-gemini)',
          WebkitBackgroundClip: 'text',
          WebkitTextFillColor: 'transparent',
          backgroundClip: 'text',
          color: 'transparent',
        }}
      >
        Empty pantry
      </p>
      <p
        style={{
          fontFamily: 'var(--font)',
          fontSize: 'var(--md-sys-typescale-body-large-size)',
          color: 'var(--md-sys-color-on-surface-variant)',
          maxWidth: '280px',
        }}
      >
        Type something above — or tap the camera to photograph your shelf
      </p>
    </div>
  )
}

// ---------------------------------------------------------------------------
// Section D: Recipe list — T-008
// ---------------------------------------------------------------------------

function RecipesSection() {
  const ranked = recipes.value
  const loadState = recipeLoadState.value
  const refine = refineState.value
  const label = recipeSectionLabel.value

  return (
    <section aria-label={label} data-refine-state={refine}>
      {/* Section label — replaced by convergence spinner while loading */}
      {loadState === 'loading' ? (
        <RecipeConvergenceState />
      ) : (
        <p
          style={{
            display: 'flex',
            alignItems: 'center',
            gap: '8px',
            flexWrap: 'wrap',
            fontFamily: 'var(--font)',
            fontSize: 'var(--md-sys-typescale-label-medium-size)',
            fontWeight: 'var(--md-sys-typescale-label-medium-weight)',
            lineHeight: 'var(--md-sys-typescale-label-medium-line-height)',
            color: 'var(--md-sys-color-on-surface-variant)',
            marginBottom: '16px',
          }}
          aria-live="polite"
          aria-atomic="true"
        >
          <span>
            {ranked.length > 0 ? `${label} · ${ranked.length} found` : label}
          </span>
          {ranked.length > 0 && <RefineChip state={refine} />}
        </p>
      )}

      {/* Results */}
      {loadState !== 'loading' && ranked.length > 0 && (
        <ul
          style={{
            listStyle: 'none',
            display: 'flex',
            flexDirection: 'column',
            gap: '12px',
          }}
        >
          {ranked.map((r, i) => {
            // Max 6 staggered (60ms each), then batch (no delay)
            const delay = i < 6 ? i * 60 : 0
            // Stable key by recipe identity so refine re-ordering MOVES nodes
            // (preserving expand state) instead of recreating them.
            return (
              <RecipeCard key={recipeKey(r)} ranked={r} animDelay={delay} />
            )
          })}
        </ul>
      )}

      {/* Empty state — shown after first load returns zero results, or on idle */}
      {loadState !== 'loading' && ranked.length === 0 && (
        <RecipeEmptyState />
      )}
    </section>
  )
}

// ---------------------------------------------------------------------------
// Refine chip — subtle "refining…" / "offline" indicator beside the section label
// ---------------------------------------------------------------------------

function RefineChip({ state }: { state: typeof refineState.value }) {
  if (state === 'refining') {
    return (
      <span
        data-refine-chip="refining"
        style={{
          display: 'inline-flex',
          alignItems: 'center',
          gap: '6px',
          padding: '2px 10px',
          borderRadius: 'var(--md-sys-shape-corner-full)',
          background: 'var(--md-sys-color-primary-container)',
          color: 'var(--md-sys-color-on-primary-container)',
          fontSize: 'var(--md-sys-typescale-label-small-size)',
          fontWeight: 'var(--md-sys-typescale-label-small-weight)',
        }}
      >
        <style>{`
          @keyframes refine-pulse { 0%,100% { opacity: 0.35 } 50% { opacity: 1 } }
          @media (prefers-reduced-motion: reduce) {
            @keyframes refine-pulse { 0%,100% { opacity: 0.7 } }
          }
        `}</style>
        <span
          aria-hidden="true"
          style={{
            width: '6px',
            height: '6px',
            borderRadius: 'var(--md-sys-shape-corner-full)',
            background: 'currentColor',
            animation: 'refine-pulse 1.1s ease-in-out infinite',
          }}
        />
        refining…
      </span>
    )
  }
  if (state === 'offline') {
    return (
      <span
        data-refine-chip="offline"
        style={{
          display: 'inline-flex',
          alignItems: 'center',
          padding: '2px 10px',
          borderRadius: 'var(--md-sys-shape-corner-full)',
          background: 'var(--md-sys-color-surface-container-highest)',
          color: 'var(--md-sys-color-on-surface-variant)',
          fontSize: 'var(--md-sys-typescale-label-small-size)',
          fontWeight: 'var(--md-sys-typescale-label-small-weight)',
        }}
      >
        offline · coverage order
      </span>
    )
  }
  return null
}

// ---------------------------------------------------------------------------
// Convergence state — centered radial-pulse vessel + "Finding what works..."
// ---------------------------------------------------------------------------

function RecipeConvergenceState() {
  return (
    <div
      style={{
        textAlign: 'center',
        padding: '48px 24px',
        display: 'flex',
        flexDirection: 'column',
        alignItems: 'center',
        gap: '16px',
      }}
    >
      <style>{`
        @keyframes convergence-pulse {
          0%, 100% { transform: scale(1); opacity: 0.6; box-shadow: var(--shadow-vessel); }
          50% { transform: scale(1.06); opacity: 1; box-shadow: var(--shadow-bloom); }
        }
        @media (prefers-reduced-motion: reduce) {
          @keyframes convergence-pulse { 0%, 100% { opacity: 0.8; } }
        }
      `}</style>
      <div
        aria-hidden="true"
        style={{
          width: '96px',
          height: '96px',
          borderRadius: 'var(--md-sys-shape-corner-full)',
          background: 'var(--bloom-gemini)',
          animation: 'convergence-pulse 1.4s cubic-bezier(0.4,0,0.2,1) infinite',
        }}
      />
      <p
        style={{
          fontFamily: 'var(--font)',
          fontSize: 'var(--md-sys-typescale-body-large-size)',
          color: 'var(--md-sys-color-on-surface-variant)',
        }}
      >
        Finding what works...
      </p>
    </div>
  )
}

// ---------------------------------------------------------------------------
// Recipe empty state — plate vessel + sane-size headline + subtext
// ---------------------------------------------------------------------------

function RecipeEmptyState() {
  return (
    <div
      style={{
        textAlign: 'center',
        padding: '48px 24px',
        display: 'flex',
        flexDirection: 'column',
        alignItems: 'center',
        gap: '16px',
      }}
    >
      {/* 96px circular vessel — empty plate illustration */}
      <div
        class="vessel"
        aria-hidden="true"
        style={{ width: '96px', height: '96px' }}
      >
        <svg width="52" height="52" viewBox="0 0 52 52" fill="none" aria-hidden="true">
          <circle cx="26" cy="28" r="16" stroke="white" stroke-width="2.2" fill="none" />
          <ellipse cx="26" cy="28" rx="10" ry="10" stroke="white" stroke-width="1.5" fill="none" opacity="0.5" />
          <path d="M20 12 L20 18" stroke="white" stroke-width="2" stroke-linecap="round" />
          <path d="M26 10 L26 18" stroke="white" stroke-width="2" stroke-linecap="round" />
          <path d="M32 12 L32 18" stroke="white" stroke-width="2" stroke-linecap="round" />
        </svg>
      </div>

      {/* Headline — "headline" style (28sp/36sp), NOT display-large */}
      <p
        style={{
          fontFamily: 'var(--font)',
          fontSize: 'var(--md-sys-typescale-headline-medium-size)',
          fontWeight: 'var(--md-sys-typescale-headline-medium-weight)',
          lineHeight: 'var(--md-sys-typescale-headline-medium-line-height)',
          letterSpacing: 'var(--md-sys-typescale-headline-medium-tracking)',
          background: 'var(--gradient-gemini)',
          WebkitBackgroundClip: 'text',
          WebkitTextFillColor: 'transparent',
          backgroundClip: 'text',
          color: 'transparent',
        }}
      >
        Nothing matches yet
      </p>
      <p
        style={{
          fontFamily: 'var(--font)',
          fontSize: 'var(--md-sys-typescale-body-large-size)',
          color: 'var(--md-sys-color-on-surface-variant)',
          maxWidth: '280px',
        }}
      >
        Add more to your pantry on the shelf above
      </p>
    </div>
  )
}

// ---------------------------------------------------------------------------
// Exported placeholder (kept for backwards-compat; no longer called internally)
// ---------------------------------------------------------------------------

/** @deprecated T-008 replaced this with RecipesSection */
export function RecipesSectionPlaceholder() {
  return <RecipesSection />
}
