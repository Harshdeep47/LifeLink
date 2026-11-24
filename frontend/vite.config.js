import { defineConfig } from 'vite'
import react from '@vitejs/plugin-react'

export default defineConfig({
  plugins: [react()],
  server: {
    port: 5173,
    proxy: {
      // The local API runs on 8080; proxying keeps the browser same-origin,
      // which avoids CORS entirely in development.
      '/api': {
        target: 'http://127.0.0.1:8080',
        changeOrigin: true,
        rewrite: (path) => path.replace(/^\/api/, ''),
      },
    },
  },
  build: {
    outDir: 'dist',
    // Source maps are useful locally and are deliberately NOT shipped: a
    // public bucket serving .map files publishes the entire frontend source,
    // including comments. Enabled only outside a production build.
    sourcemap: process.env.NODE_ENV !== 'production',
  },
  test: {
    environment: 'jsdom',
    globals: true,
    setupFiles: ['./src/test/setup.js'],
    css: false,
  },
})
