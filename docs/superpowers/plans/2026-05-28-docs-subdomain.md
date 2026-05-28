# docs.pantryatlas.org Documentation Site — Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Stand up a multilingual, searchable, brand-consistent help-documentation site at `docs.pantryatlas.org`, built from Markdown, plus a starter set of real content.

**Architecture:** A new Astro + Starlight project at `web/docs/`, a sibling of the existing `web/marketing/` site, in the same repo so "edit this page" maps to real GitHub PRs. Starlight provides config-driven locales (English canonical with automatic fallback + translation notices), native RTL, a static Pagefind search index, and CSS-variable theming. Output is 100% static HTML deployed to a dedicated Cloudflare Pages project. A custom `Banner` component override renders a "machine-translated — help improve" badge from page frontmatter. CSP is enforced via Astro's built-in hashing (validated empirically before content is written).

**Tech Stack:** Astro 5, `@astrojs/starlight`, Pagefind (bundled with Starlight), self-hosted DM Sans (`.woff2`), Cloudflare Pages + `wrangler`.

**Spec:** `docs/superpowers/specs/2026-05-28-docs-subdomain-design.md`

**Branch:** `feat/docs-site` (already created off `main`; the spec is committed there).

---

## File structure (created by this plan)

```
web/docs/
  package.json            # scripts + deps (deps populated by npm install)
  astro.config.mjs        # Starlight integration: site, locales, sidebar, editLink, customCss, components, CSP
  tsconfig.json           # extends astro/tsconfigs/strict
  src/
    content.config.ts     # docs collection (schema + translationStatus) + i18n collection
    components/
      MtBanner.astro      # Banner override: machine-translated badge + fallback handling
    styles/
      brand.css           # cool-Gemini design tokens → Starlight CSS variables
      fonts.css           # @font-face for self-hosted DM Sans
    content/
      docs/
        en/               # canonical English content (real seed pages)
          index.md
          start-here/overview.md
          cooking/basics.md
          setup/choose-a-pi.md
          community/scaling.md
          maintenance/troubleshooting.md
          developers/architecture.md
          reference/glossary.md
        es/  fr/  ar/  zh-cn/
          index.md         # machine-translated landing (translationStatus: machine); rest falls back to en
      i18n/
        es.json  fr.json  ar.json  zh-cn.json   # localized UI strings (fallback notice, Pagefind labels, MT badge)
  public/
    favicon.svg
    fonts/
      dm-sans-latin.woff2
      dm-sans-latin-ext.woff2
    _headers            # Cloudflare Pages security headers (CSP handled by Astro meta; this carries the rest)
```

Build output: `web/docs/dist/` (git-ignored).

---

## Conventions for this plan

- All shell commands assume CWD `~/pantryatlas/web/docs/` unless stated otherwise.
- "Build green" means `npm run build` exits 0 and writes `dist/`.
- Some verification is genuinely manual (browser console / rendered RTL). Those steps say **MANUAL** explicitly — do not claim them passed without doing them.
- Commit after every task. Use the shown commit message.

---

### Task 0: Add web/docs build output to .gitignore

**Files:**
- Modify: `.gitignore` (repo root)

- [ ] **Step 1: Append docs ignore rules**

Add these lines to the repo-root `.gitignore`:

```gitignore
# Astro docs site (web/docs)
web/docs/dist/
web/docs/.astro/
web/docs/node_modules/
```

- [ ] **Step 2: Verify the patterns are recognized**

Run (from repo root): `git check-ignore web/docs/dist web/docs/.astro || echo "not yet (dir absent is fine)"`
Expected: prints the paths (once they exist) or the fallback message. No error.

- [ ] **Step 3: Commit**

```bash
cd ~/pantryatlas
git add .gitignore
git commit -m "chore(docs): gitignore web/docs build artifacts"
```

---

### Task 1: Scaffold a minimal Starlight site (English only) and prove it builds

**Files:**
- Create: `web/docs/package.json`
- Create: `web/docs/tsconfig.json`
- Create: `web/docs/astro.config.mjs`
- Create: `web/docs/src/content.config.ts`
- Create: `web/docs/src/content/docs/en/index.md`
- Create: `web/docs/public/favicon.svg`

- [ ] **Step 1: Create the project directory and package.json**

```bash
mkdir -p ~/pantryatlas/web/docs/src/content/docs/en ~/pantryatlas/web/docs/public
```

`web/docs/package.json`:

```json
{
  "name": "pantryatlas-docs",
  "type": "module",
  "version": "0.1.0",
  "private": true,
  "scripts": {
    "dev": "astro dev",
    "build": "astro build",
    "preview": "astro preview",
    "sync": "astro sync"
  }
}
```

- [ ] **Step 2: Install Astro + Starlight (this populates dependency versions in package.json)**

Run: `cd ~/pantryatlas/web/docs && npm install astro@latest @astrojs/starlight@latest sharp@latest`
Expected: installs without error; `package.json` now lists `astro`, `@astrojs/starlight`, `sharp` with resolved versions; `package-lock.json` created.

- [ ] **Step 3: Create tsconfig.json**

`web/docs/tsconfig.json`:

```json
{
  "extends": "astro/tsconfigs/strict",
  "include": [".astro/types.d.ts", "**/*"],
  "exclude": ["dist"]
}
```

- [ ] **Step 4: Create a minimal astro.config.mjs (English only for now)**

`web/docs/astro.config.mjs`:

```js
import { defineConfig } from 'astro/config';
import starlight from '@astrojs/starlight';

export default defineConfig({
  site: 'https://docs.pantryatlas.org',
  integrations: [
    starlight({
      title: 'PantryAtlas Docs',
      defaultLocale: 'en',
      locales: {
        en: { label: 'English' },
      },
    }),
  ],
});
```

- [ ] **Step 5: Create content.config.ts**

`web/docs/src/content.config.ts`:

```ts
import { defineCollection } from 'astro:content';
import { docsLoader } from '@astrojs/starlight/loaders';
import { docsSchema } from '@astrojs/starlight/schema';

export const collections = {
  docs: defineCollection({ loader: docsLoader(), schema: docsSchema() }),
};
```

- [ ] **Step 6: Create the landing page**

`web/docs/src/content/docs/en/index.md`:

```md
---
title: PantryAtlas Help
description: Help and how-to guides for PantryAtlas — the free, open-source smart pantry that lives in your kitchen.
---

Welcome to the PantryAtlas help site. Use the sidebar to find your topic, or
search at the top of the page.
```

- [ ] **Step 7: Add a favicon (reuse the marketing one)**

Run: `cp ~/pantryatlas/web/marketing/site/assets/favicon.svg ~/pantryatlas/web/docs/public/favicon.svg`
Expected: file copied.

- [ ] **Step 8: Build and verify output exists**

Run: `cd ~/pantryatlas/web/docs && npm run build`
Expected: build succeeds; `dist/en/index.html` exists. Verify: `test -f dist/en/index.html && echo OK`

- [ ] **Step 9: Commit**

```bash
cd ~/pantryatlas
git add web/docs/package.json web/docs/package-lock.json web/docs/tsconfig.json web/docs/astro.config.mjs web/docs/src/content.config.ts web/docs/src/content/docs/en/index.md web/docs/public/favicon.svg
git commit -m "feat(docs): scaffold minimal Astro Starlight site"
```

---

### Task 2: Lock the Content-Security-Policy (empirical spike)

This is the one real integration risk per the spec. Starlight emits small inline scripts/styles and Pagefind uses WebAssembly. Determine the exact working policy **before** building out content.

**Files:**
- Modify: `web/docs/astro.config.mjs`
- Create: `web/docs/public/_headers`

- [ ] **Step 1: Enable Astro's built-in CSP with our directives**

In `web/docs/astro.config.mjs`, add an `experimental.csp` block at the top level of the `defineConfig` object (sibling of `integrations`):

```js
  experimental: {
    csp: {
      directives: [
        "default-src 'self'",
        "img-src 'self' data:",
        "font-src 'self'",
        "connect-src 'self'",
        "base-uri 'none'",
        "form-action 'none'",
        "frame-ancestors 'none'",
        "object-src 'none'",
      ],
      scriptDirective: {
        resources: ["'self'", "'wasm-unsafe-eval'"],
      },
      styleDirective: {
        resources: ["'self'"],
      },
    },
  },
```

Astro hashes its own inline `<script>`/`<style>` content and adds those hashes to `script-src`/`style-src` automatically, emitting a `<meta http-equiv="content-security-policy">` into every page.

- [ ] **Step 2: Build; if Astro rejects a csp option key, reconcile with the installed version**

Run: `cd ~/pantryatlas/web/docs && npm run build`
Expected: build succeeds and `dist/en/index.html` contains a `<meta http-equiv="content-security-policy"` tag. Verify: `grep -l "content-security-policy" dist/en/index.html`

If the build errors with an unknown `csp` / `scriptDirective` / `styleDirective` option: run `npx astro --version`, open that version's "Experimental: Content Security Policy" reference, and adjust the key names to match (the *concept* — directives list + per-script/style resources + auto-hashing — is stable; only key names may differ between Astro minors). Do not proceed until the meta tag is present.

- [ ] **Step 3: Create the _headers for the remaining (non-CSP) security headers**

CSP is delivered by Astro's meta tag (so hashes stay correct across Starlight updates). The `_headers` file carries everything else and must **not** set a second `Content-Security-Policy` (a second policy would intersect and likely break Starlight).

`web/docs/public/_headers`:

```
/*
  X-Content-Type-Options: nosniff
  Referrer-Policy: no-referrer
  Permissions-Policy: geolocation=(), microphone=(), camera=(), interest-cohort=()
  X-Frame-Options: DENY
```

- [ ] **Step 4: Serve the build and check the browser console for CSP violations — MANUAL**

Run: `cd ~/pantryatlas/web/docs && npm run preview -- --host`
Open the served URL in a browser. In DevTools Console + Network:
- Confirm the page renders, the theme toggle works, and the **search box returns results** when you type (Pagefind is the WASM consumer — if it's blocked you'll see a CSP error mentioning `wasm-unsafe-eval`).
- Confirm there are **no** "Refused to ... because it violates the Content-Security-Policy" errors.
- Confirm there are **no** requests to any non-`localhost` origin.

Decision rule:
- Search works + zero violations → CSP is locked. Proceed.
- Console shows a `style-src-attr` / inline style-**attribute** violation (Starlight occasionally uses `style="..."` attributes; CSP hashes don't cover attributes): add the single directive `"style-src-attr 'unsafe-inline'"` to the `directives` array. This relaxes **style attributes only** — never scripts — and is an acceptable, narrow exception. Rebuild and re-check.
- Any **script** violation that isn't solved by `wasm-unsafe-eval`: capture the exact console message and stop — escalate rather than adding `'unsafe-inline'` to scripts.

- [ ] **Step 5: Commit**

```bash
cd ~/pantryatlas
git add web/docs/astro.config.mjs web/docs/public/_headers
git commit -m "feat(docs): lock CSP via Astro hashing + Pages security headers"
```

---

### Task 3: Configure all five locales + the 7-group sidebar IA

**Files:**
- Modify: `web/docs/astro.config.mjs`
- Create: one `index`/placeholder page per English section so `autogenerate` has content:
  - `web/docs/src/content/docs/en/start-here/overview.md`
  - `web/docs/src/content/docs/en/cooking/basics.md`
  - `web/docs/src/content/docs/en/setup/choose-a-pi.md`
  - `web/docs/src/content/docs/en/community/scaling.md`
  - `web/docs/src/content/docs/en/maintenance/troubleshooting.md`
  - `web/docs/src/content/docs/en/developers/architecture.md`
  - `web/docs/src/content/docs/en/reference/glossary.md`

(Real prose for these pages lands in Tasks 7–8; here they need only valid frontmatter + a one-line body so the sidebar and build work.)

- [ ] **Step 1: Create the seven section pages as minimal valid stubs**

Each file uses this shape (substitute the per-file title/description/body below):

```md
---
title: <TITLE>
description: <DESCRIPTION>
---

<ONE-LINE BODY>
```

Use these values:

| File | title | description | body |
|---|---|---|---|
| `en/start-here/overview.md` | What PantryAtlas is | A two-minute overview of what PantryAtlas is and who it's for. | PantryAtlas helps you cook from what you already have. |
| `en/cooking/basics.md` | Cooking with PantryAtlas | How to add your pantry, scan your shelf, and read recipe results. | Add what you have; PantryAtlas finds recipes that use it. |
| `en/setup/choose-a-pi.md` | Choose a small computer | Pick and buy the small computer PantryAtlas runs on. | PantryAtlas runs on a Raspberry Pi 5 you keep in your kitchen. |
| `en/community/scaling.md` | Cooking for a crowd | Run PantryAtlas for a community kitchen serving 50–500 people. | Community Kitchen mode favors recipes that scale. |
| `en/maintenance/troubleshooting.md` | Troubleshooting | Fix common problems and keep PantryAtlas healthy. | Most problems are a network or power issue — start here. |
| `en/developers/architecture.md` | Architecture overview | How PantryAtlas is built, for contributors. | PantryAtlas is a local-first Python server with a Preact web UI. |
| `en/reference/glossary.md` | Glossary | Definitions of PantryAtlas terms. | Plain-language definitions of the words we use. |

- [ ] **Step 2: Replace the locales + add sidebar + editLink in astro.config.mjs**

Replace the `starlight({ ... })` options so they read as follows (keep the existing `experimental.csp` block from Task 2 untouched):

```js
    starlight({
      title: 'PantryAtlas Docs',
      defaultLocale: 'en',
      locales: {
        en: { label: 'English' },
        es: { label: 'Español', lang: 'es' },
        fr: { label: 'Français', lang: 'fr' },
        ar: { label: 'العربية', lang: 'ar', dir: 'rtl' },
        'zh-cn': { label: '简体中文', lang: 'zh-CN' },
      },
      editLink: {
        baseUrl: 'https://github.com/PantryAtlas/pantryatlas/edit/main/web/docs/',
      },
      sidebar: [
        { label: 'Start here', translations: { es: 'Empieza aquí', fr: 'Commencer ici', ar: 'ابدأ هنا', 'zh-CN': '从这里开始' }, autogenerate: { directory: 'start-here' } },
        { label: 'Cooking', translations: { es: 'Cocinar', fr: 'Cuisiner', ar: 'الطبخ', 'zh-CN': '烹饪' }, autogenerate: { directory: 'cooking' } },
        { label: 'Set up your device', translations: { es: 'Configura tu dispositivo', fr: 'Configurer votre appareil', ar: 'إعداد جهازك', 'zh-CN': '设置你的设备' }, autogenerate: { directory: 'setup' } },
        { label: 'Community kitchens', translations: { es: 'Cocinas comunitarias', fr: 'Cuisines communautaires', ar: 'المطابخ المجتمعية', 'zh-CN': '社区厨房' }, autogenerate: { directory: 'community' } },
        { label: 'Maintenance & troubleshooting', translations: { es: 'Mantenimiento y solución de problemas', fr: 'Maintenance et dépannage', ar: 'الصيانة واستكشاف الأخطاء', 'zh-CN': '维护与故障排除' }, autogenerate: { directory: 'maintenance' } },
        { label: 'Developers', translations: { es: 'Desarrolladores', fr: 'Développeurs', ar: 'المطورون', 'zh-CN': '开发者' }, autogenerate: { directory: 'developers' } },
        { label: 'Reference', translations: { es: 'Referencia', fr: 'Référence', ar: 'مرجع', 'zh-CN': '参考' }, autogenerate: { directory: 'reference' } },
      ],
    }),
```

- [ ] **Step 3: Build and verify all locales + sidebar render**

Run: `cd ~/pantryatlas/web/docs && npm run build`
Expected: build succeeds. Verify the language switcher target pages and RTL attribute:
```bash
test -f dist/en/start-here/overview/index.html && echo "en OK"
grep -q 'dir="rtl"' dist/ar/index.html && echo "ar RTL OK"
```
Both echoes must print. (`dist/ar/index.html` is the Arabic landing — it exists once Task 6 adds `ar/index.md`; until then Arabic pages fall back and the file to check is `dist/ar/start-here/overview/index.html`. Use whichever Arabic HTML file exists.)

- [ ] **Step 4: Confirm fallback works — MANUAL**

Run `npm run preview -- --host`, open the site, switch language to Français, and navigate to any non-landing page. Expected: the English content renders with Starlight's localized "not translated" notice (we localize the notice text in Task 5). No 404.

- [ ] **Step 5: Commit**

```bash
cd ~/pantryatlas
git add web/docs/astro.config.mjs web/docs/src/content/docs/en
git commit -m "feat(docs): five locales (incl. Arabic RTL) + 7-group sidebar IA"
```

---

### Task 4: Extend the content schema with `translationStatus` + register the i18n collection

**Files:**
- Modify: `web/docs/src/content.config.ts`

- [ ] **Step 1: Update content.config.ts**

Replace the file contents with:

```ts
import { defineCollection } from 'astro:content';
import { z } from 'astro/zod';
import { docsLoader, i18nLoader } from '@astrojs/starlight/loaders';
import { docsSchema, i18nSchema } from '@astrojs/starlight/schema';

export const collections = {
  docs: defineCollection({
    loader: docsLoader(),
    schema: docsSchema({
      extend: z.object({
        // Only set on translated (non-English) pages.
        // 'machine' shows the "help improve" badge; 'reviewed' suppresses it.
        translationStatus: z.enum(['machine', 'reviewed']).optional(),
      }),
    }),
  }),
  i18n: defineCollection({
    loader: i18nLoader(),
    schema: i18nSchema({
      // Custom UI string consumed by MtBanner (Task 6). Without this extend,
      // i18nSchema rejects unknown keys in the locale JSON files.
      extend: z.object({ 'mtBanner.text': z.string().optional() }),
    }),
  }),
};
```

- [ ] **Step 2: Sync types and build**

Run: `cd ~/pantryatlas/web/docs && npm run sync && npm run build`
Expected: both succeed; no schema/type errors. (A page may now declare `translationStatus` in frontmatter without a validation error — exercised in Task 6.)

- [ ] **Step 3: Commit**

```bash
cd ~/pantryatlas
git add web/docs/src/content.config.ts
git commit -m "feat(docs): add translationStatus frontmatter field + i18n collection"
```

---

### Task 5: Localize UI strings (fallback notice, search labels, MT badge string)

**Files:**
- Create: `web/docs/src/content/i18n/es.json`
- Create: `web/docs/src/content/i18n/fr.json`
- Create: `web/docs/src/content/i18n/ar.json`
- Create: `web/docs/src/content/i18n/zh-cn.json`

Starlight reads these to translate built-in UI. We also add one **custom** key, `mtBanner.text`, consumed by the `MtBanner` component in Task 6. (English uses Starlight defaults; the custom English string is hardcoded in the component as the fallback.)

- [ ] **Step 1: Create es.json**

```json
{
  "i18n.untranslatedContent": "Este contenido aún no está disponible en tu idioma. Se muestra en inglés.",
  "search.label": "Buscar",
  "mtBanner.text": "Traducción automática — ayúdanos a mejorar esta página"
}
```

- [ ] **Step 2: Create fr.json**

```json
{
  "i18n.untranslatedContent": "Ce contenu n'est pas encore disponible dans votre langue. Affiché en anglais.",
  "search.label": "Rechercher",
  "mtBanner.text": "Traduction automatique — aidez-nous à améliorer cette page"
}
```

- [ ] **Step 3: Create ar.json**

```json
{
  "i18n.untranslatedContent": "هذا المحتوى غير متوفر بعد بلغتك. يتم عرضه بالإنجليزية.",
  "search.label": "بحث",
  "mtBanner.text": "ترجمة آلية — ساعدنا في تحسين هذه الصفحة"
}
```

- [ ] **Step 4: Create zh-cn.json**

```json
{
  "i18n.untranslatedContent": "此内容尚未提供你的语言版本，现以英文显示。",
  "search.label": "搜索",
  "mtBanner.text": "机器翻译 — 帮助我们改进此页面"
}
```

- [ ] **Step 5: Build and verify the fallback notice is localized — MANUAL**

Run: `cd ~/pantryatlas/web/docs && npm run build && npm run preview -- --host`
Switch to Français, open a non-landing page, confirm the notice now reads the French string. Confirm the search placeholder is localized per locale.

- [ ] **Step 6: Commit**

```bash
cd ~/pantryatlas
git add web/docs/src/content/i18n
git commit -m "feat(docs): localize fallback notice, search, and MT-badge strings"
```

---

### Task 6: Build the machine-translated badge (Banner override) + demo it in all 4 locales

The badge appears only when the current page's frontmatter has `translationStatus: 'machine'`. We override Starlight's `Banner` component. We also add the real machine-translated landing pages so the badge, switcher, and RTL are all demonstrable end-to-end.

**Files:**
- Create: `web/docs/src/components/MtBanner.astro`
- Modify: `web/docs/astro.config.mjs` (register the component override)
- Create: `web/docs/src/content/docs/es/index.md`
- Create: `web/docs/src/content/docs/fr/index.md`
- Create: `web/docs/src/content/docs/ar/index.md`
- Create: `web/docs/src/content/docs/zh-cn/index.md`

- [ ] **Step 1: Create the MtBanner component**

`web/docs/src/components/MtBanner.astro`:

```astro
---
import Default from '@astrojs/starlight/components/Banner.astro';
const { entry, editUrl } = Astro.locals.starlightRoute;
const isMachine = entry.data.translationStatus === 'machine';
const text =
  Astro.locals.t('mtBanner.text') ??
  'Machine-translated — help us improve this page';
---

{isMachine && (
  <div class="mt-banner" dir="auto">
    <span>{text}</span>
    {editUrl && <a href={editUrl.href}>↗</a>}
  </div>
)}

{/* Preserve any normal frontmatter banner below ours */}
<Default><slot /></Default>

<style>
  .mt-banner {
    display: flex;
    gap: 0.5rem;
    align-items: center;
    justify-content: center;
    padding: 0.4rem 0.75rem;
    font-size: var(--sl-text-xs);
    background: var(--sl-color-blue-low, var(--sl-color-gray-6));
    color: var(--sl-color-blue-high, var(--sl-color-white));
    border-bottom: 1px solid var(--sl-color-hairline);
  }
  .mt-banner a { color: inherit; text-decoration: underline; }
</style>
```

Note: `Astro.locals.t(...)` is Starlight's translation helper exposed on locals; if the installed Starlight version exposes UI strings differently, read the key via `Astro.locals.starlightRoute.locale` and Starlight's `useTranslations` import instead. The English fallback string in `text` guarantees the component never renders empty.

- [ ] **Step 2: Register the override in astro.config.mjs**

Inside the `starlight({ ... })` options (sibling of `sidebar`), add:

```js
      components: {
        Banner: './src/components/MtBanner.astro',
      },
```

- [ ] **Step 3: Add the machine-translated landing pages**

`web/docs/src/content/docs/es/index.md`:

```md
---
title: Ayuda de PantryAtlas
description: Guías y ayuda para PantryAtlas — la despensa inteligente, libre y de código abierto, que vive en tu cocina.
translationStatus: machine
---

Te damos la bienvenida al sitio de ayuda de PantryAtlas. Usa la barra lateral
para encontrar tu tema, o busca en la parte superior de la página.
```

`web/docs/src/content/docs/fr/index.md`:

```md
---
title: Aide PantryAtlas
description: Guides et aide pour PantryAtlas — le garde-manger intelligent, libre et open source, installé dans votre cuisine.
translationStatus: machine
---

Bienvenue sur le site d'aide de PantryAtlas. Utilisez la barre latérale pour
trouver votre sujet, ou faites une recherche en haut de la page.
```

`web/docs/src/content/docs/ar/index.md`:

```md
---
title: مساعدة PantryAtlas
description: أدلة ومساعدة لـ PantryAtlas — مخزن المؤن الذكي المجاني والمفتوح المصدر الذي يعيش في مطبخك.
translationStatus: machine
---

مرحبًا بك في موقع مساعدة PantryAtlas. استخدم الشريط الجانبي للعثور على موضوعك،
أو ابحث في أعلى الصفحة.
```

`web/docs/src/content/docs/zh-cn/index.md`:

```md
---
title: PantryAtlas 帮助
description: PantryAtlas 的帮助和操作指南 —— 一款免费、开源、运行在你厨房里的智能食品柜。
translationStatus: machine
---

欢迎来到 PantryAtlas 帮助站点。使用侧边栏查找你的主题，或在页面顶部进行搜索。
```

- [ ] **Step 4: Build and assert the badge renders on machine pages and not on English**

Grep the **visible badge text** (locale-specific), not the CSS class — the class
can appear in inlined critical CSS even when the banner did not render.

Run:
```bash
cd ~/pantryatlas/web/docs && npm run build
grep -q "Traducción automática" dist/es/index.html && echo "es badge OK"
grep -q "ترجمة آلية" dist/ar/index.html && echo "ar badge OK"
grep -Eq "Traducción automática|Traduction automatique|机器翻译|ترجمة آلية|help us improve" dist/en/index.html && echo "EN BADGE LEAKED (BUG)" || echo "en clean OK"
```
Expected: `es badge OK`, `ar badge OK`, `en clean OK`. If `EN BADGE LEAKED` prints, the conditional is wrong — fix before committing.

- [ ] **Step 5: Visually confirm the badge + RTL — MANUAL**

`npm run preview -- --host`; open `/ar/` (badge text right-aligned, page RTL) and `/es/` (badge shows, links to GitHub edit URL). Open `/en/` (no badge).

- [ ] **Step 6: Commit**

```bash
cd ~/pantryatlas
git add web/docs/src/components/MtBanner.astro web/docs/astro.config.mjs web/docs/src/content/docs/es web/docs/src/content/docs/fr web/docs/src/content/docs/ar web/docs/src/content/docs/zh-cn
git commit -m "feat(docs): machine-translated badge + demo landing pages (es/fr/ar/zh-cn)"
```

---

### Task 7: Brand theming — self-hosted DM Sans + cool-Gemini tokens

**Files:**
- Create: `web/docs/public/fonts/dm-sans-latin.woff2` (copied)
- Create: `web/docs/public/fonts/dm-sans-latin-ext.woff2` (copied)
- Create: `web/docs/src/styles/fonts.css`
- Create: `web/docs/src/styles/brand.css`
- Modify: `web/docs/astro.config.mjs` (add `customCss`)

- [ ] **Step 1: Copy the DM Sans woff2 files from the marketing site**

```bash
mkdir -p ~/pantryatlas/web/docs/public/fonts
cp ~/pantryatlas/web/marketing/site/assets/fonts/dm-sans-latin.woff2 ~/pantryatlas/web/docs/public/fonts/
cp ~/pantryatlas/web/marketing/site/assets/fonts/dm-sans-latin-ext.woff2 ~/pantryatlas/web/docs/public/fonts/
```
Expected: two files present in `web/docs/public/fonts/`.

- [ ] **Step 2: Create the @font-face CSS**

`web/docs/src/styles/fonts.css`:

```css
@font-face {
  font-family: 'DM Sans';
  font-style: normal;
  font-weight: 100 1000;
  font-display: swap;
  src: url('/fonts/dm-sans-latin.woff2') format('woff2');
  unicode-range: U+0000-00FF, U+0131, U+0152-0153, U+02BB-02BC, U+02C6, U+02DA, U+02DC, U+2000-206F, U+2074, U+20AC, U+2122, U+2191, U+2193, U+2212, U+2215, U+FEFF, U+FFFD;
}
@font-face {
  font-family: 'DM Sans';
  font-style: normal;
  font-weight: 100 1000;
  font-display: swap;
  src: url('/fonts/dm-sans-latin-ext.woff2') format('woff2');
  unicode-range: U+0100-024F, U+0259, U+1E00-1EFF, U+2020, U+20A0-20AB, U+20AD-20CF, U+2113, U+2C60-2C7F, U+A720-A7FF;
}
```

(Note: DM Sans covers Latin only. Arabic and Chinese glyphs fall through to the system stack defined in `brand.css` — acceptable and avoids shipping large CJK/Arabic font files. Verified visually in Task 9.)

- [ ] **Step 3: Create the brand token mapping**

`web/docs/src/styles/brand.css`:

```css
:root {
  /* Typography: self-hosted DM Sans, system fallback covers AR/ZH glyphs */
  --sl-font: 'DM Sans', system-ui, -apple-system, 'Segoe UI', Roboto, sans-serif;

  /* Accent ramp — cool-Gemini blue (#1a73e8) */
  --sl-color-accent-low: #d8e2ff;
  --sl-color-accent: #1a73e8;
  --sl-color-accent-high: #00184a;

  /* Surfaces (light is primary) */
  --sl-color-white: #1a1b22;        /* text on light */
  --sl-color-gray-1: #2f3036;
  --sl-color-gray-2: #44464e;
  --sl-color-gray-3: #74767e;
  --sl-color-gray-4: #c6c8d3;
  --sl-color-gray-5: #e0e3ee;
  --sl-color-gray-6: #eceef7;
  --sl-color-gray-7: #f4f5fb;
  --sl-color-bg: #fcfcff;
  --sl-color-bg-nav: #f4f5fb;
  --sl-color-bg-sidebar: #fcfcff;

  /* Softer corners to echo the app's vessel feel */
  --sl-border-radius: 0.75rem;
}

/* Dark mode → deep slate from the design system */
:root[data-theme='dark'] {
  --sl-color-accent-low: #00295c;
  --sl-color-accent: #4285f4;
  --sl-color-accent-high: #d8e2ff;
  --sl-color-white: #eef0f9;
  --sl-color-bg: #111319;
  --sl-color-bg-nav: #181b22;
  --sl-color-bg-sidebar: #111319;
}

/* The gradient appears sparingly: the active sidebar item */
.sidebar a[aria-current='page'] {
  background-image: linear-gradient(135deg, #1a73e8, #9b72cb);
  color: #ffffff;
}
```

- [ ] **Step 4: Wire the stylesheets via customCss**

Inside the `starlight({ ... })` options, add (order matters — fonts before brand):

```js
      customCss: ['./src/styles/fonts.css', './src/styles/brand.css'],
```

- [ ] **Step 5: Build and assert no third-party font/host references in output**

Run:
```bash
cd ~/pantryatlas/web/docs && npm run build
grep -rho "https://[a-z0-9./-]*" dist/en/index.html | grep -v "docs.pantryatlas.org" | grep -Ei "googleapis|gstatic|fonts\.|cdn" && echo "THIRD-PARTY REF FOUND (BUG)" || echo "no third-party refs OK"
```
Expected: `no third-party refs OK`.

- [ ] **Step 6: Visually confirm brand — MANUAL**

`npm run preview -- --host`: DM Sans is in use, accent is Gemini blue, active sidebar item shows the gradient, dark-mode toggle yields deep slate.

- [ ] **Step 7: Commit**

```bash
cd ~/pantryatlas
git add web/docs/public/fonts web/docs/src/styles web/docs/astro.config.mjs
git commit -m "feat(docs): cool-Gemini theming with self-hosted DM Sans"
```

---

### Task 8: Write the real English seed content

Replace the Task-3 stubs with genuine, shippable help articles in the warm-kitchen-notebook voice (short sentences, concrete nouns, cite only what's true — match `web/marketing/DESIGN.md`). Facts are drawn from the marketing site and `ROBOT.md`/repo.

**Files (all Modify — they exist as stubs from Task 3, plus the landing):**
- `web/docs/src/content/docs/en/index.md`
- `web/docs/src/content/docs/en/start-here/overview.md`
- `web/docs/src/content/docs/en/cooking/basics.md`
- `web/docs/src/content/docs/en/setup/choose-a-pi.md`
- `web/docs/src/content/docs/en/community/scaling.md`
- `web/docs/src/content/docs/en/maintenance/troubleshooting.md`
- `web/docs/src/content/docs/en/developers/architecture.md`
- `web/docs/src/content/docs/en/reference/glossary.md`

- [ ] **Step 1: Landing page** — `en/index.md`:

```md
---
title: PantryAtlas Help
description: Help and how-to guides for PantryAtlas — the free, open-source smart pantry that lives in your kitchen.
---

PantryAtlas is a small computer that lives in your kitchen and helps you cook
delicious food from what's already on your shelf. This is the help site.

- **New here?** Start with [What PantryAtlas is](/en/start-here/overview/).
- **Setting one up?** Go to [Choose a small computer](/en/setup/choose-a-pi/).
- **Cooking today?** See [Cooking with PantryAtlas](/en/cooking/basics/).
- **Running a community kitchen?** See [Cooking for a crowd](/en/community/scaling/).
- **Something wrong?** See [Troubleshooting](/en/maintenance/troubleshooting/).

Use the search box at the top to find anything. Pages not yet translated into
your language are shown in English.
```

- [ ] **Step 2: Overview** — `en/start-here/overview.md`:

```md
---
title: What PantryAtlas is
description: A two-minute overview of what PantryAtlas is and who it's for.
---

PantryAtlas is a computer the size of a deck of cards that you keep in your
kitchen. Plug it into power and your Wi-Fi. From any phone or laptop on your home
network, open a browser and go to **pantryatlas.local**. Type what's in your
pantry, or snap a photo of your shelf. PantryAtlas shows you real recipes you can
cook with what you have, ranked by how much of your ingredients they use.

## Who it's for

- **Home cooks** feeding a family of four to ten.
- **Community kitchens** — soup kitchens, food pantries, shelters — feeding
  fifty to five hundred.
- Anyone in between: school cafeterias, refugee kitchens, a college house.

## What makes it different

- **Free forever.** The software is free and open source (Apache 2.0). You buy
  the small computer once.
- **Stays local.** Your pantry never leaves the device. No cloud account, no
  tracking.
- **Genuinely delicious.** It combines ingredient coverage with flavor-pairing
  research, so matches taste good — not just technically possible.

Next: [Choose a small computer](/en/setup/choose-a-pi/).
```

- [ ] **Step 3: Cooking** — `en/cooking/basics.md`:

```md
---
title: Cooking with PantryAtlas
description: How to add your pantry, scan your shelf, and read recipe results.
---

## Add what you have

Open **pantryatlas.local** in any browser on your home network. Type ingredients
into the add box one at a time, or tap the camera button and point your phone at
your shelf — the on-device model reads what it sees. No photo ever leaves the
device.

## Read a recipe card

Every recipe shows a **coverage ring**. A ring reading 8/10 means you already
have 8 of the 10 ingredients. Cards are ranked so the ones using the most of what
you have come first. Ingredients about to expire get a small boost so nothing
goes to waste.

## Refine and swap

- **Refine** re-ranks the current results more carefully.
- **Swaps** suggest substitutions for the ingredients you're missing.

## Home vs Community kitchen

Pick a mode from the top bar. **Home Kitchen** targets 4–10 servings. **Community
Kitchen** favors recipes that scale to hundreds, use bulk-friendly ingredients,
and need minimum special equipment. You can switch anytime.

## Install it like an app

- **iPhone:** Share → Add to Home Screen.
- **Android:** menu → Install app.
```

- [ ] **Step 4: Setup** — `en/setup/choose-a-pi.md`:

```md
---
title: Choose a small computer
description: Pick and buy the small computer PantryAtlas runs on.
---

PantryAtlas runs on a small computer you keep in your kitchen — a one-time
purchase of around $120.

## Recommended: Raspberry Pi 5 (8GB)

A Pi 5 kit from CanaKit, Adafruit, or Amazon includes everything you need: the
computer, a microSD card, a USB-C power supply, and a small case. Around $120, and
fast enough for everything PantryAtlas does. Your data lives on the microSD card,
so it's easy to back up or move to a fresh card.

## Coming soon: Coral edition

Google and Synaptics released a new Coral board — a tiny, low-power computer with
an on-board AI chip. A PantryAtlas edition is in progress: it runs a small model
on the board and borrows a more powerful computer on your network for heavy work.
It isn't ready yet — for today, pick the Pi 5.

## Then set it up

1. Download the pre-built image from GitHub releases.
2. Write it to the microSD card with the free Raspberry Pi Imager (~8 minutes).
3. Insert the card, plug in power and Wi-Fi (or ethernet). Wait for the solid
   green light (~1 minute).
4. Open **pantryatlas.local** in any browser on the same network. Pick Home or
   Community Kitchen on first launch. Done.

Stuck? See [Troubleshooting](/en/maintenance/troubleshooting/).
```

- [ ] **Step 5: Community** — `en/community/scaling.md`:

```md
---
title: Cooking for a crowd
description: Run PantryAtlas for a community kitchen serving 50–500 people.
---

Switch to **Community Kitchen** mode from the top bar. PantryAtlas then ranks
recipes that:

- **Scale linearly** to dozens or hundreds of servings.
- Use **bulk-friendly ingredients** that arrive by the case.
- Need **minimum specialized equipment**.

## A typical day

A donation truck drops off mixed produce, dry goods, and proteins. Add them by
typing or by photographing the delivery. PantryAtlas surfaces recipes that use
the most of what arrived, so less is wasted and prep is simpler.

## Many people on the network

Anyone on the same Wi-Fi can open **pantryatlas.local** at the same time — line
cooks, volunteers, the coordinator. There are no accounts to manage.

For backups and updates, see
[Troubleshooting](/en/maintenance/troubleshooting/).
```

- [ ] **Step 6: Maintenance** — `en/maintenance/troubleshooting.md`:

```md
---
title: Troubleshooting
description: Fix common problems and keep PantryAtlas healthy.
---

## I can't reach pantryatlas.local

- Make sure your phone or laptop is on the **same Wi-Fi** as the device.
- Wait for the **solid green light** — that means PantryAtlas is running.
- Some networks block `.local` names. Try the device's IP address instead (check
  your router's device list).

## The camera scan misreads my shelf

- Improve lighting and hold the phone steady.
- You can always correct items by typing — the photo is only a shortcut.

## Recipes are slow to appear

- The first search after boot warms up the model and is slower; later searches
  are faster.
- On a busy network, give it a few extra seconds.

## Back up or move your data

Your data lives on the microSD card. Power down, remove the card, and copy its
image with Raspberry Pi Imager (or any disk-image tool) to back up. Restore by
writing that image to a fresh card.

## Update PantryAtlas

Download the latest image from GitHub releases and write it to the card. Back up
first if you want to keep your current data.

## Start over

Re-flash the microSD card with a fresh image. This erases everything on the card.
```

- [ ] **Step 7: Developers** — `en/developers/architecture.md`:

```md
---
title: Architecture overview
description: How PantryAtlas is built, for contributors.
---

PantryAtlas is a **local-first** application: a Python server and a Preact web UI
that run entirely on the small computer in your kitchen. Nothing is sent to a
cloud.

## The pieces

- **Server** (`pantryatlas/`): Python. Serves the web UI and a small HTTP API,
  ranks recipes, and talks to the on-device model.
- **Web UI** (`web/`): Preact + Vite. The Navigator app you use at
  `pantryatlas.local`.
- **Recipe + flavor data:** the public RecipeNLG corpus (CC-BY-NC-4.0) and
  FlavorDB (CC-BY-NC-3.0), stored locally.
- **Model:** a Gemma model runs on-device for vision and language tasks.
- **Inference-provider registry:** lets the device borrow a more capable computer
  on the LAN for heavy work, falling back to the on-board model. See the design
  notes in `docs/superpowers/specs/`.

## Build from source

```bash
git clone https://github.com/PantryAtlas/pantryatlas
cd pantryatlas
pip install -e ".[dev]"
pytest
```

## Contributing

Pull requests are welcome (Apache 2.0). Run `ruff check .` and `pytest` before
opening a PR. Translations: edit the matching file under `web/docs/src/content/`
and open a PR — the "machine-translated" badge links straight to the edit page.
```

- [ ] **Step 8: Glossary** — `en/reference/glossary.md`:

```md
---
title: Glossary
description: Plain-language definitions of PantryAtlas terms.
---

**Coverage ring** — the circle on a recipe card showing how many of its
ingredients you already have (e.g. 8/10).

**Community Kitchen mode** — a setting that ranks recipes which scale to hundreds
of servings.

**Home Kitchen mode** — a setting that targets 4–10 servings.

**Gemma** — the open AI model from Google that runs on your device for reading
photos and understanding ingredients.

**Local-first** — runs entirely on the computer in your kitchen; your data never
leaves the device.

**pantryatlas.local** — the web address of the small computer on your home
network.

**Raspberry Pi 5** — the recommended small computer PantryAtlas runs on.

**Coverage** — how much of your pantry a recipe uses; the main ranking signal.

**Swap** — a suggested substitution for an ingredient you're missing.
```

- [ ] **Step 9: Build and verify content + internal links resolve**

Run: `cd ~/pantryatlas/web/docs && npm run build`
Expected: build succeeds with no broken-link warnings for the in-page links above. Spot-check: `test -f dist/en/reference/glossary/index.html && echo OK`

- [ ] **Step 10: Commit**

```bash
cd ~/pantryatlas
git add web/docs/src/content/docs/en
git commit -m "feat(docs): real English seed content across all sections"
```

---

### Task 9: Full end-to-end verification

No new files — this task confirms every spec acceptance criterion against a real build before deploy.

- [ ] **Step 1: Clean build on the Pi**

Run: `cd ~/pantryatlas/web/docs && rm -rf dist && npm run build`
Expected: exits 0; `dist/` written.

- [ ] **Step 2: Automated output assertions**

Run:
```bash
cd ~/pantryatlas/web/docs
grep -q 'dir="rtl"' dist/ar/index.html && echo "RTL OK"
grep -q "Traduction automatique" dist/fr/index.html && echo "MT badge OK"
grep -Eq "Traducción automática|Traduction automatique|机器翻译|ترجمة آلية|help us improve" dist/en/index.html && echo "EN LEAK BUG" || echo "EN clean OK"
test -d dist/pagefind && echo "Pagefind index OK"
grep -q "content-security-policy" dist/en/index.html && echo "CSP meta OK"
grep -rho "https://[a-z0-9./-]*" dist/en/index.html | grep -Ei "googleapis|gstatic|cdn|fonts\." && echo "THIRD-PARTY BUG" || echo "no third-party OK"
```
Expected: `RTL OK`, `MT badge OK`, `EN clean OK`, `Pagefind index OK`, `CSP meta OK`, `no third-party OK`.

- [ ] **Step 3: Browser pass on the preview — MANUAL**

`npm run preview -- --host`. Confirm, with DevTools open:
- Search returns results (type a word like "recipe").
- Language switcher works; Arabic is RTL; Chinese landing renders (system CJK font).
- A French non-landing page falls back to English with the French notice.
- MT badge shows on translated landings, links to the GitHub edit URL, absent on English.
- **Zero** CSP violations and **zero** non-localhost network requests in the Network tab.

- [ ] **Step 4: Commit (only if any fix was needed)**

```bash
cd ~/pantryatlas
git add -A web/docs
git commit -m "fix(docs): verification adjustments" || echo "nothing to commit"
```

---

### Task 10: Deploy to Cloudflare Pages + operator dashboard steps

**Files:** none (deploy + docs).

- [ ] **Step 1: Deploy a preview build**

Run:
```bash
cd ~/pantryatlas/web/docs
npx wrangler@latest pages deploy dist --project-name pantryatlas-docs --branch preview
```
Expected: wrangler creates the `pantryatlas-docs` project on first run and prints a `*.pantryatlas-docs.pages.dev` preview URL. (If it prompts to create the project, accept.)

- [ ] **Step 2: Verify the preview over HTTPS — MANUAL**

Open the printed preview URL. Re-run the Step-3 browser checks from Task 9 against the live preview. Confirm response headers include `X-Content-Type-Options: nosniff` and the CSP meta tag is present in the HTML.
```bash
curl -sI <preview-url> | grep -i "x-content-type-options"
```

- [ ] **Step 3: Deploy to production branch**

Run:
```bash
cd ~/pantryatlas/web/docs
npx wrangler@latest pages deploy dist --project-name pantryatlas-docs --branch main
```
Expected: production deploy on `pantryatlas-docs.pages.dev`. The `--branch main` flag is required (known gotcha — without it the deploy lands on a preview alias, not production).

- [ ] **Step 4: Operator dashboard steps (cannot be done by wrangler) — MANUAL**

In the Cloudflare dashboard, for project `pantryatlas-docs`:
1. **Custom domains → Set up a custom domain →** `docs.pantryatlas.org`. Cloudflare adds the CNAME automatically when the zone is on Cloudflare.
2. Wait for the certificate to issue, then load `https://docs.pantryatlas.org` and re-run the browser checks.

- [ ] **Step 5: Record the re-deploy command in the repo for future edits**

Append to `web/docs/package.json` scripts:

```json
    "deploy": "astro build && wrangler pages deploy dist --project-name pantryatlas-docs --branch main"
```

Run: `cd ~/pantryatlas/web/docs && npm pkg get scripts.deploy` to confirm it's set.

- [ ] **Step 6: Commit**

```bash
cd ~/pantryatlas
git add web/docs/package.json
git commit -m "chore(docs): add deploy script for pantryatlas-docs Pages project"
```

---

## Self-review against the spec

- **Subdomain + separate Pages project** → Task 10. ✓
- **Markdown authoring (Starlight)** → Tasks 1, 3, 8. ✓
- **All audiences IA (7 groups)** → Task 3 sidebar + Task 8 content. ✓
- **Locales EN/ES/FR/AR(RTL)/ZH + English fallback + notice** → Tasks 3, 5. ✓
- **Machine-translated badge + review status** → Tasks 4 (schema), 6 (component + demo pages). ✓
- **Static, privacy-respecting search** → Pagefind (Starlight built-in), asserted Tasks 2, 9. ✓
- **Cool-Gemini theming, self-hosted DM Sans, no third-party** → Task 7, asserted Tasks 7, 9. ✓
- **Strict CSP / security headers, no tracking** → Task 2 (spike), asserted Tasks 2, 9, 10. ✓
- **Seed content (9 EN pages + 4 MT landings)** → Tasks 6, 8. ✓
- **Build + deploy clean over SSH on Pi** → Tasks 1, 9, 10. ✓
- **Out-of-scope items (app deep-link, CI auto-deploy) stay out** → not implemented. ✓

**Open risk carried into execution:** exact Astro `experimental.csp` config key names and the `Astro.locals.t` translation-helper API can differ across Astro/Starlight minor versions. Both have concrete in-task fallbacks (Task 2 Step 2; Task 6 Step 1 note). These are the only version-sensitive spots; everything else uses stable APIs.
