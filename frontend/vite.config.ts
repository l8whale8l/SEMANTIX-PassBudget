/// <reference types="vitest/config" />
import react from '@vitejs/plugin-react'
import { defineConfig } from 'vite'
import { configDefaults } from 'vitest/config'

// The backend has no CORS and no auth (FRONTEND_API_INTEGRATION §6, FE-GAP-06). We use a
// same-origin dev proxy instead of relaxing CORS on the server: the browser only ever talks to
// the Vite origin, which forwards /api and /health to the local FastAPI process.
const BACKEND = process.env.PASSBUDGET_API_ORIGIN ?? 'http://127.0.0.1:8000'

export default defineConfig({
  plugins: [react()],
  server: {
    proxy: {
      '/api': { target: BACKEND, changeOrigin: true },
      '/health': { target: BACKEND, changeOrigin: true },
    },
  },
  test: {
    environment: 'jsdom',
    globals: true,
    setupFiles: ['./src/test/setup.ts'],
    css: false,
    // Unit/component suite. The full-stack E2E (spawns the real backend) runs via `test:e2e`.
    exclude: [...configDefaults.exclude, 'e2e/**'],
  },
})
