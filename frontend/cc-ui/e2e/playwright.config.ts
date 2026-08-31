import { defineConfig, devices } from '@playwright/test'

const baseURL = process.env.ADMIN_E2E_BASE_URL ?? 'https://admin.omnibioai.org'
const timeout = Number(process.env.ADMIN_E2E_TIMEOUT_MS ?? 30_000)

export default defineConfig({
  globalTeardown: './global-teardown.ts',
  testDir: '.',
  testMatch: '**/*.spec.ts',
  timeout,
  expect: { timeout: Math.min(timeout, 10_000) },
  fullyParallel: false,
  forbidOnly: !!process.env.CI,
  retries: process.env.CI ? 1 : 0,
  workers: 1,
  reporter: process.env.CI ? [['line'], ['html', { outputFolder: 'playwright-report', open: 'never' }]] : 'line',
  outputDir: 'test-results',
  use: {
    baseURL,
    ...devices['Desktop Chrome'],
    headless: process.env.ADMIN_E2E_HEADED !== '1',
    ignoreHTTPSErrors: process.env.ADMIN_E2E_IGNORE_HTTPS_ERRORS === '1',
    screenshot: 'only-on-failure',
    trace: 'retain-on-failure',
    video: 'off',
    serviceWorkers: 'block',
  },
  projects: [
    { name: 'auth-setup', testMatch: /auth\.setup\.ts/ },
    {
      name: 'admin-chrome',
      dependencies: ['auth-setup'],
      testMatch: /admin\.spec\.ts/,
      use: { storageState: 'e2e/.auth/admin.json' },
    },
    { name: 'anonymous-chrome', testMatch: /anonymous\.spec\.ts/ },
  ],
})
