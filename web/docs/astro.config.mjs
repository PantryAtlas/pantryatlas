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
      // pagefind: false — Pi 5 (aarch64, 16KB pages) crashes Pagefind's jemalloc allocator.
      // Search index must be built on a non-Pi host or via CF Pages build environment.
      // Remove this line before deploying to production.
      pagefind: false,
    }),
  ],
});
