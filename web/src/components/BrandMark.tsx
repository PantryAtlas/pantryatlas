/// <reference types="vite/client" />
import { h } from 'preact'

// Canonical brand artwork lives in web/brand/ (single source of truth shared
// with the favicons + PWA icons). The in-app mark is consumed as a raw SVG
// string so there's no duplicate path data between this component and the
// static asset files.
import dialAccent from '../../brand/marks/coverage-dial-accent.svg?raw'
import dialSolid from '../../brand/marks/coverage-dial-solid.svg?raw'
import sparkAccent from '../../brand/marks/spark-bowl-accent.svg?raw'
import sparkSolid from '../../brand/marks/spark-bowl-solid.svg?raw'

export type BrandVariant = 'coverage-dial' | 'spark-bowl'

/**
 * Active logo variant. Defaults to the primary mark (Coverage Dial). Preview
 * builds opt into the secondary mark with `VITE_BRAND_VARIANT=spark-bowl`.
 * Keep in sync with web/brand/brand.config.json + ops/brand/apply-brand.mjs.
 */
export const ACTIVE_VARIANT: BrandVariant =
  import.meta.env.VITE_BRAND_VARIANT === 'spark-bowl' ? 'spark-bowl' : 'coverage-dial'

const MARKS: Record<BrandVariant, { accent: string; solid: string }> = {
  'coverage-dial': { accent: dialAccent, solid: dialSolid },
  'spark-bowl': { accent: sparkAccent, solid: sparkSolid },
}

interface BrandMarkProps {
  /** Rendered square size in px */
  size?: number
  /** 'accent' = flat body (currentColor) + Gemini gradient accent; 'solid' = single color */
  tone?: 'accent' | 'solid'
  /** CSS color for the flat body / single-color form */
  color?: string
  /** Override the active variant (rarely needed) */
  variant?: BrandVariant
  /** Accessible label; omit to mark decorative */
  title?: string
}

export function BrandMark({
  size = 28,
  tone = 'accent',
  color = 'var(--md-sys-color-on-surface)',
  variant = ACTIVE_VARIANT,
  title,
}: BrandMarkProps) {
  const svg = tone === 'solid' ? MARKS[variant].solid : MARKS[variant].accent
  return (
    <span
      class="brand-mark"
      role={title ? 'img' : undefined}
      aria-label={title}
      aria-hidden={title ? undefined : 'true'}
      style={{
        display: 'inline-flex',
        width: `${size}px`,
        height: `${size}px`,
        color,
        flexShrink: 0,
      }}
      dangerouslySetInnerHTML={{ __html: svg }}
    />
  )
}
