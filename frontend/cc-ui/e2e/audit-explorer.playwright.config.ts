import { defineConfig, devices } from '@playwright/test'

export default defineConfig({
  testDir: '.',
  testMatch: /audit-explorer\.spec\.ts/,
  globalTeardown: './global-teardown.ts',
  timeout: Number(process.env.ADMIN_E2E_TIMEOUT_MS ?? 30_000),
  expect: { timeout: 10_000 },
  workers: 1,
  reporter: 'line',
  outputDir: 'test-results',
  use: {
    baseURL: process.env.ADMIN_E2E_BASE_URL ?? 'https://admin.omnibioai.org',
    ...devices['Desktop Chrome'],
    headless: process.env.ADMIN_E2E_HEADED !== '1',
    serviceWorkers: 'block',
  },
  projects: [
    { name: 'auth-setup', testMatch: /auth\.setup\.ts/, use: { storageState: undefined } },
    { name: 'audit-explorer', dependencies: ['auth-setup'], use: { storageState: 'e2e/.auth/admin.json' } },
  ],
})
