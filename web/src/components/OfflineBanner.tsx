/**
 * PantryAtlas — OfflineBanner component
 *
 * Shows a fixed banner using cool-Gemini design tokens when the browser
 * detects it is offline. Listens to the window 'online'/'offline' events.
 * Hidden (no DOM height) when online.
 *
 * Token contract: all colours via var(--md-sys-color-*) or var(--gemini-*) /
 * var(--gradient-*) — no hardcoded hex values.
 */

import { h } from 'preact';
import { useState, useEffect } from 'preact/hooks';

// ---------------------------------------------------------------------------
// OfflineBanner
// ---------------------------------------------------------------------------

export function OfflineBanner() {
  const [offline, setOffline] = useState(!navigator.onLine);

  useEffect(() => {
    function handleOnline() {
      setOffline(false);
    }
    function handleOffline() {
      setOffline(true);
    }
    window.addEventListener('online', handleOnline);
    window.addEventListener('offline', handleOffline);
    return () => {
      window.removeEventListener('online', handleOnline);
      window.removeEventListener('offline', handleOffline);
    };
  }, []);

  if (!offline) return null;

  return (
    <>
      <style>{`
        @keyframes offline-slide-in {
          from { transform: translateY(-100%); opacity: 0; }
          to   { transform: translateY(0);    opacity: 1; }
        }
        @media (prefers-reduced-motion: reduce) {
          @keyframes offline-slide-in {
            from { opacity: 0; }
            to   { opacity: 1; }
          }
        }
      `}</style>
      <div
        role="status"
        aria-live="polite"
        aria-label="Offline status"
        data-testid="offline-banner"
        style={{
          position: 'fixed',
          top: '64px', // below the fixed top-bar (64px height)
          left: 0,
          right: 0,
          zIndex: 200,
          display: 'flex',
          alignItems: 'center',
          justifyContent: 'center',
          gap: '8px',
          padding: '10px 16px',
          background: 'var(--md-sys-color-surface-container-high)',
          borderBottom: `1px solid var(--md-sys-color-outline-variant)`,
          fontFamily: 'var(--font)',
          fontSize: 'var(--md-sys-typescale-label-medium-size)',
          fontWeight: 'var(--md-sys-typescale-label-medium-weight)',
          lineHeight: 'var(--md-sys-typescale-label-medium-line-height)',
          color: 'var(--md-sys-color-on-surface)',
          animation: 'offline-slide-in 0.22s cubic-bezier(0.2,0,0,1)',
        }}
      >
        {/* Offline cloud icon */}
        <svg
          width="18"
          height="18"
          viewBox="0 0 24 24"
          fill="none"
          aria-hidden="true"
          style={{ flexShrink: 0, color: 'var(--gemini-indigo)' }}
        >
          <path
            d="M3 3L21 21"
            stroke="var(--md-sys-color-error)"
            stroke-width="1.8"
            stroke-linecap="round"
          />
          <path
            d="M17.5 17.5H6.5C4.567 17.5 3 15.933 3 14C3 12.244 4.316 10.793 6.02 10.534C6.007 10.356 6 10.179 6 10C6 7.239 8.239 5 11 5C12.879 5 14.514 6.019 15.391 7.537"
            stroke="var(--gemini-indigo)"
            stroke-width="1.8"
            stroke-linecap="round"
            stroke-linejoin="round"
          />
          <path
            d="M21 14C21 15.933 19.433 17.5 17.5 17.5"
            stroke="var(--gemini-indigo)"
            stroke-width="1.8"
            stroke-linecap="round"
          />
        </svg>

        {/* Banner text */}
        <span>
          Offline — showing cached results
        </span>
      </div>
    </>
  );
}
