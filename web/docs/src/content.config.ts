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
