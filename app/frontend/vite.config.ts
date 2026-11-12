import { defineConfig } from 'vite'
import react from '@vitejs/plugin-react-swc'
import tailwindcss from '@tailwindcss/vite'
import path from 'path'

export default defineConfig(({ mode }) => ({
  plugins: [react(), tailwindcss()],
  // `vite build --mode galeria` builds only the dev component gallery
  // (docs/galeria/plano_galeria.md) as one chunk with every asset inlined, so
  // scripts/inline-galeria.mjs can fold it into a single HTML that opens from
  // file:// (Chrome refuses module scripts loaded from file://).
  ...(mode === 'galeria' && {
    base: './',
    build: {
      outDir: 'dist-galeria',
      assetsInlineLimit: Number.MAX_SAFE_INTEGER,
      cssCodeSplit: false,
      rollupOptions: { input: 'galeria.html', output: { inlineDynamicImports: true } },
    },
  }),
  resolve: {
    alias: {
      '@': path.resolve(__dirname, './src'),
    },
  },
  server: {
    port: 5173,
    proxy: {
      '/api': {
        target: 'http://localhost:8000',
        changeOrigin: true,
      },
    },
  },
}))
