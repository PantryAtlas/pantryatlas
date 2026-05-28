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
      defaultLocale: 'root',
      locales: {
        // English is the `root` locale so it serves at `/` (the canonical docs
        // homepage) rather than `/en/`. `lang` is required on `root` — it is
        // not inferred from the key like the prefixed locales below.
        root: { label: 'English', lang: 'en' },
        es: { label: 'Español', lang: 'es' },
        fr: { label: 'Français', lang: 'fr' },
        ar: { label: 'العربية', lang: 'ar', dir: 'rtl' },
        'zh-cn': { label: '简体中文', lang: 'zh-CN' },
      },
      editLink: {
        baseUrl: 'https://github.com/PantryAtlas/pantryatlas/edit/main/web/docs/',
      },
      // Note: Starlight 0.39+ requires autogenerate to be nested inside items[].
      // The old top-level { label, autogenerate } shorthand was removed in v0.39.0.
      sidebar: [
        { label: 'Start here', translations: { es: 'Empieza aquí', fr: 'Commencer ici', ar: 'ابدأ هنا', 'zh-CN': '从这里开始' }, items: [{ autogenerate: { directory: 'start-here' } }] },
        { label: 'Cooking', translations: { es: 'Cocinar', fr: 'Cuisiner', ar: 'الطبخ', 'zh-CN': '烹饪' }, items: [{ autogenerate: { directory: 'cooking' } }] },
        { label: 'Set up your device', translations: { es: 'Configura tu dispositivo', fr: 'Configurer votre appareil', ar: 'إعداد جهازك', 'zh-CN': '设置你的设备' }, items: [{ autogenerate: { directory: 'setup' } }] },
        { label: 'Community kitchens', translations: { es: 'Cocinas comunitarias', fr: 'Cuisines communautaires', ar: 'المطابخ المجتمعية', 'zh-CN': '社区厨房' }, items: [{ autogenerate: { directory: 'community' } }] },
        { label: 'Maintenance & troubleshooting', translations: { es: 'Mantenimiento y solución de problemas', fr: 'Maintenance et dépannage', ar: 'الصيانة واستكشاف الأخطاء', 'zh-CN': '维护与故障排除' }, items: [{ autogenerate: { directory: 'maintenance' } }] },
        { label: 'Developers', translations: { es: 'Desarrolladores', fr: 'Développeurs', ar: 'المطورون', 'zh-CN': '开发者' }, items: [{ autogenerate: { directory: 'developers' } }] },
        { label: 'Reference', translations: { es: 'Referencia', fr: 'Référence', ar: 'مرجع', 'zh-CN': '参考' }, items: [{ autogenerate: { directory: 'reference' } }] },
      ],
      components: {
        Banner: './src/components/MtBanner.astro',
      },
      // Fonts loaded first so brand.css can reference the DM Sans family name.
      customCss: ['./src/styles/fonts.css', './src/styles/brand.css'],
      // Pagefind (search) is disabled by default so the site builds on the Pi 5,
      // whose 16KB memory pages crash Pagefind's jemalloc allocator. Production
      // builds on x86 / Cloudflare Pages set DOCS_SEARCH=1 to enable search.
      pagefind: process.env.DOCS_SEARCH === '1',
    }),
  ],
});
