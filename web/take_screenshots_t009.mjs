/**
 * T-009 screenshot + verify script.
 * Tests: online banner hidden, offline banner visible, offline pending items,
 *        reconnect sync (pending gone), cap test (25 → 20 entries).
 *
 * Requires:
 *   - vite preview on port 5174 (npm run preview)
 *   - mock backend on port 8099 (python mock_backend.py)
 *   - puppeteer-core at /tmp/node_modules
 *   - chromium at /usr/bin/chromium
 */
import { createRequire } from 'module'
const require = createRequire(import.meta.url)
const puppeteer = require('/tmp/node_modules/puppeteer-core/lib/cjs/puppeteer/puppeteer-core.js')

const BASE = 'http://127.0.0.1:5174'
const CHROMIUM = '/usr/bin/chromium'
const MOCK_BASE = 'http://127.0.0.1:8099'

async function sleep(ms) {
  return new Promise((r) => setTimeout(r, ms))
}

async function makePage(width = 390, height = 844) {
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
  return { browser, page }
}

async function setupPage(page) {
  // Intercept /navigator/* → forward to mock backend at 8099
  // (vite preview doesn't proxy like dev server does)
  await page.setRequestInterception(true)
  page.on('request', async (req) => {
    const url = req.url()
    if (url.includes('/navigator/')) {
      const backendUrl = url.replace('http://127.0.0.1:5174', MOCK_BASE)
      try {
        const method = req.method()
        const headers = req.headers()
        const postData = req.postData()
        const fetchOpts = { method, headers }
        if (postData) fetchOpts.body = postData
        // Use native fetch in Node.js 18+
        const resp = await fetch(backendUrl, fetchOpts)
        const body = await resp.arrayBuffer()
        const respHeaders = {}
        resp.headers.forEach((v, k) => { respHeaders[k] = v })
        await req.respond({
          status: resp.status,
          headers: respHeaders,
          body: Buffer.from(body),
        })
      } catch (err) {
        // Backend unreachable → network error (simulates offline for API)
        await req.abort('failed')
      }
    } else {
      req.continue()
    }
  })
  await page.goto(BASE, { waitUntil: 'networkidle0', timeout: 20000 })
  await page.evaluate(() => {
    localStorage.setItem('pantryatlas.mode', 'home')
  })
  await sleep(500)
}

// ---------------------------------------------------------------------------
// Main
// ---------------------------------------------------------------------------

async function main() {
  console.log('T-009 offline support verification\n')

  // ── Screenshot 1: online — banner should NOT appear ──────────────────────
  console.log('1. Online screenshot (banner hidden)...')
  {
    const { browser, page } = await makePage()
    await setupPage(page)
    await sleep(2000)
    // Verify banner not present
    const bannerVisible = await page.evaluate(() => {
      const el = document.querySelector('[data-testid="offline-banner"]')
      return el !== null
    })
    console.log(`   Banner visible online: ${bannerVisible} (expected: false)`)
    await page.screenshot({ path: '/tmp/t009-online.png', fullPage: false })
    await browser.close()
    console.log('   ✓ /tmp/t009-online.png')
  }

  // ── Screenshot 2: offline — banner should appear ──────────────────────────
  console.log('2. Offline screenshot (banner shown)...')
  {
    const { browser, page } = await makePage()
    await setupPage(page)
    await sleep(2000)
    // Go offline
    await page.setOfflineMode(true)
    // Dispatch offline event so signals update
    await page.evaluate(() => window.dispatchEvent(new Event('offline')))
    await sleep(600)
    const bannerText = await page.evaluate(() => {
      const el = document.querySelector('[data-testid="offline-banner"]')
      return el ? el.textContent : null
    })
    console.log(`   Banner text: "${bannerText}"`)
    await page.screenshot({ path: '/tmp/t009-offline.png', fullPage: false })
    await browser.close()
    console.log('   ✓ /tmp/t009-offline.png')
  }

  // ── Screenshot 3: offline — add 2 pending items ───────────────────────────
  console.log('3. Offline pending items screenshot...')
  {
    const { browser, page } = await makePage()
    await setupPage(page)
    await sleep(2000)
    // Go offline
    await page.setOfflineMode(true)
    await page.evaluate(() => window.dispatchEvent(new Event('offline')))
    await sleep(400)

    // Add 2 items via the input
    // Item 1: 'onion'
    await page.focus('input[aria-label="Add ingredient"]')
    await page.keyboard.type('onion')
    await sleep(300)
    await page.keyboard.press('Enter')
    await sleep(400)

    // Item 2: 'tomato'
    await page.focus('input[aria-label="Add ingredient"]')
    await page.keyboard.type('tomato')
    await sleep(300)
    await page.keyboard.press('Enter')
    await sleep(600)

    const pendingCount = await page.evaluate(() => {
      return document.querySelectorAll('[data-testid="pending-sync"]').length
    })
    console.log(`   Pending-sync indicators: ${pendingCount} (expected: ≥2)`)
    await page.screenshot({ path: '/tmp/t009-pending.png', fullPage: false })
    await browser.close()
    console.log('   ✓ /tmp/t009-pending.png')
  }

  // ── Screenshot 4: reconnect — pending gone after replay ───────────────────
  console.log('4. Reconnect sync screenshot (pending cleared)...')
  {
    const { browser, page } = await makePage()
    await setupPage(page)
    await sleep(2000)
    // Go offline
    await page.setOfflineMode(true)
    await page.evaluate(() => window.dispatchEvent(new Event('offline')))
    await sleep(400)

    // Add one item while offline (known vocab: 'garlic')
    await page.focus('input[aria-label="Add ingredient"]')
    await page.keyboard.type('garlic')
    await sleep(300)
    await page.keyboard.press('Enter')
    await sleep(500)

    const pendingBefore = await page.evaluate(() => {
      return document.querySelectorAll('[data-testid="pending-sync"]').length
    })
    console.log(`   Pending before reconnect: ${pendingBefore}`)

    // Go back online
    await page.setOfflineMode(false)
    await page.evaluate(() => window.dispatchEvent(new Event('online')))
    // Wait for replay + fetchPantry to complete
    await sleep(3000)

    const pendingAfter = await page.evaluate(() => {
      return document.querySelectorAll('[data-testid="pending-sync"]').length
    })
    console.log(`   Pending after reconnect: ${pendingAfter} (expected: 0)`)
    await page.screenshot({ path: '/tmp/t009-synced.png', fullPage: false })
    await browser.close()
    console.log('   ✓ /tmp/t009-synced.png')
  }

  // ── Cap test: populate 25 entries, assert 20 remain ──────────────────────
  console.log('5. Recipe-cache cap test (25 in → 20 remain)...')
  {
    const { browser, page } = await makePage()
    await setupPage(page)
    await sleep(1000)

    // Populate cache with 25 synthetic GET entries directly in the SW context
    const capResult = await page.evaluate(async () => {
      // Wait for SW to be active
      await navigator.serviceWorker.ready
      const sw = navigator.serviceWorker.controller
      if (!sw) return { error: 'No active SW controller' }

      const CACHE_NAME = 'pantryatlas-recipes-v1'
      const cache = await caches.open(CACHE_NAME)

      // Clear any pre-existing entries so we start fresh
      const existing = await cache.keys()
      await Promise.all(existing.map(k => cache.delete(k)))

      // Insert exactly 25 fake entries
      for (let i = 0; i < 25; i++) {
        const key = new Request(`http://127.0.0.1:5174/navigator/recipes/from-pantry?_body=fake${i}`)
        const response = new Response(JSON.stringify([{ fake: i }]), {
          headers: { 'Content-Type': 'application/json' }
        })
        await cache.put(key, response)
      }

      const beforeCount = (await cache.keys()).length

      // Ask SW to enforce the cap via message channel
      const done = await new Promise((resolve) => {
        const channel = new MessageChannel()
        channel.port1.onmessage = (e) => resolve(e.data)
        sw.postMessage({ type: 'enforce_recipe_cap' }, [channel.port2])
        // Fallback timeout
        setTimeout(() => resolve({ timeout: true }), 3000)
      })

      const afterCount = (await cache.keys()).length
      return { beforeCount, afterCount, swResponse: done }
    })

    console.log(`   Before cap: ${capResult.beforeCount} entries`)
    console.log(`   After cap: ${capResult.afterCount} entries (expected: 20)`)
    console.log(`   SW responded: ${JSON.stringify(capResult.swResponse)}`)
    const capPassed = capResult.afterCount === 20 && capResult.beforeCount === 25
    console.log(`   Cap test: ${capPassed ? 'PASS' : 'FAIL'}`)
    await browser.close()
  }

  // ── File sizes ────────────────────────────────────────────────────────────
  console.log('\nScreenshot sizes:')
  const { statSync } = await import('fs')
  const files = [
    '/tmp/t009-online.png',
    '/tmp/t009-offline.png',
    '/tmp/t009-pending.png',
    '/tmp/t009-synced.png',
  ]
  for (const f of files) {
    try {
      const { size } = statSync(f)
      console.log(`  ${f}: ${Math.round(size / 1024)}KB`)
    } catch {
      console.log(`  ${f}: MISSING`)
    }
  }

  console.log('\nT-009 verification complete.')
}

main().catch((err) => {
  console.error(err)
  process.exit(1)
})
