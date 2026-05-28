/**
 * T-007 screenshot script using puppeteer-core + system Chromium.
 * Sets localStorage before page loads to prevent ModeSwitcher from opening.
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
  // Inject localStorage BEFORE initial page load via CDP
  const client = await page.createCDPSession()
  await client.send('Storage.setStorageItem', {
    storageId: { storageType: 'local', origin: BASE },
    key: 'pantryatlas.mode',
    value: 'home',
  }).catch(() => {}) // Ignore if not supported
  return { browser, page, client }
}

async function gotoAndDismissModal(page) {
  await page.goto(BASE, { waitUntil: 'networkidle0', timeout: 15000 })
  // Set mode in localStorage via evaluate immediately
  await page.evaluate(() => {
    localStorage.setItem('pantryatlas.mode', 'home')
  })
  // Dismiss ModeSwitcher if open: click the Home Kitchen button
  await sleep(300)
  try {
    const homeBtn = await page.$('button[aria-pressed="true"]')
    if (homeBtn) {
      await homeBtn.click()
    } else {
      // Try clicking the backdrop
      const dialog = await page.$('[aria-label="How are you cooking?"]')
      if (dialog) {
        // Click home kitchen option
        const btns = await page.$$('button[aria-pressed]')
        if (btns[0]) await btns[0].click()
      }
    }
  } catch {}
  await sleep(600)
}

async function main() {
  console.log('Taking T-007 screenshots...\n')

  // -----------------------------------------------------------------------
  // 7: empty pantry 390x844
  // -----------------------------------------------------------------------
  {
    const { browser, page } = await makePage(390, 844)
    await page.setRequestInterception(true)
    page.on('request', (req) => {
      if (req.url().includes('/navigator/pantry') && req.method() === 'GET') {
        req.respond({ status: 200, contentType: 'application/json', body: '[]' })
      } else {
        req.continue()
      }
    })
    await gotoAndDismissModal(page)
    await sleep(1200)
    await page.screenshot({ path: '/tmp/t007-empty-mobile.png' })
    await browser.close()
    console.log('  ✓ /tmp/t007-empty-mobile.png')
  }

  // -----------------------------------------------------------------------
  // 8: resolved chip after typing 'garlic'
  // -----------------------------------------------------------------------
  {
    const { browser, page } = await makePage(390, 844)
    await gotoAndDismissModal(page)
    await page.focus('input[aria-label="Add ingredient"]')
    await page.type('input[aria-label="Add ingredient"]', 'garlic', { delay: 60 })
    await sleep(900)
    await page.screenshot({ path: '/tmp/t007-resolved-mobile.png' })
    await browser.close()
    console.log('  ✓ /tmp/t007-resolved-mobile.png')
  }

  // -----------------------------------------------------------------------
  // 9: item added (press Enter)
  // -----------------------------------------------------------------------
  {
    const { browser, page } = await makePage(390, 844)
    await gotoAndDismissModal(page)
    await page.focus('input[aria-label="Add ingredient"]')
    await page.type('input[aria-label="Add ingredient"]', 'garlic', { delay: 60 })
    await sleep(700)
    await page.keyboard.press('Enter')
    await sleep(1500)
    await page.screenshot({ path: '/tmp/t007-added-mobile.png' })
    await browser.close()
    console.log('  ✓ /tmp/t007-added-mobile.png')
  }

  // -----------------------------------------------------------------------
  // 10: error message for 'xyzzy'
  // -----------------------------------------------------------------------
  {
    const { browser, page } = await makePage(390, 844)
    await gotoAndDismissModal(page)
    await page.focus('input[aria-label="Add ingredient"]')
    await page.type('input[aria-label="Add ingredient"]', 'xyzzy', { delay: 60 })
    await sleep(900)
    await page.screenshot({ path: '/tmp/t007-unresolved-mobile.png' })
    await browser.close()
    console.log('  ✓ /tmp/t007-unresolved-mobile.png')
  }

  // -----------------------------------------------------------------------
  // 11: expiry error-container chip (kale expires today — seeded in mock)
  // -----------------------------------------------------------------------
  {
    const { browser, page } = await makePage(390, 844)
    await gotoAndDismissModal(page)
    await sleep(1200)
    await page.screenshot({ path: '/tmp/t007-expiry-mobile.png' })
    await browser.close()
    console.log('  ✓ /tmp/t007-expiry-mobile.png')
  }

  // -----------------------------------------------------------------------
  // 12a: dark mode 390x844
  // -----------------------------------------------------------------------
  {
    const { browser, page } = await makePage(390, 844, true)
    await gotoAndDismissModal(page)
    await sleep(1200)
    await page.screenshot({ path: '/tmp/t007-dark.png' })
    await browser.close()
    console.log('  ✓ /tmp/t007-dark.png')
  }

  // -----------------------------------------------------------------------
  // 12b: desktop 1280x800
  // -----------------------------------------------------------------------
  {
    const { browser, page } = await makePage(1280, 800)
    await gotoAndDismissModal(page)
    await sleep(1200)
    await page.screenshot({ path: '/tmp/t007-desktop.png' })
    await browser.close()
    console.log('  ✓ /tmp/t007-desktop.png')
  }

  console.log('\nAll screenshots complete.')

  const { statSync } = await import('fs')
  const files = [
    '/tmp/t007-empty-mobile.png',
    '/tmp/t007-resolved-mobile.png',
    '/tmp/t007-added-mobile.png',
    '/tmp/t007-unresolved-mobile.png',
    '/tmp/t007-expiry-mobile.png',
    '/tmp/t007-dark.png',
    '/tmp/t007-desktop.png',
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
