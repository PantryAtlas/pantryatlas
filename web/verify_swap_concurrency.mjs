/**
 * Regression check for the swaps-during-pantry-mutation bug:
 * expand a card (swaps load) → add an UNRELATED ingredient → the cleared swap
 * cache must re-resolve, not stick on "finding a swap…".
 */
import { createRequire } from 'module'
const require = createRequire(import.meta.url)
const puppeteer = require('/tmp/node_modules/puppeteer-core/lib/cjs/puppeteer/puppeteer-core.js')

const ORIGIN = 'http://127.0.0.1:8099'
const CHROMIUM = '/usr/bin/chromium'
const sleep = (ms) => new Promise((r) => setTimeout(r, ms))

function richPantry() {
  return [
    { canonical_name: 'butternut squash', raw_text: 'butternut squash' },
    { canonical_name: 'kale', raw_text: 'kale' },
    { canonical_name: 'garlic', raw_text: 'garlic' },
    { canonical_name: 'onion', raw_text: 'onion' },
    { canonical_name: 'vegetable broth', raw_text: 'vegetable broth' },
    { canonical_name: 'olive oil', raw_text: 'olive oil' },
    { canonical_name: 'black pepper', raw_text: 'black pepper' },
  ]
}

async function readSwapLines(page) {
  return page.$$eval('[data-swap-line]', (els) => els.map((e) => e.textContent?.trim()))
}

async function main() {
  await fetch(`${ORIGIN}/navigator/pantry`, {
    method: 'PUT',
    headers: { 'Content-Type': 'application/json' },
    body: JSON.stringify(richPantry()),
  })

  const browser = await puppeteer.launch({
    executablePath: CHROMIUM,
    headless: 'new',
    args: ['--no-sandbox', '--disable-setuid-sandbox', '--disable-dev-shm-usage', '--disable-gpu'],
    defaultViewport: { width: 390, height: 844 },
  })
  const page = await browser.newPage()
  await page.evaluateOnNewDocument(() => {
    try { localStorage.setItem('pantryatlas.mode', 'home') } catch {}
    Object.defineProperty(navigator, 'serviceWorker', {
      configurable: true,
      get: () => ({ register: () => Promise.resolve(undefined), ready: new Promise(() => {}) }),
    })
  })
  await page.goto(ORIGIN, { waitUntil: 'networkidle0', timeout: 20000 })
  await page.waitForSelector('section[data-refine-state="refined"]', { timeout: 12000 })

  // Expand the top card and wait for swaps to resolve.
  const cards = await page.$$('li[role="article"]')
  await cards[0].click()
  await page.waitForSelector('[data-swap-line]', { timeout: 8000 })
  await sleep(400)
  const before = await readSwapLines(page)
  console.log('swaps before mutation:', JSON.stringify(before))
  if (before.some((s) => s?.includes('finding'))) {
    throw new Error('FAIL: swaps stuck on "finding…" before mutation')
  }

  // Add an UNRELATED ingredient (tomato is in mock vocab, not in this recipe).
  // This clears the swap cache + aborts the in-flight swap fetch.
  await page.type('input[placeholder^="Add ingredient"]', 'tomato')
  await sleep(400) // let the resolve debounce settle
  await page.keyboard.press('Enter')

  // Pantry mutation → list unmounts during recompute (card collapses) → settle.
  await sleep(1400)
  await page.waitForSelector('section[data-refine-state="refined"]', { timeout: 12000 })
  await sleep(300)

  // Re-expand the top card; the cleared cache must trigger a FRESH swap fetch
  // that resolves (not a stale cached entry, not stuck on "finding…").
  const cards2 = await page.$$('li[role="article"]')
  if (!cards2.length) throw new Error('FAIL: no cards after mutation')
  await cards2[0].click()
  await page.waitForSelector('[data-swap-line]', { timeout: 8000 })
  await page.waitForFunction(
    () =>
      !Array.from(document.querySelectorAll('[data-swap-line]')).some((e) =>
        (e.textContent || '').includes('finding'),
      ),
    { timeout: 8000 },
  )
  const after = await readSwapLines(page)
  console.log('swaps after re-expand:', JSON.stringify(after))
  await page.screenshot({ path: '/tmp/refine-swaps-after-mutation.png', fullPage: true })
  await browser.close()

  if (after.length === 0) throw new Error('FAIL: no swap lines after re-expand')
  if (after.some((s) => s?.includes('finding'))) {
    throw new Error('FAIL: swaps STUCK on "finding…" after re-expand (the bug)')
  }
  console.log('PASS: swap cache cleared + re-resolved fresh after pantry mutation')
}

main().catch((err) => {
  console.error(err)
  process.exit(1)
})
