import { defineConfig } from 'vite'
import preact from '@preact/preset-vite'
import { resolve } from 'path'

export default defineConfig({
  root: resolve(__dirname),
  publicDir: 'public',
  plugins: [preact()],
  server: {
    proxy: {
      '/navigator': 'http://localhost:8099',
    },
  },
  build: {
    outDir: 'dist',
    emptyOutDir: true,
    rollupOptions: {
      input: {
        // Main app entry (index.html drives this)
        main: resolve(__dirname, 'index.html'),
        // Service worker — emitted as dist/sw.js (no hash, no assets/ prefix)
        sw: resolve(__dirname, 'src/sw.ts'),
      },
      output: {
        // Keep sw.js at root of dist; hashed app assets go to assets/
        entryFileNames: (chunkInfo) => {
          if (chunkInfo.name === 'sw') return 'sw.js';
          return 'assets/[name]-[hash].js';
        },
        chunkFileNames: 'assets/[name]-[hash].js',
        assetFileNames: 'assets/[name]-[hash][extname]',
      },
    },
  },
})
