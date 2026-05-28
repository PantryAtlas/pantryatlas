#!/usr/bin/env node
/*
 * apply-brand.mjs — materialize the active PantryAtlas logo variant onto every
 * static brand surface (favicons + PWA icons + the marketing header mark).
 *
 * The logo system has a PRIMARY mark (Coverage Dial) and a SECONDARY mark
 * (Spark Bowl) staged for preview builds. Source artwork + the primary/secondary
 * declaration live in web/brand/ (see brand.config.json). This script is the one
 * place that decides which variant the shipped assets use.
 *
 *   # default: render the primary (Coverage Dial) onto all surfaces
 *   node ops/brand/apply-brand.mjs
 *
 *   # preview build: stage the secondary (Spark Bowl) instead
 *   BRAND_VARIANT=spark-bowl node ops/brand/apply-brand.mjs
 *   #   ...and build the app with the matching mark:
 *   VITE_BRAND_VARIANT=spark-bowl npm --prefix web run build
 *
 * To PROMOTE the secondary to primary permanently, swap "primary"/"secondary"
 * in web/brand/brand.config.json and re-run this script with no env override.
 *
 * Run before building/deploying the app, the marketing site, or the docs site.
 * Idempotent: re-running with the same variant reproduces identical output.
 *
 * PNG icon rasterization uses rsvg-convert; if it is missing the SVG surfaces
 * are still written and the PNG step is skipped with a warning.
 */

import { readFileSync, writeFileSync } from 'node:fs'
import { execFileSync } from 'node:child_process'
import { resolve, dirname } from 'node:path'
import { fileURLToPath } from 'node:url'

const REPO = resolve(dirname(fileURLToPath(import.meta.url)), '../..')
const BRAND = resolve(REPO, 'web/brand')

const config = JSON.parse(readFileSync(resolve(BRAND, 'brand.config.json'), 'utf8'))
const requested = process.env.BRAND_VARIANT || config.primary
const variant = config.variants[requested]
if (!variant) {
  console.error(
    `[brand] unknown variant "${requested}". Known: ${Object.keys(config.variants).join(', ')}`,
  )
  process.exit(1)
}
const role = requested === config.primary ? 'primary' : 'secondary'
console.log(`[brand] applying "${requested}" (${variant.name}, ${role})`)

const tileSvg = readFileSync(resolve(BRAND, variant.tile), 'utf8')
const tileMaskableSvg = readFileSync(resolve(BRAND, variant.tileMaskable), 'utf8')
// Marketing header consumes the mark as an <img>; <img> SVGs don't inherit page
// color, so bake the ink body color in place of currentColor (gradient accent
// is already absolute).
const headerMarkSvg = readFileSync(resolve(BRAND, variant.mark), 'utf8').replaceAll(
  'currentColor',
  '#1A1B22',
)

// ── favicons (one tile, three surfaces) ──────────────────────────────────────
const faviconTargets = [
  'web/public/favicon.svg',
  'web/marketing/site/assets/favicon.svg',
  'web/docs/public/favicon.svg',
]
for (const rel of faviconTargets) {
  writeFileSync(resolve(REPO, rel), tileSvg)
  console.log(`[brand] favicon  → ${rel}`)
}

// ── marketing header mark ────────────────────────────────────────────────────
{
  const rel = 'web/marketing/site/assets/brand-mark.svg'
  writeFileSync(resolve(REPO, rel), headerMarkSvg)
  console.log(`[brand] header   → ${rel}`)
}

// ── PWA icons (rasterized) ───────────────────────────────────────────────────
function hasRsvg() {
  try {
    execFileSync('rsvg-convert', ['--version'], { stdio: 'ignore' })
    return true
  } catch {
    return false
  }
}

const pngJobs = [
  { src: variant.tile, out: 'web/public/icons/icon-192.png', size: 192 },
  { src: variant.tile, out: 'web/public/icons/icon-512.png', size: 512 },
  { src: variant.tileMaskable, out: 'web/public/icons/icon-192-maskable.png', size: 192 },
  { src: variant.tileMaskable, out: 'web/public/icons/icon-512-maskable.png', size: 512 },
]

if (hasRsvg()) {
  for (const job of pngJobs) {
    const src = resolve(BRAND, job.src)
    const out = resolve(REPO, job.out)
    execFileSync('rsvg-convert', ['-w', String(job.size), '-h', String(job.size), src, '-o', out])
    console.log(`[brand] icon     → ${job.out} (${job.size}px)`)
  }
} else {
  console.warn('[brand] rsvg-convert not found — skipped PNG icons. Install librsvg2-bin to regenerate them.')
}

console.log(`[brand] done — "${requested}" applied.`)
