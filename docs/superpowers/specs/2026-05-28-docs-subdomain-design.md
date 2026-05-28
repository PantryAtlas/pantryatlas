# Design — Documentation site at docs.pantryatlas.org

- **Date:** 2026-05-28
- **Status:** Approved (brainstorming) — ready for implementation planning
- **Scope of this document:** The PantryAtlas help-documentation platform — a new
  multilingual docs site served at `docs.pantryatlas.org`, plus a starter set of
  real content. Authoring all help articles for every audience and language is an
  ongoing effort beyond this build; the platform is the part designed here.
- **Branch context:** authored on `feat/docs-site` (off `main`)

## Motivation

The marketing site (`web/marketing/site/`) is a single, deliberately-simple
scrolling landing page. It answers "what is this / is it for me / how do I get
it" and nothing more. As PantryAtlas grows we need a real help system: many
articles across several audiences (non-technical cooks, people setting up a Pi,
community-kitchen operators, and developers), available in multiple languages,
searchable, and easy for contributors to improve.

This is the opposite of the marketing page's "one simple page" shape, so it gets
its own platform rather than being bolted onto the landing page. It still must
honor the project's non-negotiables: the cool-Gemini brand, self-hosted assets,
no third-party requests, no tracking, fully static output to Cloudflare Pages,
and a clean build/deploy over SSH on the Raspberry Pi.

## Decisions locked during brainstorming

- **Subdomain:** `docs.pantryatlas.org` (separate Cloudflare Pages project,
  `pantryatlas-docs`).
- **Authoring format:** Markdown (Astro Starlight content collections).
- **Audiences:** all of them — end-user, setup/hardware, community-kitchen
  operator, developer/contributor.
- **Languages:** English (canonical default) plus Spanish, French, Arabic
  (right-to-left), and Simplified Chinese. Untranslated pages fall back to
  English with a localized "not yet available in your language" notice. Adding a
  sixth language later is one config entry plus a folder.
- **Translation workflow:** machine-translated seed + human review. Translated
  pages carry a status; machine-translated pages show a "machine-translated —
  help us improve" badge linking to the GitHub edit URL.
- **Search:** site-wide, static, privacy-respecting (Pagefind — ships with
  Starlight, no server, no external calls).
- **Deliverable for this build:** the platform (IA, navigation, i18n, search,
  brand theming, build + deploy) plus seed content — see "Seed content" below.

## Chosen approach: Astro + Starlight

Three approaches were weighed: (A) Astro + Starlight, (B) VitePress, (C) a
hand-rolled static generator reusing the marketing `styles.css`. Option C best
matches the marketing site's zero-framework simplicity, but *this* site is large
and multi-faceted — many pages, four audiences, five languages including RTL,
plus search and per-page translation status. Starlight provides all of that
correctly out of the box (its automatic English fallback and native RTL are
especially fiddly to hand-roll), outputs 100% static HTML, and themes cleanly via
CSS variables. **Astro + Starlight was chosen.**

Honest costs accepted with this choice:

- A new build dependency (Astro + Starlight, Node-based) — builds fine over SSH
  on the Pi, just not instant.
- One Content-Security-Policy relaxation: Pagefind search uses WebAssembly, so
  the docs CSP needs `'wasm-unsafe-eval'` in `script-src`. Everything remains
  same-origin — no third party, no tracking. See "CSP" below.

## Information architecture

Seven top-level sidebar groups, ordered from "never touched a Pi" to "writing
code". Each group exists identically per language. Sample leaf pages shown; the
full page list grows over time.

1. **Start here** — What PantryAtlas is · Is it for me? · 30-minute overview ·
   Glossary of terms
2. **Cooking** *(daily end-user use)* — Add what's in your pantry · Scan your
   shelf with the camera · Reading a recipe card & the coverage ring · Refining
   results & swaps · Home vs Community kitchen modes · Expiring-soon ingredients ·
   Install it like an app
3. **Set up your device** *(hardware)* — Choose a Pi 5 (Coral coming soon) · What
   to buy · Flash the image · First boot & Wi-Fi · Find `pantryatlas.local` ·
   First-launch mode pick
4. **Community kitchens** *(operator, 50–500 servings)* — Scaling to hundreds ·
   Bulk ingredients & equipment limits · Many people on the network
5. **Maintenance & troubleshooting** — Back up & move the SD card · Update
   PantryAtlas · Can't reach `pantryatlas.local` · Camera scan problems · Slow
   recipes · Power/SD issues · Reset
6. **Developers** — Architecture overview · Build from source · Run tests ·
   Inference-provider registry / Coral · HTTP API · Contributing · Data sources &
   licenses
7. **Reference** — Glossary · Supported-hardware matrix · Data licenses
   (RecipeNLG, FlavorDB) · Translation status · Release notes

The sidebar renders these as collapsible groups, defined in `astro.config.mjs`.

## Internationalization & translation model

- **Locales:** `en` (default — canonical, used for fallback + UI labels), `es`
  (Español), `fr` (Français), `ar` (العربية, `dir: 'rtl'`), `zh-cn` (简体中文,
  `lang: 'zh-CN'`).
- **Content layout:** `src/content/docs/<locale>/<section>/<page>.md`. Identical
  filenames across locales are what wire up Starlight's fallback and translation
  features.
- **Untranslated page →** Starlight serves the English content automatically and
  shows a localized translation notice. No broken links.
- **Machine-translation badge:** each page's frontmatter carries
  `translationStatus: machine | reviewed` (English pages omit it). A small banner
  component renders on `machine` pages: *"Machine-translated — help us improve
  this page →"* linking to the GitHub edit URL. `reviewed` pages render nothing
  (or a subtle reviewed marker). English pages never show it.
- **Language switcher + "Edit this page":** both are Starlight built-ins. The
  edit link points at the source file on GitHub so corrections become a one-click
  PR.
- **UI string localization:** Starlight's built-in UI strings (search, nav,
  pagination, the fallback notice, Pagefind labels) are localized for all five
  locales via Starlight's i18n translation files.

## Repository layout

Lives in the same repo as the app and marketing site (so "edit this page" maps to
real PRs), as a sibling of `web/marketing/`:

```
web/docs/
  astro.config.mjs        # Starlight integration: locales, sidebar tree, editLink, customCss
  package.json            # scripts: dev / build / preview
  src/
    content.config.ts     # content collections: Starlight schema extended with `translationStatus`
    content/docs/
      en/    {index, start-here/, cooking/, setup/, community/, maintenance/, developers/, reference/}
      es/    fr/    ar/    zh-cn/        # same filenames as en/ → enables fallback
    styles/brand.css      # maps cool-Gemini design tokens → Starlight CSS variables
    components/MtBanner.astro           # the machine-translated badge (Starlight component/page override)
  public/
    fonts/                # DM Sans woff2, reused from web/marketing/site/assets/fonts/
    favicon.svg
    _headers              # Cloudflare Pages headers (CSP etc.); copied to dist/ root at build
```

Build output is `web/docs/dist/` (static).

## Brand theming

The existing design system (`web/design/design-system.json`,
`web/design/DESIGN.md`) is mapped onto Starlight's CSS custom properties in
`brand.css`, loaded via Starlight's `customCss`:

- `--sl-font` → self-hosted **DM Sans** (the two `.woff2` files already in the
  marketing assets). No Google Fonts CDN, no third-party font requests.
- Accent ramp → **Gemini blue `#1a73e8`** and its tonal steps.
- Surfaces → `#fcfcff` background and the `surface-container` token family; soft,
  diffused shadows; rounded corners consistent with the app's vessel feel.
- The `gradient-ember` / `gradient-thinking` washes appear **sparingly** — the
  docs landing hero and the active sidebar item — mirroring the marketing site's
  restraint (gradient used once, then as light accents).
- Starlight's light/dark toggle is kept. Light is primary; dark maps to the
  deep-slate `#111319` surface defined in the design system.

## Build, deploy & CSP

**Build:** `npm run build` in `web/docs/` produces static `dist/`. This runs over
SSH on the Pi (Node build; not instant, but fine).

**Deploy:** separate Cloudflare Pages project.

```
npx wrangler@latest pages deploy web/docs/dist --project-name pantryatlas-docs --branch main
```

The `--branch main` flag is required to deploy to the production branch (known
gotcha from the marketing-site deploys). Attaching the custom domain
`docs.pantryatlas.org` is an operator step in the Cloudflare dashboard — wrangler
cannot attach Pages custom domains.

**CSP — validated first, because it is the one real integration risk.** Starlight
emits a few small inline scripts (e.g. the theme toggle that runs before paint),
and Pagefind uses WebAssembly. The implementation plan's **first task** stands up
a minimal Starlight build, deploys a preview, and locks the exact policy before
any content is written:

- inline scripts handled via **hashes** (Astro's built-in CSP support) so we
  avoid `'unsafe-inline'`,
- `'wasm-unsafe-eval'` added to `script-src` for Pagefind,
- `connect-src 'self'` so Pagefind can fetch its same-origin index chunks,
- everything else mirrors the marketing `_headers` hardening
  (`default-src 'self'`, `img-src 'self' data:`, `frame-ancestors 'none'`,
  `object-src 'none'`, nosniff, no-referrer, restrictive Permissions-Policy).

Success criterion for that first task: a deployed preview with **zero CSP console
violations** and **no third-party network requests**.

## Seed content

What ships in this build:

- **English (real, written in the warm-kitchen-notebook voice that matches the
  marketing site):** the docs landing/index page, one genuine page per top-level
  section (7), and the Glossary — roughly **9 English pages**.
- **Other locales:** the landing page machine-translated into ES, FR, AR, and
  ZH-CN (`translationStatus: machine`) so the MT badge, the language switcher, and
  Arabic RTL are all demonstrably working end-to-end. Every other page in those
  locales falls back to English with the translation notice.

This proves every platform feature with real, visible examples while leaving the
bulk of article-writing and translation as ongoing follow-up work.

## Verification (before declaring done)

- `npm run build` succeeds on the Pi.
- Pagefind search indexes the content and returns results in the browser.
- Language switcher changes locale; navigating to a translated page works.
- Arabic renders right-to-left.
- A page that exists only in English, when viewed under another locale, falls
  back to English and shows the localized "not yet translated" notice.
- The MT banner appears on `translationStatus: machine` pages and links to the
  correct GitHub edit URL; it is absent on English and on `reviewed` pages.
- No Google-Fonts or other third-party network requests (fonts are self-hosted).
- No CSP violations in the browser console.
- Cloudflare Pages preview deploy returns HTTP 200 with the hardened headers.

## Out of scope (noted, deferred)

- **App → docs deep-linking with current locale.** The navigator app on
  `pantryatlas.local` could later link into `docs.pantryatlas.org` in the user's
  active language. Useful, but a v2 enhancement — not built here. Recorded so it
  is not forgotten.
- **CI auto-deploy.** Like the marketing site, deploys are manual via wrangler in
  this build. A GitHub Action to build + deploy on changes to `web/docs/` can be
  added later.
- **Writing the full article set and full translations.** This build delivers the
  platform plus seed content; filling in the remaining pages and human-reviewing
  machine translations is ongoing.
