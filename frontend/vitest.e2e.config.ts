/// <reference types="vitest/config" />
import { defineConfig } from 'vitest/config'

// Full-stack E2E: spawns the real backend (node environment set per-file). Kept out of the default
// unit run; launch with `npm run test:e2e`. Generous timeouts cover backend start/restart.
export default defineConfig({
  test: {
    include: ['e2e/**/*.e2e.test.ts'],
    globals: true,
    testTimeout: 60_000,
    hookTimeout: 30_000,
    fileParallelism: false,
  },
})
