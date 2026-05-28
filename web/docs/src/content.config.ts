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
  i18n: defineCollection({ loader: i18nLoader(), schema: i18nSchema() }),
};
