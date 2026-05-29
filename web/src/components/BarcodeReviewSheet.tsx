import { h } from 'preact'
import { useState, useEffect } from 'preact/hooks'
import { barcodeSheetOpen, barcodeCandidate, barcodeState, confirmBarcodeAdd } from '../signals'

/**
 * BarcodeReviewSheet — bottom sheet (mobile) / centered modal (desktop).
 *
 * Flow:
 * 1. User captures a barcode photo → postBarcode() sets barcodeSheetOpen + barcodeState.
 * 2. Sheet opens; shows scanning spinner while the backend decodes + OFF lookup runs.
 * 3. On success (found=true) → shows product name + editable canonical ingredient.
 * 4. On not-found or error → shows friendly message.
 * 5. "Add to pantry" → confirmBarcodeAdd() → adds with source:"barcode", closes sheet.
 */
export function BarcodeReviewSheet() {
  const isOpen = barcodeSheetOpen.value
  if (!isOpen) return null

  const state = barcodeState.value
  const cand = barcodeCandidate.value
  const [canonical, setCanonical] = useState('')

  useEffect(() => {
    if (cand?.proposed) setCanonical(cand.proposed.canonical_name)
  }, [cand?.proposed?.canonical_name])

  function close() {
    barcodeSheetOpen.value = false
  }

  function handleBackdrop(e: MouseEvent) {
    if ((e.target as HTMLElement).dataset.backdrop) close()
  }

  return (
    <div
      data-backdrop="true"
      data-barcode-sheet="true"
      onClick={handleBackdrop}
      role="dialog"
      aria-modal="true"
      aria-label="Barcode review"
      style={{
        position: 'fixed',
        inset: 0,
        zIndex: 200,
        display: 'flex',
        alignItems: 'flex-end',
        justifyContent: 'center',
        background: 'rgba(0,0,0,0.45)',
        backdropFilter: 'blur(2px)',
      }}
    >
      <style>{`
        @media (min-width: 720px) {
          .barcode-sheet-inner {
            border-radius: var(--md-sys-shape-corner-extra-large) !important;
            max-width: 560px !important;
            margin-bottom: auto !important;
            margin-top: auto !important;
            max-height: 90vh !important;
          }
          .barcode-drag-handle { display: none !important; }
        }
      `}</style>

      <div
        class="barcode-sheet-inner"
        onClick={(e) => e.stopPropagation()}
        style={{
          background: 'var(--md-sys-color-surface)',
          borderRadius: 'var(--md-sys-shape-corner-extra-large) var(--md-sys-shape-corner-extra-large) 0 0',
          boxShadow: 'var(--shadow-active)',
          width: '100%',
          maxWidth: '600px',
          maxHeight: '90vh',
          overflowY: 'auto',
          display: 'flex',
          flexDirection: 'column',
        }}
      >
        {/* Drag handle */}
        <div
          class="barcode-drag-handle"
          aria-hidden="true"
          style={{
            width: '32px',
            height: '4px',
            borderRadius: 'var(--md-sys-shape-corner-full)',
            background: 'var(--md-sys-color-outline-variant)',
            margin: '12px auto 0',
            flexShrink: 0,
          }}
        />

        {/* Body */}
        <div style={{ padding: '20px 24px 28px', flex: 1 }}>

          {/* Scanning state */}
          {state === 'scanning' && (
            <div style={{ textAlign: 'center', padding: '16px 0' }}>
              <div
                aria-hidden="true"
                style={{
                  width: '64px',
                  height: '64px',
                  borderRadius: 'var(--md-sys-shape-corner-full)',
                  background: 'var(--gradient-thinking)',
                  margin: '0 auto 16px',
                  animation: 'barcode-pulse 1.4s ease-in-out infinite',
                  boxShadow: 'var(--shadow-vessel)',
                }}
              />
              <style>{`
                @keyframes barcode-pulse {
                  0%, 100% { transform: scale(1); opacity: 0.7; }
                  50% { transform: scale(1.06); opacity: 1; }
                }
                @media (prefers-reduced-motion: reduce) {
                  @keyframes barcode-pulse { 0%, 100% { opacity: 0.7; } }
                }
              `}</style>
              <p
                data-barcode-status="scanning"
                style={{
                  fontFamily: 'var(--font)',
                  fontSize: 'var(--md-sys-typescale-body-large-size)',
                  color: 'var(--md-sys-color-on-surface-variant)',
                }}
              >
                Reading barcode…
              </p>
            </div>
          )}

          {/* Error state */}
          {state === 'error' && (
            <div>
              <p
                data-barcode-status="error"
                style={{
                  fontFamily: 'var(--font)',
                  fontSize: 'var(--md-sys-typescale-body-large-size)',
                  color: 'var(--md-sys-color-error)',
                  background: 'var(--md-sys-color-error-container)',
                  borderRadius: 'var(--md-sys-shape-corner-medium)',
                  padding: '14px',
                }}
              >
                Couldn't read a barcode. Try again, or add the item by typing it.
              </p>
              <div style={{ marginTop: '16px', display: 'flex', justifyContent: 'center' }}>
                <button
                  type="button"
                  onClick={close}
                  style={{
                    height: '48px',
                    padding: '0 28px',
                    borderRadius: 'var(--md-sys-shape-corner-full)',
                    border: 'none',
                    background: 'var(--md-sys-color-surface-container)',
                    fontFamily: 'var(--font)',
                    fontSize: 'var(--md-sys-typescale-label-large-size)',
                    fontWeight: 'var(--md-sys-typescale-label-large-weight)',
                    color: 'var(--md-sys-color-on-surface)',
                    cursor: 'pointer',
                  }}
                >
                  Dismiss
                </button>
              </div>
            </div>
          )}

          {/* Ready: not found */}
          {state === 'ready' && cand && !cand.found && (
            <div>
              <p
                data-barcode-status="notfound"
                style={{
                  fontFamily: 'var(--font)',
                  fontSize: 'var(--md-sys-typescale-body-large-size)',
                  color: 'var(--md-sys-color-on-surface-variant)',
                  background: 'var(--md-sys-color-surface-container)',
                  borderRadius: 'var(--md-sys-shape-corner-medium)',
                  padding: '16px',
                  lineHeight: '1.6',
                }}
              >
                Barcode {cand.code} isn't in Open Food Facts{cand.error === 'off_unavailable' ? ' (offline)' : ''}.
                Add it by typing the item instead.
              </p>
              <div style={{ marginTop: '16px', display: 'flex', justifyContent: 'center' }}>
                <button
                  type="button"
                  onClick={close}
                  style={{
                    height: '48px',
                    padding: '0 28px',
                    borderRadius: 'var(--md-sys-shape-corner-full)',
                    border: 'none',
                    background: 'var(--md-sys-color-surface-container)',
                    fontFamily: 'var(--font)',
                    fontSize: 'var(--md-sys-typescale-label-large-size)',
                    fontWeight: 'var(--md-sys-typescale-label-large-weight)',
                    color: 'var(--md-sys-color-on-surface)',
                    cursor: 'pointer',
                  }}
                >
                  Got it
                </button>
              </div>
            </div>
          )}

          {/* Ready: found */}
          {state === 'ready' && cand && cand.found && cand.proposed && (
            <div
              data-barcode-status="found"
              style={{ display: 'flex', flexDirection: 'column', gap: '12px' }}
            >
              <p
                style={{
                  fontFamily: 'var(--font)',
                  fontSize: 'var(--md-sys-typescale-title-medium-size)',
                  fontWeight: 'var(--md-sys-typescale-title-medium-weight)',
                  color: 'var(--md-sys-color-on-surface)',
                }}
              >
                {cand.product?.name}{cand.product?.brand ? ` · ${cand.product.brand}` : ''}
              </p>

              <label
                style={{
                  fontFamily: 'var(--font)',
                  fontSize: 'var(--md-sys-typescale-label-medium-size)',
                  color: 'var(--md-sys-color-on-surface-variant)',
                  display: 'block',
                }}
              >
                Store as (pantry ingredient):
                <input
                  data-barcode-canonical
                  type="text"
                  value={canonical}
                  onInput={(e) => setCanonical((e.target as HTMLInputElement).value)}
                  style={{
                    display: 'block',
                    width: '100%',
                    marginTop: '6px',
                    padding: '10px 14px',
                    borderRadius: 'var(--md-sys-shape-corner-medium)',
                    border: '1px solid var(--md-sys-color-outline)',
                    fontFamily: 'var(--font)',
                    fontSize: 'var(--md-sys-typescale-body-large-size)',
                    color: 'var(--md-sys-color-on-surface)',
                    background: 'var(--md-sys-color-surface-container-low)',
                    boxSizing: 'border-box',
                  }}
                />
              </label>

              {!cand.proposed.matched && (
                <span
                  style={{
                    fontFamily: 'var(--font)',
                    fontSize: 'var(--md-sys-typescale-label-small-size)',
                    color: 'var(--md-sys-color-on-surface-variant)',
                  }}
                >
                  We couldn't auto-match this to a known ingredient — edit if needed.
                </span>
              )}

              {/* Action row */}
              <div style={{ display: 'flex', gap: '12px', marginTop: '8px' }}>
                <button
                  type="button"
                  onClick={close}
                  style={{
                    flex: 1,
                    height: '48px',
                    borderRadius: 'var(--md-sys-shape-corner-full)',
                    border: '1.5px solid var(--md-sys-color-outline-variant)',
                    background: 'transparent',
                    fontFamily: 'var(--font)',
                    fontSize: 'var(--md-sys-typescale-label-large-size)',
                    fontWeight: 'var(--md-sys-typescale-label-large-weight)',
                    color: 'var(--md-sys-color-on-surface)',
                    cursor: 'pointer',
                  }}
                >
                  Cancel
                </button>
                <button
                  type="button"
                  data-barcode-add
                  onClick={() => confirmBarcodeAdd(cand.product?.name || canonical, canonical)}
                  disabled={!canonical.trim()}
                  style={{
                    flex: 1,
                    height: '48px',
                    borderRadius: 'var(--md-sys-shape-corner-full)',
                    border: 'none',
                    background: 'var(--gradient-ember)',
                    fontFamily: 'var(--font)',
                    fontSize: 'var(--md-sys-typescale-label-large-size)',
                    fontWeight: 'var(--md-sys-typescale-label-large-weight)',
                    color: 'var(--md-sys-color-on-primary)',
                    cursor: 'pointer',
                  }}
                >
                  Add to pantry
                </button>
              </div>
            </div>
          )}

        </div>
      </div>
    </div>
  )
}
