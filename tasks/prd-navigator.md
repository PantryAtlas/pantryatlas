# PRD: `pantryatlas.navigator` v0.2.0

> The first user-facing PantryAtlas submodule. Pantry-in, recipes-out: type what you have, see what you can cook.

## 1. Introduction / Overview

`pantryatlas.navigator` is the first v0.2 submodule. It turns the v0.1 foundation (embeddings + storage + matcher) into a working app that a non-developer can use over local Wi-Fi from their phone.

Three pieces:
1. **Recipe ingestion pipeline** that turns the staged RecipeNLG corpus into searchable, embedded entries in `RecipeStore`.
2. **HTTP API** (FastAPI) exposing pantry CRUD + recipe-ranking endpoints.
3. **Preact PWA frontend** at `/home/craigm26/pantryatlas/web/` that runs on a phone and survives airplane mode for recent views.

v0.2.0 is intentionally small: a curated 50K-recipe subset (not the full 2.1M), single-user single-pantry, English UI only, no narration layer. The bigger ideas (full corpus, cultural-fit filtering, narration, photo input) are deferred to subsequent submodules and v0.2 tracker [issue #1](https://github.com/PantryAtlas/pantryatlas/issues/1).

## 2. Goals

- A Pi 5 user can `pip install -e .[navigator]` + `python -m pantryatlas.navigator.ingest --limit 50000` and have a working recipe corpus in under an hour.
- The pantry→recipes endpoint returns ranked recipes (coverage + expiration urgency + substitution distance) in <2s for a 10-item pantry.
- A PWA installs from `http://<pi-host>:8090` on a phone on the same Wi-Fi; works offline for recently-viewed recipes.
- Full stack (gemma + embeddings sidecar + mem-monitor + navigator) stays under 6.5GB resident on Pi 5 8GB.
- The submodule structure (Python at `pantryatlas/navigator/`, web at repo root `/web/`) demonstrates the v0.2 pattern for future submodules.

## 3. Tasks

### T-001: Recipe curation + ingestion CLI scaffold
**Description:** Add `pantryatlas/navigator/__init__.py` and `pantryatlas/navigator/ingest.py`. CLI entry `python -m pantryatlas.navigator.ingest --limit N --dry-run`. Reads `pantryatlas/data/_staging/recipenlg.raw.parquet`, parses the `input` text into structured `(title, ingredients_list, instructions)` tuples using the same heuristic NER as T-008, and emits a curated subset to a staging table. Curation rules: discard rows with empty title or empty ingredients; require ≥3 distinct ingredients; balance the sample across ingredient-count buckets (3-5, 6-8, 9+ ingredients) so the corpus isn't dominated by trivially-short recipes.

**Acceptance Criteria:**
- [ ] `python -m pantryatlas.navigator.ingest --limit 1000 --dry-run` runs in <30s and prints a summary (rows selected, rows discarded, distribution across ingredient-count buckets)
- [ ] No DB writes happen with `--dry-run`
- [ ] Sample distribution: at least 25% in each of the 3 buckets (3-5, 6-8, 9+ ingredients)
- [ ] Discarded rows are logged with reason (empty title, empty ingredients, too few ingredients)
- [ ] Quality checks pass (ruff + pytest on existing tests)

### T-002: Full ingestion with embeddings → RecipeStore
**Description:** Extend `pantryatlas.navigator.ingest` to actually embed each recipe (combined title + ingredients string) via `pantryatlas.embeddings.embed` and upsert into `pantryatlas.store.recipes.RecipeStore`. Batch embeddings (default 64 per batch) to amortize bge-m3 throughput. Add a `--target-db PATH` arg defaulting to `~/.pantryatlas/recipes.db`. Resumable: on re-run, skip rows already present by recipe id.

**Acceptance Criteria:**
- [ ] `python -m pantryatlas.navigator.ingest --limit 1000 --target-db /tmp/test-recipes.db` completes successfully
- [ ] `RecipeStore("/tmp/test-recipes.db")` then `query_by_vector(embed(["pasta carbonara"])[0], top_k=5)` returns 5 plausibly-relevant recipes (manual eyeball on test output)
- [ ] Re-running with `--limit 1000` against the same db skips already-embedded rows (logs "skipped: N already present")
- [ ] Wall-clock on Pi 5 for 50K rows: estimated <60 min based on T-003 benchmark (~28-55 emb/s); log actual time
- [ ] Resulting db file is <300MB for 50K rows
- [ ] Quality checks pass

### T-003: Pantry→recipes ranking algorithm (pure Python, testable)
**Description:** Implement `pantryatlas/navigator/ranking.py` with `rank_recipes(pantry: Pantry, candidate_recipes: list[Recipe], embed_fn: Callable, k: int = 20) -> list[RankedRecipe]`. The score combines:
- **Coverage** (weight 0.50): `|pantry_canonical ∩ recipe_ingredients_canonical| / |recipe_ingredients_canonical|`
- **Expiration urgency** (weight 0.20): for each pantry ingredient with `expires_at <= today + 3 days` consumed by the recipe, add a constant boost
- **Substitution distance** (weight 0.20): for each missing ingredient, find nearest pantry ingredient via bge-m3 cosine; sum `(1 - max_cosine)` as a penalty (higher penalty = worse match)
- **Cultural fit** (weight 0.10): when configured with a cuisine tag, boost recipes whose title contains a cuisine keyword (simple lookup; deeper version deferred to v0.3)

Returns top-`k` `RankedRecipe(recipe, score, coverage, missing, substitution_suggestions, expiring_used)` tuples. Pure function — accepts already-fetched candidate recipes; the FastAPI layer (T-004) handles the sqlite-vec pre-filter to avoid scoring all 50K recipes.

**Acceptance Criteria:**
- [ ] `pantryatlas/navigator/ranking.py` exists with `rank_recipes` and the `RankedRecipe` dataclass
- [ ] `pytest tests/navigator/test_ranking.py -q` passes with at least 8 tests covering: full-coverage recipe ranks #1; partial coverage ranks below; expiration boost lifts a tied recipe above another; substitution penalty drops a high-coverage-but-unrelated recipe below
- [ ] Test asserts: with pantry=`{garlic, tomato, basil, olive oil, pasta}`, recipe=`{garlic, tomato, basil, olive oil, pasta}` (all 5 covered), score == 1.0 minus 0 penalties
- [ ] Test asserts: with pantry=`{garlic, tomato}`, recipe=`{garlic, tomato, basil}`, coverage == 2/3, missing == [basil]
- [ ] Test for expiration boost: two recipes with identical coverage; one consumes an expiring item; the expiring one ranks higher
- [ ] Quality checks pass

### T-004: FastAPI navigator endpoint
**Description:** `pantryatlas/navigator/server.py` exposes a FastAPI app with these routes:

- `GET /navigator/health` — `{"status": "ok", "recipe_count": N}`
- `GET /navigator/pantry` — return current pantry as JSON (loaded from `~/.pantryatlas/pantry.json`, a flat file for v0.2)
- `PUT /navigator/pantry` — replace current pantry with the posted list
- `POST /navigator/pantry/items` — append a single ingredient (body: `{raw_text, quantity?, expires_at?}`); resolves via `pantryatlas.pantry.Matcher`
- `DELETE /navigator/pantry/items/{canonical_name}` — remove one
- `POST /navigator/recipes/from-pantry` — body: `{pantry: list[Ingredient], k: int = 20, cuisine: str | None = null}`. Embed the pantry concat string, sqlite-vec query top 200 candidates from RecipeStore, run `rank_recipes` on those 200, return top-k. Target latency <2s for a 10-item pantry.
- `GET /navigator/` — serve the PWA `index.html` from `/web/dist/`
- `GET /static/*` — serve PWA assets from `/web/dist/`

Pantry storage in v0.2 is intentionally a flat JSON file at `~/.pantryatlas/pantry.json` — no DB schema, no migrations. Concurrent writes from multiple browser tabs are not handled (single user assumption).

**Acceptance Criteria:**
- [ ] `pytest tests/navigator/test_server.py -q` passes with at least 10 tests covering all 7 endpoints
- [ ] Tests use `httpx.AsyncClient` against the FastAPI app directly (no live server needed)
- [ ] PUT /navigator/pantry then GET /navigator/pantry round-trips a 5-item pantry losslessly
- [ ] POST /navigator/recipes/from-pantry with a known pantry returns ≥1 result given a 1000-recipe test fixture
- [ ] Health endpoint returns the actual recipe count (not hardcoded)
- [ ] CORS configured to allow same-origin only (PWA is served from the same host:port)
- [ ] Quality checks pass

### T-004B: Generate visual design via Stitch MCP (Antigravity-routed)
**Description:** Before any frontend code lands, generate authoritative visual designs for the 3 main screens via **Google Stitch MCP** (reached through Antigravity CLI on this Pi — `~/.gemini/antigravity/mcp/StitchMCP/`). Stitch produces both Figma-style mockups and frontend code; we use the mockups as visual ground-truth and translate to Preact (Stitch defaults to React/Tailwind).

Pipeline (executed from a fresh `agy -p` invocation):
1. **Write `web/design/DESIGN.md`** locally — a markdown brief describing PantryAtlas brand (terracotta-warm M3 Expressive, Spark-inspired, mobile-first, generous whitespace, bento layouts, soft elevation, expressive type ramp), the 3 target screens (PantryEditor, RecipeResults, RecipeDetail), and the content/state surface for each.
2. **`agy -p "..."` invocation** uses Stitch via:
   - `create_project --title "PantryAtlas Navigator"` → captures `project_id`
   - `upload_design_md` with the base64-encoded DESIGN.md and `projectId`
   - `create_design_system_from_design_md` to materialize the design system
   - `generate_screen_from_text` three times — one per target screen — at `deviceType=MOBILE` (primary) and a second pass at `deviceType=DESKTOP` for the bento layout
   - `get_screen` to fetch each generated screen
3. **Save artifacts** to `web/design/`:
   - `web/design/DESIGN.md` (the brief we uploaded)
   - `web/design/design-system.json` (Stitch's design system response — colors, fonts, shapes, motion)
   - `web/design/screens/{pantry-editor,recipe-results,recipe-detail}-{mobile,desktop}.{json,png,html}` (one mockup per screen × device)
   - `web/design/STITCH_PROJECT.txt` with the Stitch project URL for the operator to view in browser
4. **Commit** only the JSON + PNG artifacts (not generated HTML — that's reference, not source). PNGs are checked in so reviewers can see the target visually.

T-005, T-006, T-007, T-008 implementer prompts MUST reference these artifacts. T-007 and T-008 acceptance criteria add a "visually matches `web/design/screens/<screen>-<device>.png` within reasonable tolerance" check.

**Acceptance Criteria:**
- [ ] `web/design/DESIGN.md` exists with: brand statement, color palette intent (seed=`#B85C38` terracotta), typography intent, 3 screen descriptions (PantryEditor, RecipeResults, RecipeDetail), motion/shape principles
- [ ] `agy -p "<orchestration prompt>"` invocation succeeded — log saved to `web/design/stitch-orchestration.log`
- [ ] Stitch project URL recorded at `web/design/STITCH_PROJECT.txt` (operator can open it in browser)
- [ ] `web/design/design-system.json` exists with non-empty design tokens
- [ ] 6 screen mockup PNGs exist: `web/design/screens/{pantry-editor,recipe-results,recipe-detail}-{mobile,desktop}.png`
- [ ] Each screen's JSON metadata sidecar (`<screen>.json`) exists alongside the PNG, capturing the Stitch resource name for later `edit_screens` / `generate_variants` calls in v0.3
- [ ] `.gitignore` updated: `web/design/screens/*.html` (reference only, regenerable from Stitch), but `web/design/` directory itself is committed
- [ ] Operator can run `agy -p "Open the Stitch project"` later and the URL still resolves (i.e., the project wasn't created in a session-scoped scratch)
- [ ] Quality checks pass

**Implementation notes for the dispatch:**
- This task's "implementer" is unusual — it spawns an `agy` subprocess rather than writing Python. Use `subprocess.run(["agy", "-p", "--dangerously-skip-permissions", prompt_text], capture_output=True, timeout=600)`. The 10-minute timeout accommodates Stitch's "may take a few minutes" warning per its tool docs.
- The `--dangerously-skip-permissions` flag is needed because Antigravity will prompt for confirmation on every Stitch tool call otherwise; this is a sandboxed background invocation so auto-approve is acceptable.
- If `agy` returns a session-blocking error or rate limit, save the partial output and report DONE_WITH_CONCERNS so the operator can complete manually via the Stitch web UI (using `STITCH_PROJECT.txt`).

### T-005: Frontend scaffold + Material 3 Expressive design system (Vite + Preact at /web/)
**Description:** Initialize a Vite + Preact + TypeScript project at `/home/craigm26/pantryatlas/web/` AND lay down a **Material 3 Expressive design system** inspired by Google's Spark app. Add `package.json` with `vite`, `preact`, `@preact/preset-vite`, `typescript`, `@material/material-color-utilities` (for HCT/dynamic-color palette generation), and a Material Symbols icon font reference (variable font, served locally — no Google Fonts CDN to keep the stack Pi-only and offline-capable).

Design language (this is load-bearing — T-007 and T-008 build on it):
- **Color:** Dynamic M3 palette generated at build time from a single warm food-related seed color (`#B85C38` terracotta as default, configurable). Emit `--md-sys-color-*` CSS custom properties for both light and dark schemes via `@material/material-color-utilities`. Surface tonal palette covers `surface`, `surface-container`, `surface-container-high`, `surface-container-highest`, `primary`, `primary-container`, `secondary-container`, `on-*` pairs.
- **Typography:** M3 Expressive type ramp via CSS custom properties (`--md-sys-typescale-display-large` ... `--md-sys-typescale-label-small`). Font stack: `"Google Sans Text", "Inter", system-ui` (Google Sans falls back gracefully on devices that don't have it; we don't bundle it to avoid the licensing question). Display sizes use 700 weight; body uses 400.
- **Shape:** Generous corner radii — cards `--md-sys-shape-corner-extra-large` = 28px, buttons = 20px (full-pill on FAB). Soft elevation, no harsh shadows.
- **Layout:** Spark-inspired bento grid for content surfaces. Generous whitespace (`--md-sys-spacing-*` 4/8/12/16/24/32/48px scale). Mobile-first responsive (single column at <600px, 2-3 column bento at ≥600px).
- **Motion:** Spring-physics easing tokens (`--md-sys-motion-easing-emphasized` cubic-bezier(0.2, 0.0, 0, 1.0)). Card hover/press uses subtle scale + elevation transition. Page transitions use fade + slight rise.
- **No heavy component library.** Build components from CSS + Preact. Reference: https://m3.material.io/styles for spec values. Bundle target stays <300KB gzipped.

`web/src/styles/tokens.css` exports all design tokens. `web/src/styles/global.css` applies base resets + body styles. Minimal `src/main.tsx` renders a styled landing card with the title "PantryAtlas Navigator" using the new tokens, so the design system is visibly working in T-005 itself.

**Acceptance Criteria:**
- [ ] Files exist: `web/package.json`, `web/vite.config.ts`, `web/tsconfig.json`, `web/src/main.tsx`, `web/index.html`, `web/src/styles/tokens.css`, `web/src/styles/global.css`
- [ ] `cd web && npm install` succeeds (use pnpm if available else npm; document which)
- [ ] `cd web && npm run build` produces `web/dist/index.html` + assets
- [ ] `web/dist/index.html` (after build) renders a landing card with the title "PantryAtlas Navigator", visible body copy, and demonstrates: M3 surface color, expressive typography, 28px corner radius, generous whitespace
- [ ] CSS custom properties present in built CSS: at least `--md-sys-color-primary`, `--md-sys-color-surface-container`, `--md-sys-typescale-display-large`, `--md-sys-shape-corner-extra-large`, `--md-sys-spacing-md`
- [ ] Both `prefers-color-scheme: light` and `prefers-color-scheme: dark` palettes work (verify via DevTools color-scheme toggle — both should look polished, not just inverted)
- [ ] Material Symbols variable font is bundled locally (no `fonts.googleapis.com` references)
- [ ] Total `dist/` size <400KB gzipped (raised from 300KB to budget design-system assets + symbol font subset)
- [ ] `.gitignore` updated: `web/node_modules/`, `web/dist/` (regenerable)
- [ ] Verify in browser: open built index.html, screenshot shows polished landing card; toggle dark mode via DevTools, screenshot still polished
- [ ] Quality checks pass

### T-006: PWA shell (manifest + service worker + install prompt + adaptive icon)
**Description:** Add `web/public/manifest.webmanifest` with name=PantryAtlas, short_name=PantryAtlas, theme_color from the M3 dynamic palette (the seed-derived `--md-sys-color-primary` resolved at build time), background_color from `--md-sys-color-surface`, icons sized 192/512 (both `any` and `maskable` purpose for Android adaptive icons — generated from a single SVG source via `vite-plugin-pwa` or a custom build step). Add a service worker that precaches the app shell and runtime-caches `/navigator/recipes/from-pantry` and `/navigator/pantry` GET responses. Add a styled install-prompt component using the M3 design tokens — a soft elevated card that slides in from the bottom with the "Install PantryAtlas" CTA as a filled-tonal button.

**Acceptance Criteria:**
- [ ] `web/public/manifest.webmanifest` exists with name, short_name, theme_color matching `--md-sys-color-primary`, background_color matching `--md-sys-color-surface`, icons (192 + 512, both `any` and `maskable`), start_url, display=standalone
- [ ] `web/src/sw.ts` (or equivalent) registers and precaches the shell on first load
- [ ] After `npm run build`, `web/dist/sw.js` exists
- [ ] Adaptive maskable icons render correctly in Android's circle/squircle/teardrop preview (use https://maskable.app or document a manual check)
- [ ] Install prompt UI uses M3 design tokens (filled-tonal button, surface-container background, soft elevation, 28px corner radius); not a plain browser default
- [ ] PWA passes a basic Lighthouse audit (manifest valid, service worker present, installable) — document the Lighthouse score in the commit message
- [ ] Service worker registration is gated to production (`if (import.meta.env.PROD)`)
- [ ] Quality checks pass

### T-007: Pantry editor UI (M3 Expressive)
**Description:** `web/src/pages/PantryEditor.tsx`. Built entirely on the T-005 design system. Components:
- **Outlined text field** (M3 spec) for ingredient input with a leading Material Symbol (🌿 `local_florist` for fresh produce, falls back to `add_circle`). Floating label, supporting text, error state styling.
- **Pantry list** as a vertical stack of **filled cards** (`surface-container` background, 28px radius, soft elevation 1). Each card row shows: canonical name (`title-large` typography), raw_text below in `body-medium` if different, expiration date as a tonal **chip** in the trailing slot (color-shifts to error palette when within 1 day).
- **Per-item delete:** trailing **icon button** with `delete_outline` symbol, M3 standard icon-button styling (40px hit target, ripple, tonal hover state).
- **Per-item expiration:** inline **date picker** (use native `<input type="date">` styled with M3 tokens — keeps bundle small).
- **Resolution confirmation:** when typing, debounce 300ms, POST to a `/navigator/pantry/resolve?raw=...` endpoint (add this to T-004 if not already there) that returns the resolved canonical without persisting. Show as a **tonal chip** below the text field: "→ garlic" with primary-container color, or "→ unable to resolve" in error tonal.
- **Smooth animations:** new items animate in (fade + 8px rise, 400ms emphasized easing); removed items fade out + slide left.

Use Preact Signals for state. No Redux, no MobX.

**Acceptance Criteria:**
- [ ] All UI elements use design tokens from T-005 (no hardcoded colors, no inline pixel values for spacing/typography); verify via `grep -E '(color: #|padding: \d+px|font-size: \d+px)' web/src/pages/PantryEditor.tsx` — should return zero matches outside of CSS files
- [ ] User can type "garlic", see "→ garlic" confirmation chip within 500ms of debounce, press enter or tap confirm, ingredient appears in the pantry list with the entry animation
- [ ] User can type "old garlic", confirmation shows "→ garlic", on confirm the card displays canonical_name="garlic" as title and raw_text="old garlic" as supporting line
- [ ] User can type "xyzzy", confirmation chip shows "→ unable to resolve" in error-tonal; user can tap "add as custom" to accept with canonical_name="xyzzy"
- [ ] User can set/change/clear expiration date via the native date picker; the trailing chip updates instantly
- [ ] Chip color shifts to error palette when expiration ≤ 1 day away (verify with a sample item dated tomorrow)
- [ ] User can delete a pantry item; exit animation plays before the card is removed from the DOM
- [ ] Verify in browser via mcp__claude-in-chrome__* tools: load `http://localhost:8090/`, navigate to pantry editor, add 3 items, take screenshot at viewport 390x844 (iPhone 15 size) — screenshot should show polished M3 design with consistent spacing, soft shadows, terracotta accent, no debug borders or default browser styling visible
- [ ] Screenshot in dark mode also looks polished (toggle via DevTools)
- [ ] All cards remain readable at viewport widths from 360px (small phone) to 1280px (laptop)
- [ ] Quality checks pass

### T-008: Recipe results UI (Spark-inspired bento layout)
**Description:** `web/src/pages/RecipeResults.tsx`. Spark-app-inspired bento grid of recipe cards. Built on T-005 tokens.

Layout:
- **Sticky top app bar** (M3 small top app bar): title "PantryAtlas" + leading menu icon + trailing icon button for settings. `surface-container` background with scroll-aware elevation.
- **Hero "Find recipes" FAB:** large extended FAB (`primary-container` color, `search` Material Symbol leading icon) anchored bottom-right on mobile, inline at top on desktop. Disabled state when pantry is empty (use tonal-disabled treatment, not just opacity).
- **Bento grid of recipe cards:** CSS grid with `auto-fit minmax(280px, 1fr)`. Each card is a **filled-tonal card** (M3, `surface-container-high` background) with:
  - **Top:** Coverage ring (SVG, animated stroke-dashoffset, primary color) wrapping a large numerator/denominator like "8 / 10" in `display-small` weight 700. Below the ring: `label-medium` "in pantry".
  - **Middle:** Recipe title in `title-large` (2 lines max, ellipsis), then a chip row showing: missing-count chip (tonal, `secondary-container`), expiring-used chip (only if >0, error-container tonal), substitution-count chip (only if >0).
  - **Bottom:** "View recipe" button (filled-tonal, full width) + subtle source attribution "RecipeNLG · CC-BY-NC-4.0" in `label-small` `on-surface-variant`.
- **Empty state:** When pantry is empty, replace the grid with a centered illustration (Material Symbol `restaurant_menu` at 96px in `on-surface-variant`) + `headline-medium` "Add ingredients to start" + supporting body text + filled CTA "Open pantry editor".
- **Loading state:** Bento grid renders 6 skeleton cards (`surface-container-high` background with M3 skeleton shimmer animation — subtle linear gradient sweep).
- **Detail view ("View recipe"):** Sheet that slides up from bottom on mobile, side-sheet on desktop. M3 sheet styling: 28px top-corner radius, drag handle, surface-container-highest background. Inside: title (`headline-medium`), full ingredient list with pantry-match checkmarks, instructions in `body-large`, source attribution + link to original.
- **Motion:** Cards stagger-enter on results load (50ms delay per card, fade + 12px rise, emphasized easing). Tapping a card animates the expansion to detail sheet (transform-based, 400ms).

**Acceptance Criteria:**
- [ ] All UI elements use design tokens from T-005 — verified by grep as in T-007
- [ ] After pantry has 3+ items, tapping the FAB fires `POST /navigator/recipes/from-pantry` and renders ≥1 card within 3 seconds
- [ ] Each card shows: coverage ring with animated fill, title, chip row (missing/expiring/substitution counts as applicable), "View recipe" button, source attribution
- [ ] Empty-state appears when pantry is empty: illustration + headline + CTA button visible
- [ ] Loading state shows 6 skeleton cards during the fetch (verify by throttling network to "Slow 3G" in DevTools)
- [ ] "View recipe" opens the sheet with full text; sheet animates in from the bottom on mobile (≤600px width) and from the side on desktop (>600px)
- [ ] Source attribution "RecipeNLG · CC-BY-NC-4.0" visible on every card and on the detail sheet
- [ ] Verify in browser via mcp__claude-in-chrome__* tools: open the app, add 5 ingredients, tap FAB, take screenshots at 390x844 (mobile) and 1280x800 (desktop). Both screenshots must show:
  - Polished M3 design with terracotta accent
  - Coverage rings rendering correctly
  - Bento grid (3+ columns on desktop, 1 column on mobile)
  - No browser-default form styling, no debug borders
  - Smooth animations (capture a video frame mid-animation if possible)
- [ ] Dark mode screenshot at the same viewports also polished
- [ ] Stagger-entry animation visible (cards don't all pop in simultaneously)
- [ ] Quality checks pass

### T-009: Offline cache (recent recipes survive airplane mode)
**Description:** Extend the service worker to cache the last N (default 20) recipe-results responses by URL+body hash. Also cache the last 50 individual recipe-detail responses. When offline, serve from cache and show an "offline — showing cached results" banner. Pantry edits made while offline should queue in IndexedDB and POST when reconnected (use the Background Sync API if available, otherwise on next page focus).

**Acceptance Criteria:**
- [ ] After viewing 3 recipe-results responses online, disabling network, reloading the app: previously-viewed results are still browsable
- [ ] Offline banner appears when `navigator.onLine === false`
- [ ] Pantry add/remove operations made while offline queue locally and replay on reconnect (manual test: add 2 items offline, reconnect, GET /navigator/pantry shows both)
- [ ] Cache size bounded: oldest entries evicted when cache exceeds the limit (test by manipulating IndexedDB directly)
- [ ] Verify in browser via Chrome DevTools Network panel: throttle to "Offline", recent results still load
- [ ] Quality checks pass

### T-010: navigator systemd unit + integration with v0.1 stack
**Description:** Add `ops/systemd/pantryatlas-navigator.service` matching the pattern of the v0.1 units. ExecStart runs `uvicorn pantryatlas.navigator.server:app --host 0.0.0.0 --port 8090` (note: 0.0.0.0, not 127.0.0.1 — needs to be reachable from the phone on the LAN). Add to `ops/systemd/install.sh` UNITS array. Update `ops/pi-bootstrap.sh` to also build the frontend (`cd web && npm install && npm run build`) so a fresh bootstrap produces a deployable app.

**Acceptance Criteria:**
- [ ] `ops/systemd/pantryatlas-navigator.service` exists
- [ ] `bash -n` and `systemd-analyze verify` results documented (skip OK if ExecStart binary paths don't exist on dev host)
- [ ] `ops/systemd/install.sh` includes the navigator unit
- [ ] `ops/pi-bootstrap.sh` includes a new stage `stage_web_build` that runs npm install + build (gated by a new stamp file)
- [ ] Pi-bootstrap script still passes `shellcheck` (no new severity-warning issues)
- [ ] Quality checks pass

### T-011: Integration test (Pi-gated, opt-in)
**Description:** `tests/integration/test_navigator_e2e.py` marked `@pytest.mark.pi_integration`. Boots the FastAPI app in-process (no uvicorn — use `httpx.AsyncClient` against `app`), PUTs a 5-item pantry, POSTs to `/recipes/from-pantry`, asserts ≥1 result with a coverage > 0.4, asserts response time <2s. Opt-in via `PANTRYATLAS_PI_INTEGRATION=1` like the v0.1 integration test.

**Acceptance Criteria:**
- [ ] Test file exists with the `@pytest.mark.pi_integration` marker
- [ ] Default `pytest -m 'not pi_integration'` skips the test
- [ ] `PANTRYATLAS_PI_INTEGRATION=1 pytest tests/integration/test_navigator_e2e.py -q` exits 0 on a Pi with ingested recipes
- [ ] Test logs `navigator_e2e_runtime_seconds=<float>` and asserts < 10.0
- [ ] Test asserts the response includes the source attribution field per the license terms
- [ ] Quality checks pass

### T-012: Documentation
**Description:** Add `docs/navigator.md` covering: what the navigator is, how to ingest, how to run the server, how to install the PWA on a phone, the API reference (all 7 endpoints), the ranking algorithm weights and rationale, and the privacy story (everything stays on the Pi, no telemetry, RecipeNLG attribution). Update `README.md` to mention the navigator and link to the new doc. Update `docs/deferred-v0.2.md` to mark `pantryatlas.navigator` as shipped and note what's still deferred (full corpus, narration, cultural-fit ML).

**Acceptance Criteria:**
- [ ] `docs/navigator.md` exists with sections: Overview, Ingestion, Running, PWA install, API reference, Ranking algorithm, Privacy + attribution
- [ ] All 7 navigator endpoints documented with request/response examples
- [ ] README.md links to `docs/navigator.md`
- [ ] `docs/deferred-v0.2.md` updated to remove `pantryatlas.navigator` from the deferred list (move to a "Shipped in v0.2.0" section)
- [ ] Quality checks pass

### T-013: v0.2.0 release
**Description:** Bump version to `0.2.0`, write CHANGELOG entry covering T-001..T-012, tag `v0.2.0`, push, ensure CI green on the tag, comment on issue #1 (v0.2 tracker) checking off the `pantryatlas.navigator` item. Open issue #2 ("v0.3 scope tracker") if the remaining v0.2 items (other submodules) are now better tracked separately.

**Acceptance Criteria:**
- [ ] `pyproject.toml` version is `0.2.0`
- [ ] `CHANGELOG.md` has `## [0.2.0] - YYYY-MM-DD` section enumerating T-001..T-012
- [ ] `git tag v0.2.0` exists locally and on origin
- [ ] CI run on the tagged commit shows `conclusion=success`
- [ ] Comment posted on `PantryAtlas/pantryatlas#1` with the shipped checklist update
- [ ] Quality checks pass

## 4. Functional Requirements

- **FR-1:** A curated subset of RecipeNLG (≥50,000 recipes) must be ingestible into RecipeStore in under 60 minutes on Pi 5.
- **FR-2:** Recipe ingestion must be resumable — re-running the CLI on the same target db must skip already-embedded rows.
- **FR-3:** The pantry→recipes endpoint must return ≤20 ranked recipes in under 2 seconds for a 10-item pantry.
- **FR-4:** Ranking must combine coverage, expiration urgency, substitution distance, and (optionally) cultural fit in a documented, deterministic formula.
- **FR-5:** The PWA must be installable on a phone via the standard browser "Add to Home Screen" flow.
- **FR-6:** The PWA must remain usable when offline for recently-viewed recipes and accept pantry edits that queue and sync on reconnect.
- **FR-7:** All recipe cards must display source attribution ("From RecipeNLG, CC-BY-NC-4.0") to comply with the license.
- **FR-8:** Pantry state must persist across browser reloads and across server restarts (flat JSON at `~/.pantryatlas/pantry.json` is acceptable for v0.2).
- **FR-9:** The navigator service must run as a systemd unit alongside the v0.1 services without exceeding the 6.5GB resident-RAM budget.
- **FR-10:** The PWA must be reachable from a phone on the same Wi-Fi at `http://<pi-host>:8090`.
- **FR-11:** All ingredient-text resolution must go through the existing `pantryatlas.pantry.Matcher` (exact → fuzzy → semantic@0.60); no new matching code is allowed.

## 5. Non-Goals (Out of Scope for v0.2.0)

- **No full 2.1M recipe ingestion.** Curated 50K subset only. Sharding + full corpus deferred to v0.3.
- **No multi-user / accounts.** Single user, single pantry per device.
- **No i18n in the UI.** English-only UI. (bge-m3's multilingual embedding still works at search time — a Spanish query still finds relevant English recipes.)
- **No cultural-fit ML.** Cuisine boost in the ranker is a simple keyword lookup; deeper version with Gemma cuisine classification is v0.3.
- **No Gemma narration / substitution explainer.** That's `pantryatlas.slerp_chef`, a later submodule.
- **No photo-of-fridge ingestion.** Deferred to a `pantryatlas.vision` submodule.
- **No voice input.** Deferred.
- **No production HTTPS / domain hosting.** Local Wi-Fi access only; the operator can layer Tailscale or Cloudflare Tunnel separately.
- **No analytics / telemetry.** Everything stays on the Pi.
- **No recipe editing / user-contributed recipes.** Read-only corpus from RecipeNLG.
- **No nutritional information.** USDA layer is in the deferred-v0.2.md list.
- **No new ingredient-matching code paths.** Reuse `pantryatlas.pantry.Matcher`.

## 6. Technical Considerations

- **Pi 5 8GB RAM budget:**
  - v0.1 baseline: Gemma 4 E4B (~3 GB) + bge-m3 ONNX (~600 MB) + sqlite-vec corpus (<500 MB) + Python/FastAPI/OS (~1 GB) ≈ 5.1 GB.
  - Navigator adds: RecipeStore DB (~250 MB on disk; ~80 MB resident via sqlite page cache) + FastAPI process (~80 MB) + ingestion peaks (transient, releases after run) ≈ ~200 MB resident steady-state.
  - Total: ~5.3 GB resident under normal load. Well within the 6.5 GB cap.
- **Recipe ingestion architecture:** Batched embeddings (64 per batch through `pantryatlas.embeddings.embed`) amortizes bge-m3 throughput. The existing embeddings sidecar at port 8089 is reusable but the ingestion CLI loads its own embedder for batch efficiency.
- **sqlite-vec query latency:** Top-200 retrieval from a 50K-row vec0 index typically completes in <50ms on Pi 5; ranking 200 candidates in Python takes <500ms (bge-m3 cosines for substitution suggestions are the expensive part). Combined <2s budget is comfortable.
- **Service worker strategy:** Cache-first for app shell, stale-while-revalidate for `/navigator/recipes/from-pantry`, network-first for `/navigator/pantry`. Tune later if usage patterns surface different needs.
- **Frontend build:** Vite + Preact + TypeScript. Total bundle target <300KB gzipped. Phone install ergonomics matter — keep the shell small.
- **RecipeNLG license (CC-BY-NC-4.0):** Non-Commercial. Every UI surface that shows recipe content must include source attribution. The whole stack remains free-to-use for personal + community-kitchen contexts, which is the stated mission.
- **Existing services to not break:** v0.1's pi_integration test, all 102 v0.1 tests, the existing systemd units. Run the full pytest suite before each commit.

## 7. Success Metrics

- v0.2.0 ships with tag `v0.2.0` pushed, CI green, [issue #1](https://github.com/PantryAtlas/pantryatlas/issues/1) checklist updated.
- Phone-installed PWA → enter 5 pantry items → tap "Find recipes" → see ranked cards in ≤3 seconds end-to-end.
- Pi 5 stack (v0.1 + navigator) stays under 6.5 GB resident RAM after 24 hours of light use.
- All v0.1 tests still pass; navigator adds ≥30 new tests; total ≥132 tests passing.
- A non-developer can follow `docs/navigator.md` and end up with a working PWA on their phone.

## 8. Open Questions

- **OQ-1 (RESOLVED):** Design system = Material 3 Expressive, Spark-inspired. Implemented via CSS custom properties + `@material/material-color-utilities` for dynamic-color palette generation. NO heavy component library — components built from CSS + Preact. Material Symbols variable font bundled locally. Bundle target raised from 300KB to 400KB gzipped to budget the design system. See T-005 for the design tokens spec; T-007 and T-008 are now visually-load-bearing tasks.

- **OQ-9 (RESOLVED):** Visual design source-of-truth = **Google Stitch** (via Antigravity CLI on this Pi). T-004B generates the design artifacts before any frontend code is written. T-005 implements the design system to match Stitch's tokens; T-007 and T-008 implement screens to match Stitch's mockups within reasonable tolerance. This gives us Google's design intelligence for layout/visual + Claude's implementation precision for code. Stitch's frontend code output (typically React/Tailwind) is reference-only; we adapt to Preact + the CSS-tokens design system from T-005. Iteration: if Stitch's first pass needs adjustment, use `edit_screens` or `generate_variants` in v0.3 — for v0.2.0 we ship what the first pass produces, then iterate post-launch.
- **OQ-2:** The flat `~/.pantryatlas/pantry.json` storage is v0.2-only. v0.3 likely needs a real pantry table when multi-pantry support lands. Schema migration plan should be sketched (not implemented) in `docs/navigator.md`.
- **OQ-3:** Should the recipe-card "view full recipe" modal display the full instructions text, given that RecipeNLG instructions are sometimes long and unstructured? Default: yes, with a max-height scroll container. If this causes UX problems we can switch to a per-recipe URL pattern that links to the original source (RecipeNLG entries include source URLs).
- **OQ-4:** The 50K subset is hardcoded as a default. Should the user be able to pick which 50K (e.g., "give me 50K Italian-leaning recipes" via a curation flag)? Default: no, ship the balanced sample for v0.2; surface as an option in v0.3 when cuisine classification lands.
- **OQ-5:** No HTTPS. Should we ship a self-signed cert + service worker exception for localhost? Service workers require HTTPS in production but accept localhost as an exception, so for `http://<pi-host>:8090` the PWA install flow on a phone might fail. Need to verify during T-006 and document the workaround if needed.
- **OQ-6:** The original prose plan mentioned i18n scaffolding (English + Spanish + Chinese at launch). Explicitly deferring all UI i18n for v0.2 — confirm this is acceptable, since bge-m3 still gives multilingual search. If not acceptable, T-007 and T-008 scope expands materially.

- **OQ-7 (design):** Seed color for the M3 dynamic palette. Default proposal: `#B85C38` (terracotta) — warm, food-associated, generates a distinctive palette that doesn't look like every other generic AI app. Alternatives: `#7A8450` (sage/olive), `#C8932A` (saffron). Final choice can be reconsidered post-T-005 once the generated palette is visible; the choice is a one-line constant change. Document the choice in `docs/navigator.md` design section so future submodules can match the brand.

- **OQ-8 (design):** The original prose plan said "Preact PWA (lightweight)". Adding the M3 design system bumps the bundle from ~150KB to ~400KB gzipped — still well within mobile-network tolerances but no longer trivially small. Acceptable tradeoff for the design quality. If bundle size becomes a problem on slow connections, the M3 utilities can be tree-shaken further or replaced with hardcoded tokens.
