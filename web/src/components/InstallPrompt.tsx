import { h } from 'preact'
import { useState, useEffect } from 'preact/hooks'

// BeforeInstallPromptEvent is not in standard lib; declare it locally.
interface BeforeInstallPromptEvent extends Event {
  readonly platforms: string[];
  readonly userChoice: Promise<{ outcome: 'accepted' | 'dismissed'; platform: string }>;
  prompt(): Promise<void>;
}

/**
 * InstallPrompt — M3 filled-tonal button that surfaces the browser's
 * native PWA install prompt. Listens for `beforeinstallprompt`,
 * stashes the deferred event, and renders the prompt when ready.
 *
 * All colors use M3 design tokens (var(--md-sys-...)). No hardcoded hex.
 */
export function InstallPrompt() {
  const [deferredPrompt, setDeferredPrompt] = useState<BeforeInstallPromptEvent | null>(null)
  const [dismissed, setDismissed] = useState(false)

  useEffect(() => {
    const handler = (e: Event) => {
      e.preventDefault()
      setDeferredPrompt(e as BeforeInstallPromptEvent)
    }
    window.addEventListener('beforeinstallprompt', handler)
    return () => window.removeEventListener('beforeinstallprompt', handler)
  }, [])

  if (!deferredPrompt || dismissed) return null

  async function handleInstall() {
    if (!deferredPrompt) return
    await deferredPrompt.prompt()
    const { outcome } = await deferredPrompt.userChoice
    if (outcome === 'accepted' || outcome === 'dismissed') {
      setDeferredPrompt(null)
      setDismissed(true)
    }
  }

  function handleDismiss() {
    setDeferredPrompt(null)
    setDismissed(true)
  }

  return (
    <div
      role="banner"
      aria-label="Install PantryAtlas"
      style={{
        position: 'fixed',
        bottom: '24px',
        left: '50%',
        transform: 'translateX(-50%)',
        width: 'min(calc(100vw - 32px), 400px)',
        padding: '16px 20px',
        borderRadius: 'var(--md-sys-shape-corner-large)',
        background: 'var(--md-sys-color-surface-container-high)',
        border: '1px solid var(--md-sys-color-outline-variant)',
        boxShadow: 'var(--shadow-active)',
        display: 'flex',
        alignItems: 'center',
        gap: '16px',
        zIndex: 9999,
      }}
    >
      {/* Icon vessel */}
      <div
        aria-hidden="true"
        style={{
          width: '44px',
          height: '44px',
          borderRadius: 'var(--md-sys-shape-corner-medium)',
          background: 'var(--md-sys-color-primary-container)',
          flexShrink: 0,
          display: 'flex',
          alignItems: 'center',
          justifyContent: 'center',
        }}
      >
        <svg
          width="24"
          height="24"
          viewBox="0 0 24 24"
          fill="none"
          aria-hidden="true"
        >
          {/* Bowl icon */}
          <path
            d="M5 12 H19 A7 7 0 0 1 5 12 Z"
            fill="var(--md-sys-color-on-primary-container)"
          />
          <ellipse
            cx="12"
            cy="12"
            rx="7"
            ry="1.4"
            fill="var(--md-sys-color-on-primary-container)"
            opacity="0.5"
          />
          <rect
            x="10"
            y="18"
            width="4"
            height="2"
            rx="1"
            fill="var(--md-sys-color-on-primary-container)"
          />
          {/* Sparkle */}
          <path
            d="M18 4l.8 2.8 2.8.8-2.8.8L18 11l-.8-2.8L14.4 7.6l2.8-.8L18 4z"
            fill="var(--md-sys-color-on-primary-container)"
          />
        </svg>
      </div>

      {/* Text content */}
      <div style={{ flex: 1, minWidth: 0 }}>
        <p
          style={{
            margin: 0,
            fontFamily: 'var(--font)',
            fontSize: 'var(--md-sys-typescale-label-large-size)',
            fontWeight: 'var(--md-sys-typescale-label-large-weight)',
            lineHeight: 'var(--md-sys-typescale-label-large-line-height)',
            color: 'var(--md-sys-color-on-surface)',
          }}
        >
          Add to Home Screen
        </p>
        <p
          style={{
            margin: '2px 0 0',
            fontFamily: 'var(--font)',
            fontSize: 'var(--md-sys-typescale-body-small-size)',
            fontWeight: 'var(--md-sys-typescale-body-small-weight)',
            lineHeight: 'var(--md-sys-typescale-body-small-line-height)',
            color: 'var(--md-sys-color-on-surface-variant)',
            whiteSpace: 'nowrap',
            overflow: 'hidden',
            textOverflow: 'ellipsis',
          }}
        >
          Cook what you have — works offline
        </p>
      </div>

      {/* Actions */}
      <div style={{ display: 'flex', gap: '8px', flexShrink: 0 }}>
        {/* Dismiss — text button */}
        <button
          type="button"
          onClick={handleDismiss}
          aria-label="Dismiss install prompt"
          style={{
            background: 'transparent',
            border: 'none',
            cursor: 'pointer',
            padding: '8px 4px',
            fontFamily: 'var(--font)',
            fontSize: 'var(--md-sys-typescale-label-large-size)',
            fontWeight: 'var(--md-sys-typescale-label-large-weight)',
            color: 'var(--md-sys-color-on-surface-variant)',
            borderRadius: 'var(--md-sys-shape-corner-small)',
          }}
        >
          Not now
        </button>

        {/* Install — M3 filled-tonal button */}
        <button
          type="button"
          onClick={handleInstall}
          aria-label="Install PantryAtlas as an app"
          style={{
            background: 'var(--md-sys-color-secondary-container)',
            color: 'var(--md-sys-color-on-secondary-container)',
            border: 'none',
            cursor: 'pointer',
            padding: '10px 20px',
            borderRadius: 'var(--md-sys-shape-corner-full)',
            fontFamily: 'var(--font)',
            fontSize: 'var(--md-sys-typescale-label-large-size)',
            fontWeight: 'var(--md-sys-typescale-label-large-weight)',
            lineHeight: 'var(--md-sys-typescale-label-large-line-height)',
            letterSpacing: '0.01em',
            transition: 'filter 0.15s ease',
          }}
          onMouseEnter={(e) => {
            ;(e.currentTarget as HTMLButtonElement).style.filter = 'brightness(0.92)'
          }}
          onMouseLeave={(e) => {
            ;(e.currentTarget as HTMLButtonElement).style.filter = ''
          }}
        >
          Install
        </button>
      </div>
    </div>
  )
}
