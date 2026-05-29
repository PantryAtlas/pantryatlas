import { h } from 'preact'
import { useEffect, useRef } from 'preact/hooks'
import {
  photoSheetOpen,
  photoFile,
  photoSheetState,
  photoDetectedItems,
  photoErrorMsg,
  fetchPantry,
} from '../signals'
import { parseShelfOnDevice, onDeviceTelemetry, isOnDeviceEnabled } from '../ondevice/parseShelfOnDevice'

/**
 * PhotoReviewSheet — bottom sheet (mobile) / centered modal (desktop).
 *
 * Flow:
 * 1. File is set in photoFile signal.
 * 2. Sheet opens, POSTs to /navigator/vision/parse-shelf (multipart).
 * 3. If 404/503/network error → shows graceful degradation message.
 * 4. If success → shows checklist of detected items.
 * 5. "Add to pantry" → resolves + adds all checked items, re-fetches pantry.
 */
export function PhotoReviewSheet() {
  const isOpen = photoSheetOpen.value
  if (!isOpen) return null

  const file = photoFile.value
  const sheetState = photoSheetState.value
  const detectedItems = photoDetectedItems.value
  const errorMsg = photoErrorMsg.value
  const telemetry = onDeviceTelemetry.value

  const objectUrl = useRef<string>('')

  // Revoke previous object URL to avoid memory leaks
  useEffect(() => {
    if (file) {
      objectUrl.current = URL.createObjectURL(file)
      if (isOnDeviceEnabled()) {
        parseShelfOnDevice(file) // runs SmolVLM in-browser; sets the same signals
      } else {
        postToVision(file)
      }
    }
    return () => {
      if (objectUrl.current) URL.revokeObjectURL(objectUrl.current)
    }
  }, [file])

  function close() {
    photoSheetOpen.value = false
    photoFile.value = null
    photoSheetState.value = 'loading'
    photoDetectedItems.value = []
    photoErrorMsg.value = ''
  }

  function handleBackdrop(e: MouseEvent) {
    if ((e.target as HTMLElement).dataset.backdrop) close()
  }

  function toggleItem(index: number) {
    photoDetectedItems.value = photoDetectedItems.value.map((item, i) =>
      i === index ? { ...item, checked: !item.checked } : item
    )
  }

  function updateLabel(index: number, label: string) {
    photoDetectedItems.value = photoDetectedItems.value.map((item, i) =>
      i === index ? { ...item, label } : item
    )
  }

  async function handleAddToPantry() {
    const checked = photoDetectedItems.value.filter((it) => it.checked)
    for (const item of checked) {
      try {
        await fetch('/navigator/pantry/items', {
          method: 'POST',
          headers: { 'Content-Type': 'application/json' },
          body: JSON.stringify({ raw_text: item.label }),
        })
      } catch {
        // continue adding others
      }
    }
    await fetchPantry()
    close()
  }

  function handleRetake() {
    // Re-trigger file input — just close and let the user tap camera again
    close()
  }

  return (
    <div
      data-backdrop="true"
      onClick={handleBackdrop}
      role="dialog"
      aria-modal="true"
      aria-label="Photo review"
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
          .photo-sheet-inner {
            border-radius: var(--md-sys-shape-corner-extra-large) !important;
            max-width: 560px !important;
            margin-bottom: auto !important;
            margin-top: auto !important;
            max-height: 90vh !important;
          }
          .photo-drag-handle { display: none !important; }
        }
      `}</style>

      <div
        class="photo-sheet-inner"
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
          class="photo-drag-handle"
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

        {/* Captured photo with gradient-vessel halo */}
        {file && objectUrl.current && (
          <div
            style={{
              position: 'relative',
              margin: '16px 16px 0',
              borderRadius: 'var(--md-sys-shape-corner-large)',
              overflow: 'hidden',
              maxHeight: '240px',
              background: 'var(--bloom-gemini), #5566d8',
            }}
          >
            <img
              src={objectUrl.current}
              alt="Captured shelf photo"
              style={{
                width: '100%',
                height: '240px',
                objectFit: 'cover',
                display: 'block',
                borderRadius: 'var(--md-sys-shape-corner-large)',
              }}
            />
          </div>
        )}

        {/* Body */}
        <div style={{ padding: '20px 24px 28px', flex: 1 }}>
          {/* Loading state */}
          {sheetState === 'loading' && (
            <div style={{ textAlign: 'center', padding: '16px 0' }}>
              <div
                aria-hidden="true"
                style={{
                  width: '64px',
                  height: '64px',
                  borderRadius: 'var(--md-sys-shape-corner-full)',
                  background: 'var(--gradient-thinking)',
                  margin: '0 auto 16px',
                  animation: 'photo-pulse 1.4s ease-in-out infinite',
                  boxShadow: 'var(--shadow-vessel)',
                }}
              />
              <style>{`
                @keyframes photo-pulse {
                  0%, 100% { transform: scale(1); opacity: 0.7; }
                  50% { transform: scale(1.06); opacity: 1; }
                }
                @media (prefers-reduced-motion: reduce) {
                  @keyframes photo-pulse { 0%, 100% { opacity: 0.7; } }
                }
              `}</style>
              <p
                style={{
                  fontFamily: 'var(--font)',
                  fontSize: 'var(--md-sys-typescale-body-large-size)',
                  color: 'var(--md-sys-color-on-surface-variant)',
                }}
              >
                {isOnDeviceEnabled() ? 'Reading your shelf on this phone…' : 'Reading your shelf...'}
              </p>
            </div>
          )}

          {/* Graceful degradation: endpoint not available */}
          {sheetState === 'unavailable' && (
            <div>
              <p
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
                Photo recognition isn't set up on this server yet — type ingredients for now.
              </p>
              <div style={{ marginTop: '20px', display: 'flex', justifyContent: 'center' }}>
                <button
                  type="button"
                  onClick={close}
                  class="btn"
                  style={{
                    background: 'var(--md-sys-color-surface-container)',
                    color: 'var(--md-sys-color-on-surface)',
                    border: 'none',
                    fontFamily: 'var(--font)',
                    fontSize: 'var(--md-sys-typescale-label-large-size)',
                    fontWeight: 'var(--md-sys-typescale-label-large-weight)',
                    padding: '12px 28px',
                    borderRadius: 'var(--md-sys-shape-corner-full)',
                    cursor: 'pointer',
                  }}
                >
                  Got it
                </button>
              </div>
            </div>
          )}

          {/* Parsed items checklist */}
          {sheetState === 'parsed' && (
            <div>
              {telemetry && (
                <p
                  style={{
                    fontFamily: 'var(--font)',
                    fontSize: 'var(--md-sys-typescale-label-small-size, 11px)',
                    color: 'var(--md-sys-color-on-surface-variant)',
                    margin: '0 0 10px',
                    opacity: 0.8,
                  }}
                >
                  On-device · {telemetry.backend} · load {telemetry.loadMs}ms · infer {telemetry.inferMs}ms · {telemetry.model}
                </p>
              )}
              <p
                style={{
                  fontFamily: 'var(--font)',
                  fontSize: 'var(--md-sys-typescale-body-large-size)',
                  color: 'var(--md-sys-color-on-surface)',
                  marginBottom: '16px',
                }}
              >
                Found {detectedItems.length} items — uncheck anything that's not yours
              </p>
              <ul style={{ listStyle: 'none', display: 'flex', flexDirection: 'column', gap: '8px', marginBottom: '24px' }}>
                {detectedItems.map((item, i) => (
                  <li
                    key={i}
                    style={{
                      display: 'flex',
                      alignItems: 'center',
                      gap: '12px',
                      padding: '10px 14px',
                      background: 'var(--md-sys-color-surface-container-low)',
                      borderRadius: 'var(--md-sys-shape-corner-medium)',
                    }}
                  >
                    <input
                      type="checkbox"
                      checked={item.checked}
                      onChange={() => toggleItem(i)}
                      aria-label={`Include ${item.label}`}
                      style={{ width: '20px', height: '20px', accentColor: 'var(--md-sys-color-primary)', flexShrink: 0 }}
                    />
                    <input
                      type="text"
                      value={item.label}
                      onInput={(e) => updateLabel(i, (e.target as HTMLInputElement).value)}
                      aria-label={`Edit item ${i + 1} label`}
                      style={{
                        flex: 1,
                        background: 'transparent',
                        border: 'none',
                        borderBottom: '1px solid var(--md-sys-color-outline-variant)',
                        fontFamily: 'var(--font)',
                        fontSize: 'var(--md-sys-typescale-body-large-size)',
                        color: 'var(--md-sys-color-on-surface)',
                        padding: '2px 4px',
                        outline: 'none',
                      }}
                    />
                  </li>
                ))}
              </ul>

              {/* Action row */}
              <div style={{ display: 'flex', gap: '12px' }}>
                <button
                  type="button"
                  onClick={handleRetake}
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
                  Retake photo
                </button>
                <button
                  type="button"
                  onClick={handleAddToPantry}
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

          {/* Error state */}
          {sheetState === 'error' && (
            <div>
              <p
                style={{
                  fontFamily: 'var(--font)',
                  fontSize: 'var(--md-sys-typescale-body-large-size)',
                  color: 'var(--md-sys-color-error)',
                  background: 'var(--md-sys-color-error-container)',
                  borderRadius: 'var(--md-sys-shape-corner-medium)',
                  padding: '14px',
                }}
              >
                {errorMsg || "Something went wrong reading your photo — try again or type ingredients instead."}
              </p>
              <div style={{ marginTop: '16px', display: 'flex', gap: '12px' }}>
                <button type="button" onClick={handleRetake} style={{ flex: 1, height: '48px', borderRadius: 'var(--md-sys-shape-corner-full)', border: '1.5px solid var(--md-sys-color-outline-variant)', background: 'transparent', fontFamily: 'var(--font)', fontSize: 'var(--md-sys-typescale-label-large-size)', fontWeight: 'var(--md-sys-typescale-label-large-weight)', cursor: 'pointer', color: 'var(--md-sys-color-on-surface)' }}>Retake</button>
                <button type="button" onClick={close} style={{ flex: 1, height: '48px', borderRadius: 'var(--md-sys-shape-corner-full)', border: 'none', background: 'var(--md-sys-color-surface-container)', fontFamily: 'var(--font)', fontSize: 'var(--md-sys-typescale-label-large-size)', fontWeight: 'var(--md-sys-typescale-label-large-weight)', cursor: 'pointer', color: 'var(--md-sys-color-on-surface)' }}>Dismiss</button>
              </div>
            </div>
          )}
        </div>
      </div>
    </div>
  )
}

// ---------------------------------------------------------------------------
// Vision POST (module-level helper so it can be called from useEffect)
// ---------------------------------------------------------------------------

async function postToVision(file: File) {
  try {
    const fd = new FormData()
    fd.append('image', file)
    const res = await fetch('/navigator/vision/parse-shelf', {
      method: 'POST',
      body: fd,
    })
    if (res.status === 404 || res.status === 503) {
      photoSheetState.value = 'unavailable'
      return
    }
    if (!res.ok) {
      photoSheetState.value = 'unavailable'
      return
    }
    const data = await res.json()
    // Expected: { items: string[] }
    const items: string[] = Array.isArray(data.items) ? data.items : []
    photoDetectedItems.value = items.map((label) => ({ label, checked: true }))
    photoSheetState.value = 'parsed'
  } catch {
    // Network error / missing endpoint → graceful degrade
    photoSheetState.value = 'unavailable'
  }
}
