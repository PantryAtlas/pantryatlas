import { defineConfig } from 'vite'
import preact from '@preact/preset-vite'
import { resolve } from 'path'

export default defineConfig({
  root: resolve(__dirname),
  publicDir: 'public',
  plugins: [preact()],
  build: {
    outDir: 'dist',
    emptyOutDir: true,
  },
})
