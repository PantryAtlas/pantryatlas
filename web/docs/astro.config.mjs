import { defineConfig } from 'astro/config';
import starlight from '@astrojs/starlight';

export default defineConfig({
  site: 'https://docs.pantryatlas.org',
  // Astro 6 ships CSP as a stable config option. In 6.3.8 it lives under
  // `security.csp` (verified against the installed zod schema). Astro auto-hashes
  // its own inline <script>/<style> and injects a
  // <meta http-equiv="content-security-policy"> into every static page.
  security: {
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
      // 'wasm-unsafe-eval' is required by Pagefind search (WASM) in production builds.
      // script-src stays fully hash-locked (no 'unsafe-inline') — the security-critical part.
      scriptDirective: { resources: ["'self'", "'wasm-unsafe-eval'"] },
      // 'unsafe-inline' is required for style: Starlight (icon sizing, sidebar
      // depth) and Shiki code blocks emit inline style ATTRIBUTES that CSP hashes
      // cannot cover, and Astro disallows style-src-attr in `directives`. Astro
      // still emits hashes for <style> ELEMENTS, so this only relaxes inline
      // style attributes; no third-party style origins are allowed.
      styleDirective: { resources: ["'self'", "'unsafe-inline'"] },
    },
  },
  integrations: [
    starlight({
      title: 'PantryAtlas Docs',
      defaultLocale: 'en',
      locales: {
        en: { label: 'English' },
      },
      // Pagefind (search) is disabled by default so the site builds on the Pi 5,
      // whose 16KB memory pages crash Pagefind's jemalloc allocator. Production
      // builds on x86 / Cloudflare Pages set DOCS_SEARCH=1 to enable search.
      pagefind: process.env.DOCS_SEARCH === '1',
    }),
  ],
});
