/**
 * verify_loop.mjs — headless end-to-end check of the SP-A "I cooked this" loop.
 *
 * WHAT THIS GUARDS (the real UI path, not just the API):
 *   It builds the PWA, serves it same-origin via mock_backend.py (backed by a
 *   REAL KitchenStore on a throwaway temp db), opens it in headless Chromium,
 *   seeds one pantry item, then EXPANDS A RECIPE CARD AND CLICKS THE ACTUAL
 *   "I cooked this" button (`[data-cooked-btn]`). A prior bug had that button
 *   log the meal but pass NO `consumed`, so the pantry never decremented — this
 *   script reproduces that exact path through the button's onClick handler.
 *
 *   It asserts, in order:
 *     1. the outgoing POST /navigator/cook carries a NON-EMPTY `consumed` array
 *        (the precise fix-guard — the button derives covered ingredients itself);
 *     2. the /cook response reports the seeded item in `matched`;
 *     3. GET /navigator/meals shows the cooked recipe (dish_name = the card's
 *        own title, read live from the DOM — not hardcoded);
 *     4. GET /navigator/pantry shows the cooked item soft-decremented. The button
 *        sends coarse_amount='cook', so a fresh `present` item lands on `low`
 *        (one notch), NOT `used_up` — coarse-by-design.
 *
 * It prints `LOOP OK` and exits 0 on success, `LOOP FAILED` + exit 1 otherwise.
 *
 * SELF-CONTAINED: spawns its own backend with system python3 (the uv .venv has
 * no uvicorn) on a fresh temp kitchen.db, polls /navigator/health, and tears
 * everything down on exit — so `node web/verify_loop.mjs` is a one-shot gate.
 *
 * Reuses the sibling harness pattern (web/take_screenshots_refine.mjs,
 * web/verify_swap_concurrency.mjs): puppeteer-core from /tmp/node_modules +
 * /usr/bin/chromium. If puppeteer-core is absent, install it once with:
 *   npm install --prefix /tmp puppeteer-core --ignore-scripts --no-save
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
  console.log('LOOP FAILED')
  process.exit(1)
}
const puppeteer = require(PUPPETEER_PATH)

const WEB_DIR = dirname(fileURLToPath(import.meta.url))
const CHROMIUM = '/usr/bin/chromium'
const PORT = Number(process.env.MOCK_PORT || 8097)
const ORIGIN = `http://127.0.0.1:${PORT}`
const sleep = (ms) => new Promise((r) => setTimeout(r, ms))

// Throwaway kitchen.db so the run starts EMPTY and is fully deterministic.
const TMP = mkdtempSync(join(tmpdir(), 'pa-loop-'))
const KITCHEN_DB = join(TMP, 'kitchen.db')

let backend = null
let browser = null

function cleanup() {
  try {
    if (browser) browser.close()
  } catch {}
  try {
    if (backend && !backend.killed) backend.kill('SIGKILL')
  } catch {}
  try {
    rmSync(TMP, { recursive: true, force: true })
  } catch {}
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
        PYTHONPATH: join(WEB_DIR, '..'), // import pantryatlas.store.kitchen
        MOCK_KITCHEN_DB: KITCHEN_DB, // start EMPTY (no default seed)
        MOCK_REFINE_DELAY_S: '0', // settle fast — no screenshot window needed
      },
      stdio: ['ignore', 'inherit', 'inherit'],
    },
  )
  backend.on('exit', (code) => {
    if (code && code !== 0 && code !== null) {
      console.error(`backend exited early with code ${code}`)
    }
  })
  // Poll health until the server answers (uvicorn boot on the Pi is ~1-3s).
  for (let i = 0; i < 60; i++) {
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
  console.log('LOOP FAILED')
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

  // Skip the first-launch mode switcher + stub the service worker so the
  // multi-call instant/refine flow is never served from cache.
  await page.evaluateOnNewDocument(() => {
    try {
      localStorage.setItem('pantryatlas.mode', 'home')
    } catch {}
    Object.defineProperty(navigator, 'serviceWorker', {
      configurable: true,
      get: () => ({ register: () => Promise.resolve(undefined), ready: new Promise(() => {}) }),
    })
  })

  await page.goto(ORIGIN, { waitUntil: 'networkidle0', timeout: 25000 })

  // Seed ONE pantry item via the API the page itself uses, then reload so the
  // app recomputes recipes from a known single-item pantry.
  const seedStatus = await page.evaluate(async () => {
    const r = await fetch('/navigator/pantry/items', {
      method: 'POST',
      headers: { 'Content-Type': 'application/json' },
      body: JSON.stringify({ raw_text: 'garlic' }),
    })
    return r.status
  })
  if (seedStatus !== 201) fail(`seeding garlic returned ${seedStatus}, expected 201`)

  await page.reload({ waitUntil: 'networkidle0', timeout: 25000 })

  // Wait for the recipe list to paint AND refine to settle, then for ≥1 card.
  await page.waitForSelector('section[data-refine-state="refined"]', { timeout: 15000 })
  await page.waitForSelector('li[role="article"]', { timeout: 10000 })
  await sleep(300) // let any re-order settle

  // Read the TOP card's title from its aria-label ("Title, N missing · M min").
  const cards = await page.$$('li[role="article"]')
  if (!cards.length) fail('no recipe cards rendered for the seeded pantry')
  const topTitle = await page.evaluate(
    (el) => (el.getAttribute('aria-label') || '').split(',')[0].trim(),
    cards[0],
  )
  if (!topTitle) fail('could not read the top recipe card title')
  console.log('top card:', topTitle)

  // Expand the top card so its action buttons render.
  await cards[0].click()
  await page.waitForSelector('[data-cooked-btn]', { timeout: 8000 })

  // Arm a listener on the cook POST BEFORE clicking, so we capture the exact
  // request body the button sends (the fix-guard) + the server's response.
  const cookReqPromise = page.waitForRequest(
    (req) => req.url().includes('/navigator/cook') && req.method() === 'POST',
    { timeout: 10000 },
  )
  const cookRespPromise = page.waitForResponse(
    (res) => res.url().includes('/navigator/cook') && res.request().method() === 'POST',
    { timeout: 10000 },
  )

  // CLICK THE REAL "I cooked this" BUTTON.
  await page.click('[data-cooked-btn]')

  const cookReq = await cookReqPromise
  const cookResp = await cookRespPromise

  // ---- Assertion 1: the button sent a NON-EMPTY `consumed` array (the bug). --
  let reqBody = {}
  try {
    reqBody = JSON.parse(cookReq.postData() || '{}')
  } catch {
    fail('cook request body was not valid JSON')
  }
  console.log('cook request body:', JSON.stringify(reqBody))
  if (!Array.isArray(reqBody.consumed) || reqBody.consumed.length === 0) {
    fail('POST /navigator/cook carried no `consumed` items (the regression)')
  }
  const consumedNames = reqBody.consumed.map((c) => c.canonical_name)
  if (!consumedNames.includes('garlic')) {
    fail(`consumed array missing the covered item 'garlic': ${JSON.stringify(consumedNames)}`)
  }

  // ---- Assertion 2: the /cook response matched the seeded item. -------------
  if (!(cookResp.ok() || cookResp.status() === 201)) {
    fail(`POST /navigator/cook returned HTTP ${cookResp.status()}`)
  }
  const cookJson = await cookResp.json()
  console.log('cook response:', JSON.stringify(cookJson))
  if (!Array.isArray(cookJson.matched) || !cookJson.matched.includes('garlic')) {
    fail(`cook response did not match 'garlic': ${JSON.stringify(cookJson.matched)}`)
  }

  // The button awaits fetchPantry()/fetchMeals() after /cook; give them a beat.
  await sleep(600)

  // ---- Assertions 3 + 4: meal logged + pantry decremented (via the API the
  //      page uses). Done in-page so it goes through the same same-origin fetch.
  const after = await page.evaluate(async () => {
    const meals = await (await fetch('/navigator/meals')).json()
    const pantry = await (await fetch('/navigator/pantry')).json()
    return { meals, pantry }
  })

  const meal = after.meals[0]
  if (!meal) fail('GET /navigator/meals returned no meals after cooking')
  console.log('newest meal:', JSON.stringify({ dish_name: meal.dish_name, servings: meal.servings }))
  if (meal.dish_name !== topTitle) {
    fail(`newest meal dish_name '${meal.dish_name}' != clicked card '${topTitle}'`)
  }

  const garlic = after.pantry.find((i) => i.canonical_name === 'garlic')
  if (!garlic) fail("'garlic' vanished from the pantry after cooking")
  console.log('garlic after cook:', JSON.stringify({ state: garlic.state }))
  // Real button sends coarse_amount='cook' → present drops ONE notch to 'low'
  // (coarse-by-design; servings does NOT scale the decrement in SP-A).
  if (garlic.state !== 'low' && garlic.state !== 'used_up') {
    fail(`garlic state is '${garlic.state}', expected a soft-decrement ('low'/'used_up')`)
  }

  console.log('LOOP OK')
  cleanup()
  process.exit(0)
}

process.on('SIGINT', () => {
  cleanup()
  process.exit(130)
})

main().catch((err) => {
  console.error(err)
  console.log('LOOP FAILED')
  cleanup()
  process.exit(1)
})
