import { h } from 'preact'
import { useEffect, useRef } from 'preact/hooks'

/**
 * CoverageRing — SVG ring showing ingredient coverage fraction.
 *
 * - Gradient stroke using cool-Gemini design tokens (no literal hex values).
 * - Track in outline-variant, center fraction text.
 * - Animates stroke-dashoffset on entry; respects prefers-reduced-motion.
 *
 * Usage:
 *   <CoverageRing present={8} total={10} size={80} />
 *   → shows "8/10" ring with 80% arc filled
 */

interface CoverageRingProps {
  /** Number of ingredients present in pantry */
  present: number
  /** Total number of ingredients in recipe */
  total: number
  /** Diameter in px (80 on mobile, 64 on desktop) */
  size?: number
  /** Optional extra className / style — not used internally */
  class?: string
}

export function CoverageRing({ present, total, size = 80 }: CoverageRingProps) {
  const strokeWidth = 8
  const radius = (size - strokeWidth) / 2
  const circumference = 2 * Math.PI * radius
  const fraction = total > 0 ? Math.min(1, present / total) : 0
  const targetDash = fraction * circumference

  // Unique id per instance for linearGradient defs
  const idRef = useRef(`cr-${Math.random().toString(36).slice(2, 8)}`)
  const id = idRef.current

  // Stroke animation ref
  const strokeRef = useRef<SVGCircleElement>(null)

  useEffect(() => {
    const el = strokeRef.current
    if (!el) return
    // Respect prefers-reduced-motion
    const reducedMotion = window.matchMedia('(prefers-reduced-motion: reduce)').matches
    if (reducedMotion) {
      el.style.strokeDashoffset = String(circumference - targetDash)
      el.style.opacity = '1'
      return
    }
    // Animate from full-offset (empty) to targetDash
    el.style.strokeDashoffset = String(circumference)
    el.style.opacity = '0'
    el.style.transition = 'none'
    requestAnimationFrame(() => {
      requestAnimationFrame(() => {
        el.style.transition = 'stroke-dashoffset 600ms cubic-bezier(0.2,0,0,1), opacity 200ms'
        el.style.strokeDashoffset = String(circumference - targetDash)
        el.style.opacity = '1'
      })
    })
  }, [present, total, circumference, targetDash])

  const cx = size / 2
  const cy = size / 2

  return (
    <svg
      width={size}
      height={size}
      viewBox={`0 0 ${size} ${size}`}
      aria-hidden="true"
      style={{
        flexShrink: 0,
        display: 'block',
        overflow: 'visible',
      }}
    >
      <defs>
        {/* Gradient stroke — cool Gemini tokens via CSS vars referenced via stop-color */}
        <linearGradient id={`${id}-grad`} x1="0%" y1="0%" x2="100%" y2="100%">
          <stop offset="0%" stop-color="var(--gemini-blue)" />
          <stop offset="40%" stop-color="var(--gemini-indigo)" />
          <stop offset="70%" stop-color="var(--gemini-purple)" />
          <stop offset="100%" stop-color="var(--gemini-magenta)" />
        </linearGradient>

        {/* Vessel radial fill for ring interior */}
        <radialGradient id={`${id}-vessel`} cx="50%" cy="40%" r="60%">
          <stop offset="0%" stop-color="var(--gemini-purple)" stop-opacity="0.18" />
          <stop offset="60%" stop-color="var(--gemini-blue)" stop-opacity="0.08" />
          <stop offset="100%" stop-color="var(--gemini-blue)" stop-opacity="0" />
        </radialGradient>
      </defs>

      {/* Vessel fill behind the ring */}
      <circle
        cx={cx}
        cy={cy}
        r={radius - strokeWidth / 2}
        fill={`url(#${id}-vessel)`}
      />

      {/* Track ring — outline-variant token */}
      <circle
        cx={cx}
        cy={cy}
        r={radius}
        fill="none"
        stroke="var(--md-sys-color-outline-variant)"
        stroke-width={strokeWidth}
        stroke-linecap="round"
      />

      {/* Coverage arc — gradient stroke, animated */}
      <circle
        ref={strokeRef}
        cx={cx}
        cy={cy}
        r={radius}
        fill="none"
        stroke={`url(#${id}-grad)`}
        stroke-width={strokeWidth}
        stroke-linecap="round"
        stroke-dasharray={circumference}
        stroke-dashoffset={circumference} // JS overrides this
        transform={`rotate(-90 ${cx} ${cy})`}
        style={{ opacity: 0 }}
      />

      {/* Center text: fraction */}
      <text
        x={cx}
        y={cy}
        dominant-baseline="central"
        text-anchor="middle"
        style={{
          fontFamily: 'var(--font)',
          fontSize: size <= 64 ? 'var(--md-sys-typescale-label-medium-size)' : 'var(--md-sys-typescale-title-small-size)',
          fontWeight: 'var(--md-sys-typescale-title-medium-weight)',
          fill: 'var(--md-sys-color-on-tertiary-container)',
        }}
      >
        {`${present}/${total}`}
      </text>
    </svg>
  )
}
