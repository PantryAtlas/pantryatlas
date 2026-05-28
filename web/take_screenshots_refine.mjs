/**
 * Screenshot script for the instant→refine→swaps flow.
 * puppeteer-core + system Chromium against the mock backend, which serves the
 * built PWA on the same origin (port 8099) and adds a delay to /refine so the
 * "refining…" chip is captured mid-flight.
 *
 * Captures:
 *   1. instant + refining chip (coverage order, Butternut on top)
 *   2. settled (refined order — Garlic Kale re-ordered above Butternut)
 *   3. expanded card with smart-swap lines (match + no-match)
 *   4. desktop settled
 *   5. dark settled
 */
import { createRequire } from 'module'
const require = createRequire(import.meta.url)
const puppeteer = require('/tmp/node_modules/puppeteer-core/lib/cjs/puppeteer/puppeteer-core.js')

const ORIGIN = 'http://127.0.0.1:8099'
const CHROMIUM = '/usr/bin/chromium'

function sleep(ms) {
  return new Promise((r) => setTimeout(r, ms))
}

// Pantry chosen so instant (coverage) order ≠ refined order:
//  Butternut & Kale Stew  → coverage 7/10 = 0.70  (instant #1)
//  Garlic Kale Stir-Fry   → coverage 4/7  = 0.57  (instant #2)
// After refine, Butternut's missing (nutmeg/chili/lemon) have no close swap
// → high penalty → it drops below Garlic Kale. Visible settle.
function richPantry() {
  const today = new Date()
  const iso = (d) => d.toISOString().slice(0, 10)
  const tomorrow = new Date(today.getTime() + 86400000)
  return [
    { canonical_name: 'butternut squash', raw_text: 'butternut squash' },
    { canonical_name: 'kale', raw_text: 'wilting kale', expires_at: iso(today) },
    { canonical_name: 'garlic', raw_text: 'garlic', expires_at: iso(tomorrow) },
    { canonical_name: 'onion', raw_text: 'onion' },
    { canonical_name: 'vegetable broth', raw_text: 'vegetable broth' },
    { canonical_name: 'olive oil', raw_text: 'olive oil' },
    { canonical_name: 'black pepper', raw_text: 'black pepper' },
  ]
}

async function makePage(width, height, darkMode = false) {
  const browser = await puppeteer.launch({
    executablePath: CHROMIUM,
    headless: 'new',
    args: [
      '--no-sandbox',
      '--disable-setuid-sandbox',
      '--disable-dev-shm-usage',
      '--disable-gpu',
      `--window-size=${width},${height}`,
    ],
    defaultViewport: { width, height },
  })
  const page = await browser.newPage()
  // Set mode (skip the first-launch switcher) and disable the SW so the
  // multi-call refine/swaps flow is never served from cache during capture.
  await page.evaluateOnNewDocument(() => {
    try {
      localStorage.setItem('pantryatlas.mode', 'home')
    } catch {}
    Object.defineProperty(navigator, 'serviceWorker', {
      configurable: true,
      get: () => ({ register: () => Promise.resolve(undefined), ready: new Promise(() => {}) }),
    })
  })
  if (darkMode) {
    await page.emulateMediaFeatures([{ name: 'prefers-color-scheme', value: 'dark' }])
  }
  return { browser, page }
}

async function main() {
  console.log('Seeding rich pantry on mock backend...')
  const put = await fetch(`${ORIGIN}/navigator/pantry`, {
    method: 'PUT',
    headers: { 'Content-Type': 'application/json' },
    body: JSON.stringify(richPantry()),
  })
  if (!put.ok) throw new Error(`pantry PUT failed: ${put.status}`)

  // -------------------------------------------------------------------------
  // 1: instant + refining chip (cards in coverage order: Butternut #1)
  // -------------------------------------------------------------------------
  {
    const { browser, page } = await makePage(390, 844)
    await page.goto(ORIGIN, { waitUntil: 'networkidle0', timeout: 20000 })
    // Wait for the refining chip to appear (refine is in flight, ~1.2s window)
    await page.waitForSelector('[data-refine-chip="refining"]', { timeout: 12000 })
    await page.screenshot({ path: '/tmp/refine-instant-mobile.png', fullPage: true })
    const instantOrder = await page.$$eval('li[role="article"]', (els) =>
      els.map((e) => e.getAttribute('aria-label')?.split(',')[0]),
    )
    await browser.close()
    console.log('  ✓ /tmp/refine-instant-mobile.png  instant order:', instantOrder.join(' | '))
  }

  // -------------------------------------------------------------------------
  // 2: settled (refined order — Garlic Kale re-ordered above Butternut)
  // -------------------------------------------------------------------------
  {
    const { browser, page } = await makePage(390, 844)
    await page.goto(ORIGIN, { waitUntil: 'networkidle0', timeout: 20000 })
    await page.waitForSelector('section[data-refine-state="refined"]', { timeout: 12000 })
    await sleep(500) // let the re-order settle
    await page.screenshot({ path: '/tmp/refine-settled-mobile.png', fullPage: true })
    const settledOrder = await page.$$eval('li[role="article"]', (els) =>
      els.map((e) => e.getAttribute('aria-label')?.split(',')[0]),
    )
    await browser.close()
    console.log('  ✓ /tmp/refine-settled-mobile.png  settled order:', settledOrder.join(' | '))
  }

  // -------------------------------------------------------------------------
  // 3: expanded card with smart-swap lines
  // -------------------------------------------------------------------------
  {
    const { browser, page } = await makePage(390, 844)
    await page.goto(ORIGIN, { waitUntil: 'networkidle0', timeout: 20000 })
    await page.waitForSelector('section[data-refine-state="refined"]', { timeout: 12000 })
    await sleep(300)
    const cards = await page.$$('li[role="article"]')
    if (!cards.length) throw new Error('no recipe cards to expand')
    await cards[0].click()
    // Wait for at least one swap line to resolve (match or no-match)
    await page.waitForSelector('[data-swap-line]', { timeout: 8000 })
    await sleep(400)
    await page.screenshot({ path: '/tmp/refine-expanded-swaps-mobile.png', fullPage: true })
    const swapLines = await page.$$eval('[data-swap-line]', (els) =>
      els.map((e) => e.getAttribute('data-swap-line') + ': ' + e.textContent?.trim()),
    )
    await browser.close()
    console.log('  ✓ /tmp/refine-expanded-swaps-mobile.png  swaps:', JSON.stringify(swapLines))
  }

  // -------------------------------------------------------------------------
  // 4: desktop settled (single centered column)
  // -------------------------------------------------------------------------
  {
    const { browser, page } = await makePage(1280, 800)
    await page.goto(ORIGIN, { waitUntil: 'networkidle0', timeout: 20000 })
    await page.waitForSelector('section[data-refine-state="refined"]', { timeout: 12000 })
    await sleep(500)
    await page.screenshot({ path: '/tmp/refine-settled-desktop.png', fullPage: true })
    await browser.close()
    console.log('  ✓ /tmp/refine-settled-desktop.png')
  }

  // -------------------------------------------------------------------------
  // 5: dark settled
  // -------------------------------------------------------------------------
  {
    const { browser, page } = await makePage(390, 844, true)
    await page.goto(ORIGIN, { waitUntil: 'networkidle0', timeout: 20000 })
    await page.waitForSelector('section[data-refine-state="refined"]', { timeout: 12000 })
    await sleep(500)
    await page.screenshot({ path: '/tmp/refine-settled-dark.png', fullPage: true })
    await browser.close()
    console.log('  ✓ /tmp/refine-settled-dark.png')
  }

  const { statSync } = await import('fs')
  for (const f of [
    '/tmp/refine-instant-mobile.png',
    '/tmp/refine-settled-mobile.png',
    '/tmp/refine-expanded-swaps-mobile.png',
    '/tmp/refine-settled-desktop.png',
    '/tmp/refine-settled-dark.png',
  ]) {
    try {
      console.log(`  ${f}: ${Math.round(statSync(f).size / 1024)}KB`)
    } catch {
      console.log(`  ${f}: MISSING`)
    }
  }
}

main().catch((err) => {
  console.error(err)
  process.exit(1)
})
