/**
 * T-008 screenshot script — recipe section + inline expand.
 * Uses puppeteer-core + system Chromium against the mock backend (port 8099)
 * served through Vite preview (port 5174).
 */
import { createRequire } from 'module'
const require = createRequire(import.meta.url)
const puppeteer = require('/tmp/node_modules/puppeteer-core/lib/cjs/puppeteer/puppeteer-core.js')

const BASE = 'http://127.0.0.1:5174'
const CHROMIUM = '/usr/bin/chromium'

async function sleep(ms) {
  return new Promise((r) => setTimeout(r, ms))
}

async function makePage(width, height, darkMode = false) {
  const args = [
    '--no-sandbox',
    '--disable-setuid-sandbox',
    '--disable-dev-shm-usage',
    '--disable-gpu',
    `--window-size=${width},${height}`,
  ]
  const browser = await puppeteer.launch({
    executablePath: CHROMIUM,
    headless: 'new',
    args,
    defaultViewport: { width, height },
  })
  const page = await browser.newPage()
  if (darkMode) {
    await page.emulateMediaFeatures([{ name: 'prefers-color-scheme', value: 'dark' }])
  }
  return { browser, page }
}

async function gotoAndSetMode(page) {
  await page.goto(BASE, { waitUntil: 'networkidle0', timeout: 15000 })
  await page.evaluate(() => {
    localStorage.setItem('pantryatlas.mode', 'home')
  })
  // Dismiss ModeSwitcher if open
  await sleep(300)
  try {
    const btns = await page.$$('button[aria-pressed]')
    if (btns[0]) await btns[0].click()
  } catch {}
  await sleep(800)
}

async function main() {
  console.log('Taking T-008 screenshots...\n')

  // -------------------------------------------------------------------------
  // 1: empty pantry → recipe empty-state (no recipes returned)
  // -------------------------------------------------------------------------
  {
    const { browser, page } = await makePage(390, 844)
    // Intercept pantry to return empty list → recipes endpoint will also return []
    await page.setRequestInterception(true)
    page.on('request', (req) => {
      const url = req.url()
      if (url.includes('/navigator/pantry') && req.method() === 'GET') {
        req.respond({ status: 200, contentType: 'application/json', body: '[]' })
      } else if (url.includes('/navigator/recipes/from-pantry') && req.method() === 'POST') {
        req.respond({ status: 200, contentType: 'application/json', body: '[]' })
      } else {
        req.continue()
      }
    })
    await gotoAndSetMode(page)
    await sleep(2000)
    await page.screenshot({ path: '/tmp/t008-empty-mobile.png', fullPage: true })
    await browser.close()
    console.log('  ✓ /tmp/t008-empty-mobile.png')
  }

  // -------------------------------------------------------------------------
  // 2: pantry has items → recipe results (real mock backend data)
  // -------------------------------------------------------------------------
  {
    const { browser, page } = await makePage(390, 844)
    await gotoAndSetMode(page)
    // Wait for recipe results to load (backend has garlic+kale seeded)
    await sleep(2500)
    await page.screenshot({ path: '/tmp/t008-results-mobile.png', fullPage: true })
    await browser.close()
    console.log('  ✓ /tmp/t008-results-mobile.png')
  }

  // -------------------------------------------------------------------------
  // 3: expand a recipe card → inline-expanded view
  // -------------------------------------------------------------------------
  {
    const { browser, page } = await makePage(390, 844)
    await gotoAndSetMode(page)
    await sleep(2500)
    // Click the first recipe card's chevron button
    try {
      // Find the first recipe card li element and click it
      const cards = await page.$$('li[role="article"]')
      if (cards.length > 0) {
        await cards[0].click()
        await sleep(800)
      } else {
        console.log('  ⚠ No recipe cards found yet, retrying...')
        await sleep(1000)
        const cards2 = await page.$$('li[role="article"]')
        if (cards2.length > 0) {
          await cards2[0].click()
          await sleep(800)
        }
      }
    } catch (err) {
      console.log('  ⚠ Click error:', err.message)
    }
    await page.screenshot({ path: '/tmp/t008-expanded-mobile.png', fullPage: true })
    await browser.close()
    console.log('  ✓ /tmp/t008-expanded-mobile.png')
  }

  // -------------------------------------------------------------------------
  // 4: desktop 1280x800 → single column (not bento)
  // -------------------------------------------------------------------------
  {
    const { browser, page } = await makePage(1280, 800)
    await gotoAndSetMode(page)
    await sleep(2500)
    await page.screenshot({ path: '/tmp/t008-results-desktop.png', fullPage: true })
    await browser.close()
    console.log('  ✓ /tmp/t008-results-desktop.png')
  }

  // -------------------------------------------------------------------------
  // 5: dark mode
  // -------------------------------------------------------------------------
  {
    const { browser, page } = await makePage(390, 844, true)
    await gotoAndSetMode(page)
    await sleep(2500)
    await page.screenshot({ path: '/tmp/t008-results-dark.png', fullPage: true })
    await browser.close()
    console.log('  ✓ /tmp/t008-results-dark.png')
  }

  console.log('\nAll T-008 screenshots complete.')

  const { statSync } = await import('fs')
  const files = [
    '/tmp/t008-empty-mobile.png',
    '/tmp/t008-results-mobile.png',
    '/tmp/t008-expanded-mobile.png',
    '/tmp/t008-results-desktop.png',
    '/tmp/t008-results-dark.png',
  ]
  for (const f of files) {
    try {
      const { size } = statSync(f)
      console.log(`  ${f}: ${Math.round(size / 1024)}KB`)
    } catch {
      console.log(`  ${f}: MISSING`)
    }
  }
}

main().catch((err) => {
  console.error(err)
  process.exit(1)
})
