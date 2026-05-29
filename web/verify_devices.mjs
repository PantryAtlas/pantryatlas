/**
 * verify_devices.mjs — headless end-to-end check of the SP-C device-approval flow.
 *
 * WHAT THIS GUARDS (the real UI path, not just the API):
 *   It builds the PWA, serves it same-origin via mock_backend.py (backed by a
 *   REAL KitchenStore on a throwaway temp db), opens it in headless Chromium,
 *   then drives the COMPLETE device-approval path:
 *
 *   1. Enroll a device via page.evaluate(fetch POST /navigator/devices/enroll
 *      {name:"Counter Pi", role:"sensor"}) — this lands in the mock's KitchenStore.
 *
 *   2. Click the real "Devices" toggle button in the top bar, which sets
 *      devicesPanelOpen.value = true in the Preact signal and mounts DevicesPanel.
 *      DevicesPanel's useEffect runs fetchDevices() on mount; the pending device
 *      row appears.
 *
 *   3. Assert [data-device-row] renders and its [data-device-status] text content
 *      contains "pending" (the attribute is just the status value "pending"; the
 *      text reads "sensor · pending").
 *
 *   4. Click the real [data-approve] button (inline in the main column, not a
 *      z-indexed overlay — real Puppeteer click, not dispatchEvent). This calls
 *      approveDevice() → POST /navigator/devices/{id}/approve on the mock, which
 *      uses the real mint_token()/hash_token() from device_auth. The raw token is
 *      returned once and stored in lastIssuedToken signal.
 *
 *   5. Assert [data-token-reveal] appears and contains a non-empty token string.
 *
 *   6. Assert via GET /navigator/devices (fetched in-page) that the device's
 *      status is "paired".
 *
 * What is exercised:
 *   - Real "Devices" toggle button click → DevicesPanel mount → fetchDevices()
 *   - Real [data-approve] button click (the actual approve path, not injected)
 *   - Mock's approve → mint_token()/hash_token() → KitchenStore.approve_device()
 *   - lastIssuedToken signal → [data-token-reveal] render with the raw token
 *   - GET /navigator/devices confirming status:"paired" and no token_hash leakage
 *
 * What is NOT exercised:
 *   - /navigator/devices/me (bearer-token verification) — covered by pytest
 *   - reject / delete flows — covered by pytest (test_device_routes.py)
 *   - Live mDNS/avahi-browse — operator-side; avahi XML validated by pytest
 *   This is intentional: the headless test guards the UI approve→reveal path.
 *   The full API surface is covered by the pytest suite.
 *
 * Prints `DEVICES OK` and exits 0 on success; `DEVICES FAILED` + exit 1 otherwise.
 *
 * SELF-CONTAINED: spawns its own backend on a fresh temp kitchen.db, polls health,
 * drives chromium, and tears everything down on exit.
 *
 * Prereqs: puppeteer-core at /tmp/node_modules (install once:
 *   npm install --prefix /tmp puppeteer-core --ignore-scripts --no-save)
 */
import { createRequire } from 'module'
import { spawn } from 'child_process'
import { mkdtempSync, rmSync, existsSync } from 'fs'
import { tmpdir } from 'os'
import { join, dirname } from 'path'
import { fileURLToPath } from 'url'

const require = createRequire(import.meta.url)
const PUPPETEER_PATH = '/tmp/node_modules/puppeteer-core/lib/cjs/puppeteer/puppeteer-core.js'
if (!existsSync(PUPPETEER_PATH)) {
  console.error(
    'puppeteer-core not found at /tmp/node_modules. Install it first:\n' +
      '  npm install --prefix /tmp puppeteer-core --ignore-scripts --no-save',
  )
  console.log('DEVICES FAILED')
  process.exit(1)
}
const puppeteer = require(PUPPETEER_PATH)

const WEB_DIR = dirname(fileURLToPath(import.meta.url))
const CHROMIUM = '/usr/bin/chromium'
const PORT = Number(process.env.MOCK_PORT || 8097)
const ORIGIN = `http://127.0.0.1:${PORT}`
const sleep = (ms) => new Promise((r) => setTimeout(r, ms))

// Throwaway db
const TMP = mkdtempSync(join(tmpdir(), 'pa-devices-'))
const KITCHEN_DB = join(TMP, 'kitchen.db')

let backend = null
let browser = null

function cleanup() {
  try { if (browser) browser.close() } catch {}
  try { if (backend && !backend.killed) backend.kill('SIGKILL') } catch {}
  try { rmSync(TMP, { recursive: true, force: true }) } catch {}
}

async function startBackend() {
  backend = spawn(
    '/usr/bin/python3',
    ['-m', 'uvicorn', 'mock_backend:app', '--host', '127.0.0.1', '--port', String(PORT),
     '--log-level', 'warning'],
    {
      cwd: WEB_DIR,
      env: {
        ...process.env,
        PYTHONPATH: join(WEB_DIR, '..'),
        MOCK_KITCHEN_DB: KITCHEN_DB,
        MOCK_REFINE_DELAY_S: '0',
      },
      stdio: ['ignore', 'inherit', 'inherit'],
    },
  )
  let backendError = null
  backend.on('exit', (code) => {
    if (code !== 0 && code !== null) {
      backendError = `backend exited with code ${code}`
      console.error(backendError)
    }
  })
  for (let i = 0; i < 60; i++) {
    if (backendError) {
      throw new Error(`backend failed to start: ${backendError}`)
    }
    try {
      const res = await fetch(`${ORIGIN}/navigator/health`)
      if (res.ok) return
    } catch {}
    await sleep(500)
  }
  throw new Error('backend did not become healthy in time')
}

function fail(msg) {
  console.error(`assertion failed: ${msg}`)
  console.log('DEVICES FAILED')
  cleanup()
  process.exit(1)
}

async function main() {
  await startBackend()

  browser = await puppeteer.launch({
    executablePath: CHROMIUM,
    headless: 'new',
    args: ['--no-sandbox', '--disable-setuid-sandbox', '--disable-dev-shm-usage', '--disable-gpu'],
    defaultViewport: { width: 390, height: 844 },
  })
  const page = await browser.newPage()
  page.on('pageerror', (e) => console.error('page error:', e.message))

  // Skip first-launch mode switcher; stub service worker so it doesn't block.
  await page.evaluateOnNewDocument(() => {
    try { localStorage.setItem('pantryatlas.mode', 'home') } catch {}
    Object.defineProperty(navigator, 'serviceWorker', {
      configurable: true,
      get: () => ({ register: () => Promise.resolve(undefined), ready: new Promise(() => {}) }),
    })
  })

  await page.goto(ORIGIN, { waitUntil: 'networkidle0', timeout: 25000 })

  // ---- Step 1: Enroll a device via fetch (before opening the panel). ----------
  // Order matters: enroll first so the device exists when DevicesPanel mounts
  // and calls fetchDevices() in its useEffect. If we open the panel first
  // with an empty store, nothing re-triggers the fetch on enroll.
  console.log('step 1: enrolling device via fetch...')
  const enrollResult = await page.evaluate(async () => {
    const res = await fetch('/navigator/devices/enroll', {
      method: 'POST',
      headers: { 'Content-Type': 'application/json' },
      body: JSON.stringify({ name: 'Counter Pi', role: 'sensor' }),
    })
    return { status: res.status, body: await res.json() }
  })
  console.log('step 1: enroll result:', JSON.stringify(enrollResult))
  if (enrollResult.status !== 201) {
    fail(`enroll returned status ${enrollResult.status}, expected 201`)
  }
  const deviceId = enrollResult.body.device_id
  if (!deviceId) fail('enroll response missing device_id')
  if (enrollResult.body.status !== 'pending') {
    fail(`enroll status is "${enrollResult.body.status}", expected "pending"`)
  }

  // ---- Step 2: Click the "Devices" toggle to open the panel. ------------------
  // The toggle button aria-label is "Show devices panel" when closed (Navigator.tsx).
  // DevicesPanel mounts on first open and calls fetchDevices() in its useEffect.
  console.log('step 2: clicking Devices toggle...')
  await page.click('[aria-label="Show devices panel"]')

  // Wait for the device row to appear (DevicesPanel's useEffect fires async).
  console.log('step 2: waiting for device row...')
  await page.waitForSelector('[data-device-row]', { timeout: 10000 })
  console.log('step 2: device row appeared')

  // ---- Step 3: Assert the row shows "pending" status. -------------------------
  // data-device-status attribute = "pending" (the status value alone).
  // Text content reads "sensor · pending" (role · status).
  console.log('step 3: asserting pending status...')
  const statusEl = await page.$('[data-device-status]')
  if (!statusEl) fail('[data-device-status] element not found')

  const statusAttr = await page.evaluate((el) => el.getAttribute('data-device-status'), statusEl)
  const statusText = await page.evaluate((el) => el.textContent, statusEl)
  console.log(`step 3: data-device-status="${statusAttr}", textContent="${statusText}"`)

  if (statusAttr !== 'pending') {
    fail(`[data-device-status] attribute is "${statusAttr}", expected "pending"`)
  }
  if (!statusText || !statusText.includes('pending')) {
    fail(`[data-device-status] text "${statusText}" does not contain "pending"`)
  }

  // ---- Step 4: Click the real [data-approve] button. -------------------------
  // DevicesPanel is rendered inline in the main column (not a z-indexed overlay),
  // so a real Puppeteer click on the element works without dispatchEvent workaround.
  console.log('step 4: clicking [data-approve] button...')
  const approveBtn = await page.$('[data-approve]')
  if (!approveBtn) fail('[data-approve] button not found')

  const isDisabled = await page.evaluate((el) => el.disabled, approveBtn)
  if (isDisabled) fail('[data-approve] button is disabled')

  await approveBtn.click()
  console.log('step 4: approve button clicked')

  // ---- Step 5: Assert [data-token-reveal] appears with a non-empty token. ----
  // approveDevice() → POST /approve → mock mints a real token → lastIssuedToken
  // signal set → DevicesPanel renders <code data-token-reveal>...token...</code>.
  console.log('step 5: waiting for [data-token-reveal]...')
  await page.waitForSelector('[data-token-reveal]', { timeout: 10000 })

  const revealText = await page.evaluate(() => {
    const el = document.querySelector('[data-token-reveal]')
    return el ? el.textContent : null
  })
  console.log(`step 5: token-reveal text: "${revealText}"`)

  if (!revealText) fail('[data-token-reveal] has no text content')
  // Strip the prefix — the token itself follows after ": "
  const PREFIX = 'Save this token on the device (shown once): '
  const rawToken = revealText.includes(PREFIX)
    ? revealText.slice(revealText.indexOf(PREFIX) + PREFIX.length).trim()
    : revealText.trim()

  if (!rawToken || rawToken.length < 16) {
    fail(`extracted token "${rawToken}" is too short or empty — approve may not have returned a token`)
  }
  console.log(`step 5: token extracted (length ${rawToken.length}) — OK`)

  // ---- Step 6: Verify GET /navigator/devices shows status "paired". ----------
  console.log('step 6: verifying device status via GET /navigator/devices...')
  const devicesList = await page.evaluate(async () => {
    const res = await fetch('/navigator/devices')
    return res.json()
  })
  console.log('step 6: devices list:', JSON.stringify(devicesList))

  const found = devicesList.find((d) => d.device_id === deviceId)
  if (!found) {
    fail(`device ${deviceId} not found in GET /navigator/devices list`)
  }
  if (found.status !== 'paired') {
    fail(`device status is "${found.status}", expected "paired"`)
  }
  // Belt-and-suspenders: verify token is never leaked in the list
  if ('token' in found || 'token_hash' in found) {
    fail('GET /navigator/devices leaked raw token or token_hash — security violation')
  }
  console.log('step 6: device is paired and no token leaked')

  console.log('DEVICES OK')
  cleanup()
  process.exit(0)
}

process.on('SIGINT', () => { cleanup(); process.exit(130) })

main().catch((err) => {
  console.error(err)
  console.log('DEVICES FAILED')
  cleanup()
  process.exit(1)
})
