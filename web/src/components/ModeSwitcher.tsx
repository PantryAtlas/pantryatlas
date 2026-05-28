import { h } from 'preact'
import { mode, setMode, modeSwitcherOpen } from '../signals'
import type { Mode } from '../signals'

/**
 * ModeSwitcher — bottom sheet on mobile, centered dialog on desktop.
 * Two large mode options: Home Kitchen / Community Kitchen.
 * Selection persists via localStorage (via setMode in signals.ts).
 */
export function ModeSwitcher() {
  const isOpen = modeSwitcherOpen.value
  if (!isOpen) return null

  function selectMode(m: Mode) {
    setMode(m)
    modeSwitcherOpen.value = false
  }

  function handleBackdropClick(e: MouseEvent) {
    if ((e.target as HTMLElement).dataset.backdrop) {
      modeSwitcherOpen.value = false
    }
  }

  const currentMode = mode.value

  return (
    <div
      data-backdrop="true"
      onClick={handleBackdropClick}
      role="dialog"
      aria-modal="true"
      aria-label="How are you cooking?"
      style={{
        position: 'fixed',
        inset: 0,
        zIndex: 200,
        display: 'flex',
        alignItems: 'flex-end',
        justifyContent: 'center',
        background: 'rgba(0,0,0,0.35)',
        backdropFilter: 'blur(2px)',
        padding: '0',
      }}
    >
      {/* Desktop: centered dialog wrapper */}
      <style>{`
        @media (min-width: 720px) {
          .mode-sheet-inner {
            border-radius: var(--md-sys-shape-corner-extra-large) !important;
            max-width: 480px !important;
            margin-bottom: auto !important;
            margin-top: auto !important;
          }
          .mode-drag-handle { display: none !important; }
        }
      `}</style>

      <div
        class="mode-sheet-inner"
        style={{
          background: 'var(--md-sys-color-surface)',
          borderRadius: 'var(--md-sys-shape-corner-extra-large) var(--md-sys-shape-corner-extra-large) 0 0',
          boxShadow: 'var(--shadow-active)',
          width: '100%',
          maxWidth: '600px',
          padding: '0 24px 40px',
        }}
      >
        {/* Drag handle — mobile only */}
        <div
          class="mode-drag-handle"
          aria-hidden="true"
          style={{
            width: '32px',
            height: '4px',
            borderRadius: 'var(--md-sys-shape-corner-full)',
            background: 'var(--md-sys-color-outline-variant)',
            margin: '12px auto 0',
          }}
        />

        {/* Title */}
        <h2
          style={{
            fontFamily: 'var(--font)',
            fontSize: 'var(--md-sys-typescale-headline-medium-size)',
            fontWeight: 'var(--md-sys-typescale-headline-medium-weight)',
            lineHeight: 'var(--md-sys-typescale-headline-medium-line-height)',
            letterSpacing: 'var(--md-sys-typescale-headline-medium-tracking)',
            color: 'var(--md-sys-color-on-surface)',
            margin: '24px 0 20px',
            textAlign: 'center',
          }}
        >
          How are you cooking?
        </h2>

        {/* Mode options */}
        <div style={{ display: 'flex', flexDirection: 'column', gap: '12px' }}>
          <ModeOption
            icon="🏠"
            label="Home Kitchen"
            sublabel="4 to 10 servings"
            modeKey="home"
            selected={currentMode === 'home'}
            onSelect={selectMode}
          />
          <ModeOption
            icon="🍲"
            label="Community Kitchen"
            sublabel="50 to 500 servings"
            modeKey="community"
            selected={currentMode === 'community'}
            onSelect={selectMode}
          />
        </div>

        {/* Footer */}
        <p
          style={{
            textAlign: 'center',
            marginTop: '20px',
            fontFamily: 'var(--font)',
            fontSize: 'var(--md-sys-typescale-body-small-size)',
            fontWeight: 'var(--md-sys-typescale-body-small-weight)',
            color: 'var(--md-sys-color-on-surface-variant)',
          }}
        >
          You can change this anytime from the top bar.
        </p>
      </div>
    </div>
  )
}

// ---------------------------------------------------------------------------
// ModeOption — one large pill button
// ---------------------------------------------------------------------------

interface ModeOptionProps {
  icon: string
  label: string
  sublabel: string
  modeKey: Mode
  selected: boolean
  onSelect: (m: Mode) => void
}

function ModeOption({ icon, label, sublabel, modeKey, selected, onSelect }: ModeOptionProps) {
  return (
    <button
      type="button"
      onClick={() => onSelect(modeKey)}
      aria-pressed={selected}
      style={{
        display: 'flex',
        alignItems: 'center',
        gap: '20px',
        padding: '0 24px',
        height: '80px',
        borderRadius: 'var(--md-sys-shape-corner-full)',
        border: 'none',
        cursor: 'pointer',
        width: '100%',
        textAlign: 'left',
        background: selected
          ? 'var(--gradient-ember)'
          : 'var(--md-sys-color-surface-container)',
        color: selected
          ? 'var(--md-sys-color-on-primary)'
          : 'var(--md-sys-color-on-surface)',
        boxShadow: selected ? 'var(--shadow-rest)' : 'none',
        transition: 'background 0.2s, box-shadow 0.2s',
        fontFamily: 'var(--font)',
      }}
    >
      {/* Leading vessel illustration */}
      <div
        aria-hidden="true"
        style={{
          width: '48px',
          height: '48px',
          borderRadius: 'var(--md-sys-shape-corner-full)',
          background: selected
            ? 'rgba(255,255,255,0.22)'
            : 'var(--md-sys-color-surface-container-high)',
          display: 'flex',
          alignItems: 'center',
          justifyContent: 'center',
          fontSize: '24px',
          flexShrink: 0,
        }}
      >
        {icon}
      </div>

      {/* Label + sublabel */}
      <div>
        <div
          style={{
            fontSize: 'var(--md-sys-typescale-title-medium-size)',
            fontWeight: 'var(--md-sys-typescale-title-medium-weight)',
            lineHeight: '1.3',
          }}
        >
          {label}
        </div>
        <div
          style={{
            fontSize: 'var(--md-sys-typescale-label-medium-size)',
            fontWeight: 'var(--md-sys-typescale-label-medium-weight)',
            opacity: selected ? 0.85 : 0.7,
            marginTop: '2px',
          }}
        >
          {sublabel}
        </div>
      </div>
    </button>
  )
}
